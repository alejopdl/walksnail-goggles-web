"""
WS WiFi Stream — Standalone launcher.

Entry point for PyInstaller. Defers ALL server imports until after
sys._MEIPASS is available, so static files are found correctly in
both frozen and development modes.
"""
from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
import webbrowser
import multiprocessing
from pathlib import Path


# ── PyInstaller resource path ──────────────────────────────────────────────

def _meipass_or(rel: str) -> str:
    """Resolve path relative to the bundle (frozen) or source tree (dev)."""
    base = getattr(sys, "_MEIPASS", Path(__file__).parent)
    return str(Path(base) / rel)


# ── Helpers ────────────────────────────────────────────────────────────────

def _find_free_port(preferred: int | None = None) -> int:
    """Pick a port that's actually free.

    Prefers an uncommon port so we don't collide with common dev servers
    (3000/5000/8000/8080…). If the preferred/candidate ports are busy, keep
    trying; as a last resort let the OS assign any free port (bind to 0).

    Note: SO_REUSEADDR is intentionally NOT set here — we want the bind to
    genuinely fail when the port is taken, so busy ports are detected correctly.
    """
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates += [8477, 8478, 8479, 8480, 8481, 0]  # uncommon range, then "any free"
    for port in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("No free port found")


def _wait_for_server(port: int, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _print_banner(port: int) -> None:
    print(f"""
  ╔══════════════════════════════════════════╗
  ║   🚁  WS WiFi Stream            ║
  ║   http://localhost:{port:<5}                 ║
  ║                                          ║
  ║   The app opened in your browser.        ║
  ║   Keep this window open while using it.  ║
  ║   Press Ctrl+C here to quit.             ║
  ╚══════════════════════════════════════════╝
""", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    # ── 0. Windows multiprocessing support ───────────────────────────────────
    multiprocessing.freeze_support()

    # Windows consoles often default to cp1252, which can't encode the banner's
    # emoji / box-drawing characters and would crash on the first print. Force
    # UTF-8 (with replacement) so the app never dies on output encoding.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # ── 1. Parse args (fast — no heavy imports yet) ──────────────────────
    import argparse

    parser = argparse.ArgumentParser(
        description="WS WiFi Stream — web-based FPV goggles control"
    )
    parser.add_argument("--host", default="192.168.42.1",
                        help="Goggles IP (default: 192.168.42.1)")
    parser.add_argument("--port", type=int, default=None,
                        help="Web UI port (default: auto — picks an uncommon free port)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open browser automatically")
    args = parser.parse_args()   # prints help and exits if --help

    port = _find_free_port(args.port)
    static_dir = Path(_meipass_or("static"))

    # ── 2. Patch server STATIC_DIR BEFORE importing server.py ────────────
    #       server.py mounts StaticFiles at module level — we must set the
    #       correct path before that code runs.
    import ws_client.web.server as srv
    srv.STATIC_DIR = static_dir

    # ── 3. Rebuild the FastAPI app's static mount with the correct path ───
    from fastapi.staticfiles import StaticFiles

    # Remove any previously registered static mount (from module-level init)
    srv.app.routes[:] = [
        r for r in srv.app.routes
        if not (hasattr(r, "name") and r.name == "static")
    ]
    srv.app.mount("/", StaticFiles(directory=str(static_dir), html=True),
                  name="static")

    # ── 4. Configure goggles host ─────────────────────────────────────────
    srv._goggles_host = args.host
    srv._client = None  # lazy-created on first request
    # This is the packaged app (no window of its own): quit when the browser
    # tab closes, so we never leave an invisible background process running.
    srv._auto_shutdown_enabled = True

    # ── 5. Start uvicorn in a background thread ───────────────────────────
    import uvicorn

    def _run():
        uvicorn.run(srv.app, host="127.0.0.1", port=port,
                    log_level="warning", access_log=False)

    threading.Thread(target=_run, daemon=True).start()

    # ── 6. Wait for server ready ──────────────────────────────────────────
    print(f"\n  Starting on port {port}…", flush=True)
    if not _wait_for_server(port):
        print("  ERROR: server failed to start. Check your installation.",
              file=sys.stderr)
        sys.exit(1)

    _print_banner(port)

    # ── 7. Open browser ───────────────────────────────────────────────────
    url = f"http://localhost:{port}"
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    # ── 8. Block until Ctrl+C ─────────────────────────────────────────────
    stop = threading.Event()

    def _bye(sig, frame):
        print("\n  Shutting down… bye! 👋", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _bye)
    signal.signal(signal.SIGTERM, _bye)
    stop.wait()


if __name__ == "__main__":
    main()
