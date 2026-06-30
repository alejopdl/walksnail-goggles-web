"""
Walksnail Ground Station — Standalone launcher.

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

def _find_free_port(preferred: int = 8080) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
  ║   🚁  Walksnail Ground Station            ║
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

    # ── 1. Parse args (fast — no heavy imports yet) ──────────────────────
    import argparse

    parser = argparse.ArgumentParser(
        description="Walksnail Ground Station — web-based FPV goggles control"
    )
    parser.add_argument("--host", default="192.168.42.1",
                        help="Goggles IP (default: 192.168.42.1)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Web UI port (default: 8080, auto-adjusted if busy)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open browser automatically")
    args = parser.parse_args()   # prints help and exits if --help

    port = _find_free_port(args.port)
    static_dir = Path(_meipass_or("static"))

    # ── 2. Patch server STATIC_DIR BEFORE importing server.py ────────────
    #       server.py mounts StaticFiles at module level — we must set the
    #       correct path before that code runs.
    import walksnail_client.web.server as srv
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
