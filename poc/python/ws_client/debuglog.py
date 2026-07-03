"""Session debug logging for WS WiFi Stream.

Enabled with ``--debug`` (or ``WS_DEBUG=1``). Writes a timestamped session log
to the user's log directory AND echoes to the console, capturing:

* every control request to the goggles (command, duration, ok/error),
* the RTSP reader lifecycle (connect / first frame / stream errors / reconnect
  with backoff / stop),
* VTX link transitions (first-seen / LINKED / LOST),
* a request-rate summary every ~10 s (to spot goggles saturation).

Set ``WS_DEBUG_VERBOSE=1`` (or ``--debug-verbose``) to also log full request
bodies and raw responses.

The point: analyse a session afterwards for reconnection bugs, hangs, errors,
and whether we're hammering the goggles — for both the live view and the gallery.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_LOG = logging.getLogger("wsdebug")

_enabled = False
_verbose = False
_logfile: "Path | None" = None

# request-rate tracking (goggles-bound requests only)
_req_lock = threading.Lock()
_req_count = 0
_req_window_start = 0.0


def enabled() -> bool:
    return _enabled


def verbose() -> bool:
    return _verbose


def logfile() -> "Path | None":
    return _logfile


def _log_dir() -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Logs" / "WS-WiFi-Stream"
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        d = Path(base) / "WS-WiFi-Stream" / "logs"
    else:
        d = Path.home() / ".local" / "state" / "ws-wifi-stream"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup(enable: bool = False, verbose_bodies: bool = False) -> "Path | None":
    """Configure logging. Returns the log file path (or None if disabled)."""
    global _enabled, _verbose, _logfile, _req_window_start
    _enabled = enable or os.environ.get("WS_DEBUG") == "1"
    _verbose = verbose_bodies or os.environ.get("WS_DEBUG_VERBOSE") == "1"
    if not _enabled:
        return None

    _logfile = _log_dir() / f"session-{datetime.now():%Y%m%d-%H%M%S}.log"
    _LOG.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d  %(message)s",
                            datefmt="%H:%M:%S")
    fh = logging.FileHandler(_logfile, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    _LOG.handlers[:] = [fh, sh]
    _LOG.propagate = False
    _req_window_start = time.monotonic()
    event(f"=== DEBUG SESSION START (verbose={_verbose}) ===")
    return _logfile


def event(msg: str) -> None:
    """Log a lifecycle/state event."""
    if _enabled:
        _LOG.debug(msg)


def _tick_rate() -> None:
    """Count a goggles request; emit a rate summary every ~10 s."""
    global _req_count, _req_window_start
    emit = False
    with _req_lock:
        _req_count += 1
        now = time.monotonic()
        span = now - _req_window_start
        if span >= 10.0:
            n, secs = _req_count, span
            _req_count = 0
            _req_window_start = now
            emit = True
    if emit:
        _LOG.debug(f"[rate] {n} goggles requests in {secs:.1f}s ({n / secs:.1f}/s)")


def req(kind: str, name: str, dur_ms: float, ok: bool, detail: str = "") -> None:
    """Log one request to the goggles (control HTTP, download, etc.)."""
    if not _enabled:
        return
    _tick_rate()
    status = "ok " if ok else "ERR"
    tail = f"  {detail}" if detail else ""
    _LOG.debug(f"[{kind}] {name}  {dur_ms:.0f}ms  {status}{tail}")
