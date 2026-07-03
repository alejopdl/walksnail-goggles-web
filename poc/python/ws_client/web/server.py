"""
FPV goggles — Web Ground Station backend.

FastAPI server providing:
  • MJPEG live video stream from the goggles RTSP feed (latest-frame, self-healing)
  • WebSocket telemetry push (devicestate every 500 ms)
  • REST API: device info, telemetry poll, DVR list/download/delete, settime
  • Serves the SPA frontend from ./static/

Usage:
    pip install -e ".[web]"
    ws-web                           # goggles at 192.168.42.1, web on :8080
    ws-web --host 127.0.0.1:18080   # adb tunnel mode
    ws-web --bind 127.0.0.1          # localhost only (single-machine use)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import signal
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import AsyncGenerator

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from ws_client import debuglog
from ws_client import protocol as p
from ws_client.client import WSClient
from ws_client.video import LatestFrameReader

# VTX debounce: only accept a link-state change after this many agreeing polls,
# so a single flaky poll (common while the goggles boot) doesn't flap the UI.
VTX_DEBOUNCE = 2
_vtx_stable: "bool | None" = None    # debounced VTX link state (what the UI sees)
_vtx_pending_count = 0               # consecutive polls disagreeing with _vtx_stable
_records_busy = False                # a heavy DVR query is in flight; telemetry yields

STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# Module-level singletons (configured at startup via main())
#
# These are set once during startup and shared across all requests.
# The _reader is lazy-started on first /video/stream request and
# persists until transport changes or an explicit restart.
# ---------------------------------------------------------------------------

_goggles_host: str = p.DEFAULT_HOST      # goggles HTTP host (control/records/files)
_rtsp_host: str = ""                      # goggles RTSP host; "" → fall back to _goggles_host
_client: WSClient | None = None   # HTTP control client (lazy)
_client_timeout: float = 4.0             # per-request HTTP timeout (s); raise for tunnels

_reader: LatestFrameReader | None = None  # background RTSP decoder thread
_reader_lock = threading.Lock()           # protects _reader create/swap
_current_transport: str = "tcp"           # "tcp" or "udp"
_stream_start_time: float = 0.0           # monotonic timestamp for uptime calc


def _get_client() -> WSClient:
    """Lazy-initialise and return the shared HTTP control client.

    Default 4s timeout — long enough for the goggles to respond over a Wi-Fi
    hop, short enough not to block the event loop unduly. Raise it with
    ``--timeout`` when driving the goggles through a slower adb/USB tunnel,
    where the large records response can exceed 4s.
    """
    global _client
    if _client is None:
        _client = WSClient(_goggles_host, timeout=_client_timeout)
    return _client


def _get_or_start_reader(transport: str = "tcp") -> LatestFrameReader:
    """Return the running RTSP reader, (re)starting only when needed.

    If the transport changes (tcp↔udp), the old reader is stopped and a
    new one is created. Otherwise the existing reader is reused — multiple
    browser tabs share the same decoder thread.
    """
    global _reader, _current_transport, _stream_start_time
    with _reader_lock:
        if _reader is None or transport != _current_transport:
            # A restart (previous reader existed) needs a settle delay so the
            # goggles release their single RTSP session before we reconnect.
            restart = _reader is not None
            if _reader is not None:
                debuglog.event(f"[reader] stopping (transport change "
                               f"{_current_transport}->{transport})")
                _reader.stop()
            _current_transport = transport
            rtsp_host = _rtsp_host or _goggles_host
            delay = 1.5 if restart else 0.0
            debuglog.event(f"[reader] starting (transport={transport}, "
                           f"host={rtsp_host}, settle={delay:.1f}s)")
            _reader = LatestFrameReader(rtsp_host, transport=transport,
                                        start_delay=delay).start()
            _stream_start_time = time.monotonic()
    return _reader


# ---------------------------------------------------------------------------
# MJPEG helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_CACHE: dict[str, bytes] = {}


def _make_placeholder(msg: str, sub: str, quality: int, w: int, h: int) -> bytes:
    """Render a dark placeholder frame as JPEG bytes (cached by key).

    Shown in the MJPEG stream while the RTSP reader has no decoded frame.
    Uses a subtle dot-grid and concentric circles for visual interest.
    The result is cached so repeated calls with the same arguments
    don't re-render (critical at 30 fps).
    """
    key = f"{msg}|{sub}|{quality}|{w}|{h}"
    if key not in _PLACEHOLDER_CACHE:
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # Subtle dot-grid
        for y in range(0, h, 48):
            for x in range(0, w, 48):
                cv2.circle(img, (x, y), 1, (18, 22, 32), -1)
        # Centre circle decoration
        cx, cy = w // 2, h // 2
        cv2.circle(img, (cx, cy), 60, (25, 32, 50), 2)
        cv2.circle(img, (cx, cy), 40, (20, 26, 40), 2)
        # Main message
        font = cv2.FONT_HERSHEY_SIMPLEX
        fs = min(1.1, 1.1 * w / 1920)
        tw, _ = cv2.getTextSize(msg, font, fs, 2)[0]
        cv2.putText(img, msg, (cx - tw // 2, cy - 10),
                    font, fs, (55, 70, 95), 2, cv2.LINE_AA)
        # Sub-message
        if sub:
            fs2 = fs * 0.65
            tw2, _ = cv2.getTextSize(sub, font, fs2, 1)[0]
            cv2.putText(img, sub, (cx - tw2 // 2, cy + 30),
                        font, fs2, (38, 48, 65), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        _PLACEHOLDER_CACHE[key] = buf.tobytes() if ok else b""
    return _PLACEHOLDER_CACHE[key]


def _encode_frame(frame: np.ndarray, quality: int, scale: float) -> bytes:
    """Resize (if scale < 1) and JPEG-encode a BGR numpy frame."""
    if scale < 0.98:
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


# Cache last rendered placeholder state so we don't spam the HTTP client
_last_vtx_state: bool | None = None


async def _mjpeg_gen(
    reader: LatestFrameReader,
    quality: int,
    scale: float,
    fps: int,
) -> AsyncGenerator[bytes, None]:
    """
    Yield MJPEG boundary+JPEG pairs forever (until client disconnects).

    • When the reader has a decoded frame → encode + yield it.
    • When no frame yet → yield a dark placeholder slate.
    • JPEG encoding and placeholder generation are offloaded to the thread
      executor so the FastAPI event loop is never blocked.
    """
    interval = 1.0 / max(1, fps)
    last_ts = 0.0
    loop = asyncio.get_running_loop()

    # Resolution of placeholder
    pw, ph = int(1920 * scale), int(1080 * scale)

    while True:
        now = time.monotonic()
        gap = interval - (now - last_ts)
        if gap > 0:
            await asyncio.sleep(gap)

        frame = reader.read()

        if frame is not None:
            jpeg = await loop.run_in_executor(None, _encode_frame, frame, quality, scale)
        else:
            # Show a contextual placeholder while waiting for the first frame
            last_err = reader.last_error
            err_s = str(last_err).lower() if last_err else ""
            if reader.wedged:
                msg, sub = ("Live feed stuck",
                            "Reboot the goggles to recover (RTSP session wedged)")
            elif last_err and "empty" in err_s:
                msg, sub = "No VTX signal", "Power on the drone / air unit"
            elif "invalid data" in err_s or "404" in err_s or "401" in err_s:
                # RTSP reachable but no decodable stream — almost always the feed
                # is already held by another client (the goggles serve ONE RTSP
                # session). Closing the phone app's live view frees it.
                msg, sub = "Live feed unavailable", "Another app may be holding the stream — close the phone app's live view"
            elif "timed out" in err_s or "timeout" in err_s or "refused" in err_s:
                msg, sub = "Cannot reach video", "Goggles RTSP not responding — check Wi-Fi / tunnel"
            elif last_err:
                msg, sub = "Stream error", str(last_err)[:60]
            else:
                msg, sub = "Connecting to RTSP…", reader.transport.upper()
            jpeg = await loop.run_in_executor(
                None, _make_placeholder, msg, sub, quality, pw, ph
            )

        if jpeg:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
            last_ts = time.monotonic()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="WS WiFi Stream", docs_url=None, redoc_url=None)


# ── Lifecycle / auto-shutdown ---------------------------------------------
# The packaged desktop app has no window of its own — the browser tab IS the UI.
# The launcher enables auto-shutdown; each open tab holds a telemetry WebSocket,
# so when the last tab closes we quit after a short grace period (no orphaned
# background process). The UI's "Quit" button hits /api/shutdown directly.
_auto_shutdown_enabled = False
_active_clients = 0
_SHUTDOWN_GRACE = 6.0  # seconds to wait for a reconnect before quitting


def _quit_process() -> None:
    """Stop the whole app gracefully. SIGINT is handled by both the launcher and
    standalone uvicorn, so this shuts down cleanly in either context."""
    os.kill(os.getpid(), signal.SIGINT)


def _do_autoshutdown() -> None:
    # Quit only if still no clients after the grace period (tab wasn't reopened).
    if _auto_shutdown_enabled and _active_clients <= 0:
        _quit_process()


def _maybe_autoshutdown() -> None:
    if _auto_shutdown_enabled and _active_clients <= 0:
        threading.Timer(_SHUTDOWN_GRACE, _do_autoshutdown).start()


@app.post("/api/shutdown")
async def api_shutdown():
    """Explicit 'Quit' from the UI: reply first, then exit a moment later."""
    threading.Timer(0.3, _quit_process).start()
    return {"ok": True}


# ── Video ------------------------------------------------------------------

@app.get("/video/stream")
async def video_stream(
    transport: str = Query("tcp", pattern="^(tcp|udp)$"),
    quality: int = Query(82, ge=10, le=95),
    scale: float = Query(1.0, ge=0.2, le=1.0),
    fps: int = Query(30, ge=1, le=60),
):
    """MJPEG multipart stream. Keeps streaming even while waiting for frames."""
    reader = _get_or_start_reader(transport)
    return StreamingResponse(
        _mjpeg_gen(reader, quality, scale, fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/stream/status")
async def stream_status():
    """Return reader health: frames decoded, last error, transport, uptime."""
    with _reader_lock:
        r = _reader
    if r is None:
        return {
            "running": False, "frames_decoded": 0, "last_error": None,
            "transport": None, "uptime_s": 0,
        }
    return {
        "running": not r._stop.is_set(),
        "frames_decoded": r.frames_decoded,
        "last_error": str(r.last_error) if r.last_error else None,
        "transport": _current_transport,
        "uptime_s": round(time.monotonic() - _stream_start_time, 1),
    }


@app.post("/api/stream/restart")
async def stream_restart(transport: str = Query("tcp", pattern="^(tcp|udp)$")):
    """Force-stop and restart the RTSP reader (transport change or manual recovery)."""
    global _reader, _current_transport, _stream_start_time
    debuglog.event(f"[reader] manual restart requested (transport={transport})")
    with _reader_lock:
        if _reader:
            _reader.stop()
        _current_transport = transport
        rtsp_host = _rtsp_host or _goggles_host
        # 1.5s settle so the goggles free the single RTSP session before reconnect.
        _reader = LatestFrameReader(rtsp_host, transport=transport,
                                    start_delay=1.5).start()
        _stream_start_time = time.monotonic()
    return {"ok": True, "transport": transport}


# ── System -----------------------------------------------------------------

@app.get("/api/online")
async def api_online():
    """Ping the goggles. Returns {online: bool} — never raises."""
    try:
        return {"online": _get_client().online()}
    except Exception:
        return {"online": False}


@app.get("/api/info")
async def api_info():
    """Device version, serials, HW revision."""
    try:
        info = _get_client().get_version()
        return {
            "goggles_sn": info.goggles_sn,
            "goggles_hw": info.goggles_hw,
            "goggles_sw": info.goggles_sw,
            "tx_sn": info.tx_sn,
            "tx_hw": info.tx_hw,
            "tx_sw": info.tx_sw,
            "vtx_present": info.vtx_present,
        }
    except Exception as exc:
        raise HTTPException(503, detail=str(exc))


@app.get("/api/state")
async def api_state():
    """One-shot devicestate poll (for REST clients; prefer /ws/telemetry)."""
    try:
        return _get_client().get_device_state()
    except Exception as exc:
        raise HTTPException(503, detail=str(exc))


@app.post("/api/settime")
async def api_settime():
    """Sync the goggles clock to the server's local time."""
    try:
        _get_client().set_time()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


