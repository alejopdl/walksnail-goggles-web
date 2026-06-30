"""Show the live drone feed in a window (needs the ``[video]`` extra + a linked VTX).

    pip install -e ".[video]"
    python examples/live_view.py
"""

from walksnail_client import WalksnailClient
from walksnail_client.video import show_live


def main() -> None:
    c = WalksnailClient()
    if not c.vtx_connected():
        raise SystemExit("vtx_connect=0 — power the drone/VTX and link it first.")
    print("streaming", c.rtsp_url, "(press q or ESC to quit)")
    show_live(c.host)


if __name__ == "__main__":
    main()
