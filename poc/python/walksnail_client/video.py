"""Live video for the Walksnail Goggles X.

The feed is plain H.264-over-RTSP (``rtsp://<host>/live.ch01``), so PyAV (FFmpeg)
decodes it with no custom parsing. Requires the ``[video]`` extra:

    pip install -e ".[video]"

A media stream only exists when an air unit is linked (``vtx_connect == 1``).

Low latency & robustness
------------------------
* A background reader decodes as fast as the network allows and keeps **only the
  most recent frame**, so latency never accumulates.
* Decoding is **slice-threaded** (frame threading would delay output by frames)
  with aggressive FFmpeg de-buffering options.
* The reader is **resilient**: corrupt frames (common on UDP packet loss) are
  skipped, and it **auto-reconnects** on stream errors instead of crashing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from . import protocol as p

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np


def _ll_opts(transport: str) -> dict[str, str]:
    """FFmpeg options tuned for low-latency live FPV."""
    return {
        "rtsp_transport": transport,
        "rtsp_flags": "prefer_tcp" if transport == "tcp" else "none",
        "fflags": "nobuffer",
        "flags": "low_delay",
        "max_delay": "0",
        "reorder_queue_size": "0",
        "probesize": "100000",
        "analyzeduration": "0",
        "timeout": "5000000",  # socket timeout, microseconds (ffmpeg >=6)
    }


def _open(host: str, transport: str):
    import av  # lazy import so the control plane needs no video deps

    container = av.open(p.rtsp_url(host), options=_ll_opts(transport))
    stream = container.streams.video[0]
    stream.thread_type = "SLICE"  # parallel decode without buffering frames
    return container, stream


def live_frames(host: str = p.DEFAULT_HOST, *, bgr: bool = True,
                transport: str = "tcp") -> Iterator["np.ndarray"]:
    """Yield decoded frames as numpy arrays (BGR by default, else RGB).

    Sequential generator (no reconnect) — fine for processing/recording. For a
    low-latency, self-healing live view use :func:`show_live`.
    """
    import av

    fmt = "bgr24" if bgr else "rgb24"
    container, stream = _open(host, transport)
    try:
        for packet in container.demux(stream):
            try:
                for frame in packet.decode():
                    yield frame.to_ndarray(format=fmt)
            except av.error.FFmpegError:
                continue  # skip corrupt frame
    finally:
        container.close()


class LatestFrameReader:
    """Background RTSP decoder exposing only the newest frame; self-healing."""

    def __init__(self, host: str = p.DEFAULT_HOST, *, transport: str = "tcp"):
        self.host = host
        self.transport = transport
        self._frame: "np.ndarray | None" = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.frames_decoded = 0
        self.last_error: BaseException | None = None

    def start(self) -> "LatestFrameReader":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        import av

        connect_fails = 0
        while not self._stop.is_set():
            try:
                container, stream = _open(self.host, self.transport)
                connect_fails = 0  # connected — reset backoff
            except Exception as e:  # noqa: BLE001 — connect failed; back off + retry
                self.last_error = e
                # Exponential backoff (0.5s → 5s cap). Rapid reconnects can wedge
                # the goggles' single-session RTSP server, so don't hammer it.
                connect_fails += 1
                delay = min(0.5 * (2 ** (connect_fails - 1)), 5.0)
                if self._stop.wait(delay):
                    return
                continue
            try:
                for packet in container.demux(stream):
                    if self._stop.is_set():
                        break
                    try:
                        for frame in packet.decode():
                            img = frame.to_ndarray(format="bgr24")
                            with self._lock:
                                self._frame = img
                            self.frames_decoded += 1
                    except av.error.FFmpegError as e:
                        self.last_error = e  # corrupt frame (UDP loss) — skip
                        continue
            except av.error.FFmpegError as e:
                self.last_error = e  # stream hiccup/EOF — reconnect
            finally:
                container.close()
            if self._stop.wait(0.1):  # brief pause before reconnect
                return

    def read(self) -> "np.ndarray | None":
        """Most recent frame, or ``None`` if none decoded yet."""
        with self._lock:
            return self._frame

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


class _TelemetryPoller:
    """Polls ``devicestate`` in the background for the OSD overlay."""

    def __init__(self, host: str, interval: float = 0.5):
        self.host = host
        self.interval = interval
        self.state: dict = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "_TelemetryPoller":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        from .client import WalksnailClient
        c = WalksnailClient(self.host, timeout=2.0)
        while not self._stop.wait(self.interval):
            try:
                self.state = c.get_device_state()
            except Exception:  # noqa: BLE001 — OSD is best-effort
                pass

    def stop(self) -> None:
        self._stop.set()


def _draw_osd(frame, state: dict) -> None:
    import cv2

    v = state.get("gas_voltage")
    line = "  ".join(filter(None, [
        f"BAT {v:.1f}V" if isinstance(v, (int, float)) else None,
        f"GTEMP {state.get('gas_tempeture')}C" if "gas_tempeture" in state else None,
        f"VTX {'LINK' if state.get('vtx_connect') else 'NO'}",
        f"{state['bitrate'] / 1e6:.1f}Mbps" if state.get("bitrate") else None,
    ]))
    if not line:
        return
    cv2.putText(frame, line, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 0), 4, cv2.LINE_AA)            # outline for contrast
    cv2.putText(frame, line, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 0), 1, cv2.LINE_AA)


def play_url(url: str, *, window: str = "Walksnail DVR") -> None:
    """Play a recorded clip (URL or local path) at real speed.

    Unlike the live view this honours each frame's PTS so playback runs at the
    recorded rate. Keys: 'q'/ESC quit, space pause/resume.
    """
    import av
    import cv2

    container = av.open(url)
    try:
        stream = container.streams.video[0]
        tb = float(stream.time_base) if stream.time_base else 0.0
        start = time.monotonic()
        first_pts = None
        paused = False
        for frame in container.decode(stream):
            img = frame.to_ndarray(format="bgr24")
            if tb and frame.pts is not None:
                pts = frame.pts * tb
                first_pts = pts if first_pts is None else first_pts
                delay = (start + (pts - first_pts)) - time.monotonic()
                if delay > 0:
                    time.sleep(min(delay, 1.0))
            cv2.imshow(window, img)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = not paused
                while paused:
                    k = cv2.waitKey(50) & 0xFF
                    if k == ord(" "):
                        paused = False
                    elif k in (ord("q"), 27):
                        return
    finally:
        container.close()
        cv2.destroyAllWindows()


def show_live(host: str = p.DEFAULT_HOST, *, window: str = "Walksnail Live",
              transport: str = "tcp", osd: bool = False) -> None:
    """Open a window and render the live feed (latest-frame, low latency).

    Keys: 'q'/ESC quit, 's' save a PNG snapshot. ``transport='udp'`` may lower
    latency further (resilient to loss). ``osd=True`` overlays telemetry.
    """
    import cv2

    reader = LatestFrameReader(host, transport=transport).start()
    tele = _TelemetryPoller(host).start() if osd else None
    waiting_since = time.monotonic()
    try:
        while True:
            frame = reader.read()
            if frame is None:
                if time.monotonic() - waiting_since > 8 and reader.last_error:
                    print(f"  (still connecting… last error: {reader.last_error})")
                    waiting_since = time.monotonic()
                if cv2.waitKey(5) & 0xFF in (ord("q"), 27):
                    break
                continue
            if tele is not None and tele.state:
                _draw_osd(frame, tele.state)
            cv2.imshow(window, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                fn = time.strftime("walksnail_%Y%m%d_%H%M%S.png")
                cv2.imwrite(fn, frame)
                print(f"  saved {fn}")
    finally:
        reader.stop()
        if tele is not None:
            tele.stop()
        cv2.destroyAllWindows()