# ── DVR --------------------------------------------------------------------

@app.get("/api/records")
async def api_records(start: int = 0, limit: int = 500):
    """List DVR clips. Returns {total, rows: [{szFileName, duration}, ...]}.

    ``query_record`` is heavy on the goggles, so we: cap an over-large limit,
    run it off the event loop, give it a generous timeout, and flag
    ``_records_busy`` so the telemetry loop pauses (no concurrent hammering).
    """
    global _records_busy
    limit = max(1, min(limit, 5000))  # the goggles hold few clips; huge limits are slow
    loop = asyncio.get_running_loop()
    _records_busy = True
    debuglog.event(f"[dvr] records query start (limit={limit})")
    try:
        result = await loop.run_in_executor(
            None, lambda: _get_client().list_records(start, limit, timeout=15.0))
        debuglog.event(f"[dvr] records query ok ({len(result.get('rows', []))} rows)")
        return result
    except Exception as exc:
        debuglog.event(f"[dvr] records query FAILED: {type(exc).__name__}: {exc}")
        raise HTTPException(503, detail=str(exc))
    finally:
        _records_busy = False


@app.delete("/api/records/{filename}")
async def api_delete(filename: str):
    try:
        _get_client().delete_record(filename)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


@app.get("/api/records/{filename}/download")
async def api_download(filename: str, inline: bool = False):
    """Proxy-stream a DVR clip from the goggles to the browser.

    ``inline=1`` serves the clip with ``Content-Disposition: inline`` so a
    browser ``<video>`` element plays it in place instead of forcing a save.
    The goggles' file server has no HTTP Range support, so inline playback is
    progressive-from-start (no seeking) — acceptable for the short DVR clips.
    """
    url = p.record_url(filename, _goggles_host)

    def _generate():
        with urllib.request.urlopen(url, timeout=120) as resp:
            while chunk := resp.read(1 << 16):
                yield chunk

    disposition = "inline" if inline else "attachment"
    safe_filename = filename.replace('"', '').replace('\n', '').replace('\r', '')
    return StreamingResponse(
        _generate(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'{disposition}; filename="{safe_filename}"'},
    )


# ── Telemetry WebSocket ----------------------------------------------------

@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    """Push devicestate JSON every 500 ms. Sends {type, data} or {type, message}.

    Also doubles as the liveness signal for auto-shutdown: while a browser tab is
    open it holds this socket; when it closes, the client count drops and the app
    may quit (see _maybe_autoshutdown)."""
    global _active_clients, _vtx_stable, _vtx_pending_count
    await ws.accept()
    _active_clients += 1
    debuglog.event(f"[ws] telemetry client connected (active={_active_clients})")
    client = _get_client()
    loop = asyncio.get_running_loop()
    err_streak = 0
    try:
        while True:
            # Yield to a heavy DVR query so we don't pile concurrent requests onto
            # the goggles' tiny HTTP server (which makes the gallery time out).
            if _records_busy:
                await asyncio.sleep(0.3)
                continue
            try:
                # Short timeout so a slow/booting goggles doesn't stall polling.
                state = await loop.run_in_executor(
                    None, lambda: client.get_device_state(timeout=2.0))
                err_streak = 0
                raw = bool(state.get("vtx_connect"))
                # Debounce the link state (ignore single-poll blips).
                if _vtx_stable is None:
                    _vtx_stable = raw
                    _vtx_pending_count = 0
                    debuglog.event(f"[vtx] initial state: "
                                   f"{'LINKED' if raw else 'NO VTX'}")
                elif raw != _vtx_stable:
                    _vtx_pending_count += 1
                    if _vtx_pending_count >= VTX_DEBOUNCE:
                        _vtx_stable = raw
                        _vtx_pending_count = 0
                        debuglog.event(f"[vtx] transition: "
                                       f"{'NO VTX -> LINKED' if raw else 'LINKED -> NO VTX'}")
                else:
                    _vtx_pending_count = 0
                # Send the DEBOUNCED link state so the UI never flaps on a blip.
                state["vtx_connect"] = 1 if _vtx_stable else 0
                await ws.send_json({"type": "state", "data": state})
            except Exception as exc:
                # Transient poll error: hold the last state (don't flap the UI).
                # Only report a real outage after several consecutive failures.
                err_streak += 1
                debuglog.event(f"[ws] telemetry poll error #{err_streak}: "
                               f"{type(exc).__name__}: {exc}")
                if err_streak >= 6:
                    await ws.send_json({"type": "error", "message": str(exc)})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _active_clients -= 1
        debuglog.event(f"[ws] telemetry client disconnected (active={_active_clients})")
        _maybe_autoshutdown()


# ── Static SPA (must be mounted last) -------------------------------------
# check_dir=False so importing this module never fails when STATIC_DIR isn't the
# real location yet. In a frozen (PyInstaller) build the launcher patches
# STATIC_DIR and re-mounts this route with the correct bundled path; in dev the
# directory already exists next to this file.

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True, check_dir=False), name="static")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _acquire_single_instance_lock(host: str):
    """Ensure only ONE ground station targets a given goggles host.

    The goggles' RTSP server is single-session: two server instances streaming
    the same goggles fight over (and can wedge) that one session. We take an
    exclusive, OS-level advisory lock on a per-host lockfile. A second instance
    for the same host exits with a clear message instead of stealing the stream.

    Returns the open lock file handle (keep it alive for the process lifetime),
    or ``None`` on platforms without ``fcntl`` (lock simply not enforced there).
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-POSIX
        return None
    key = hashlib.sha1(host.encode()).hexdigest()[:12]
    lock_path = Path(tempfile.gettempdir()) / f"ws-web-{key}.lock"
    fh = open(lock_path, "a+")  # don't truncate — a loser must still read the PID
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            prev = lock_path.read_text().strip() or "another process"
        except OSError:
            prev = "another process"
        print(
            f"\n  ✗ A WS WiFi Stream is already running for {host}\n"
            f"    (held by PID {prev}; lockfile {lock_path}).\n"
            f"    Only one instance may stream a goggles at a time — the RTSP\n"
            f"    feed is single-session. Open the existing UI in your browser,\n"
            f"    or stop that instance first.\n",
            file=sys.stderr,
        )
        fh.close()
        sys.exit(1)
    fh.seek(0); fh.truncate(); fh.write(str(os.getpid())); fh.flush()
    return fh


def main() -> None:
    """CLI entry point for ``ws-web``.

    Parses --host, --port, --bind and starts the uvicorn server.
    Prints a startup banner with local and LAN URLs.
    """
    parser = argparse.ArgumentParser(
        description="FPV goggles — Web Ground Station"
    )
    parser.add_argument(
        "--host", default=p.DEFAULT_HOST,
        help="Goggles AP address (default: 192.168.42.1). "
             "Use 127.0.0.1:18080 when tunnelling via adb."
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Web server port (default: 8080)"
    )
    parser.add_argument(
        "--bind", default="127.0.0.1",
        help="Bind address. Default 127.0.0.1 limits access to this machine only. "
             "Use 0.0.0.0 to expose the ground station to your entire LAN."
    )
    parser.add_argument(
        "--timeout", type=float, default=4.0,
        help="HTTP control timeout in seconds (default: 4.0). Raise it (e.g. 12) "
             "when driving the goggles through a slow adb/USB tunnel."
    )
    parser.add_argument(
        "--rtsp-host", default="",
        help="Separate host:port for the RTSP video feed. Only needed in tunnel "
             "mode, where control (port 80) and video (port 554) ride different "
             "local ports — e.g. --host 127.0.0.1:18080 --rtsp-host 127.0.0.1:18554. "
             "Defaults to --host (direct Wi-Fi, where both share one IP)."
    )
    parser.add_argument(
        "--allow-multi", action="store_true",
        help="Skip the single-instance lock. By default a second server for the "
             "same goggles is refused (the RTSP feed is single-session)."
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Write a session debug log (goggles requests, RTSP reconnects, "
             "VTX transitions, request rate)."
    )
    parser.add_argument(
        "--debug-verbose", action="store_true",
        help="Like --debug but also logs full request/response bodies."
    )
    args = parser.parse_args()

    log_path = debuglog.setup(args.debug or args.debug_verbose, args.debug_verbose)
    if log_path:
        print(f"\n  🐞 DEBUG MODE — session log: {log_path}")

    # Refuse a second instance for the same goggles unless explicitly allowed.
    _lock = None if args.allow_multi else _acquire_single_instance_lock(args.host)

    global _goggles_host, _rtsp_host, _client, _client_timeout
    _goggles_host = args.host
    _rtsp_host = args.rtsp_host
    _client_timeout = args.timeout
    _client = None  # lazy-created on first request

    print(f"\n  🚁  WS WiFi Stream")
    print(f"      Goggles → http://{args.host}")
    if args.rtsp_host:
        print(f"      RTSP    → rtsp://{args.rtsp_host}{p.RTSP_PATH}")
    print(f"      Web UI  → http://localhost:{args.port}")
    if args.bind == "0.0.0.0":
        import socket
        try:
            ip = socket.gethostbyname(socket.gethostname())
            print(f"      LAN     → http://{ip}:{args.port}")
        except Exception:
            pass
    print(f"      Ctrl+C to stop\n")

    uvicorn.run(app, host=args.bind, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
