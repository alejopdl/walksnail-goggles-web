"""Command-line entry point: ``walksnail <command>`` (or ``python -m walksnail_client``)."""

from __future__ import annotations

import argparse
import json
import sys

from . import protocol as p
from .client import WalksnailClient


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_info(c: WalksnailClient, args) -> int:
    info = c.get_version()
    _print_json(info.raw)
    print(f"\nGoggles SW {info.goggles_sw} (HW {info.goggles_hw}, SN {info.goggles_sn})")
    print(f"Air unit linked: {'yes' if info.vtx_present else 'no'}")
    return 0


def cmd_state(c: WalksnailClient, args) -> int:
    state = c.get_device_state()
    _print_json(state)
    print(f"\nvtx_connect={state.get('vtx_connect')}  "
          f"gas_voltage={state.get('gas_voltage'):.2f}V  "
          f"bitrate={state.get('bitrate')}")
    return 0


def cmd_records(c: WalksnailClient, args) -> int:
    res = c.list_records(start=args.start, limit=args.limit)
    rows = res.get("rows", [])
    print(f"total={res.get('total')}  showing {len(rows)}")
    for r in rows:
        print(f"  {r['szFileName']:>20}  {r['duration']:>4}s  {c.record_url(r['szFileName'])}")
    return 0


def cmd_download(c: WalksnailClient, args) -> int:
    dest = args.dest or args.filename
    print(f"downloading {args.filename} -> {dest}")
    c.download_record(args.filename, dest)
    print("done")
    return 0


def cmd_play(c: WalksnailClient, args) -> int:
    from .video import play_url
    target = args.filename if args.file else c.record_url(args.filename)
    print(f"playing {target}  (q/ESC quit, space pause)")
    play_url(target)
    return 0


def cmd_pull_all(c: WalksnailClient, args) -> int:
    import os
    os.makedirs(args.dest, exist_ok=True)
    rows = c.list_records(limit=args.limit)["rows"]
    print(f"downloading {len(rows)} clips -> {args.dest}/")
    for i, r in enumerate(rows, 1):
        name = r["szFileName"]
        out = os.path.join(args.dest, name)
        if os.path.exists(out) and not args.overwrite:
            print(f"  [{i}/{len(rows)}] skip {name} (exists)")
            continue
        print(f"  [{i}/{len(rows)}] {name} ({r['duration']}s)")
        c.download_record(name, out)
    print("done")
    return 0


def _confirm(args, what: str) -> bool:
    if args.yes:
        return True
    print(f"refusing to {what} without --yes (irreversible)", file=sys.stderr)
    return False


def cmd_delete(c: WalksnailClient, args) -> int:
    if not _confirm(args, f"delete {args.filename}"):
        return 2
    c.delete_record(args.filename)
    print(f"deleted {args.filename}")
    return 0


def cmd_settime(c: WalksnailClient, args) -> int:
    c.set_time()
    print("goggles clock synced to local time")
    return 0


def cmd_reboot(c: WalksnailClient, args) -> int:
    if not _confirm(args, "reboot the goggles"):
        return 2
    c.reboot()
    print("reboot sent")
    return 0


def cmd_factory_reset(c: WalksnailClient, args) -> int:
    if not _confirm(args, "factory-reset the goggles"):
        return 2
    c.factory_reset()
    print("factory reset sent")
    return 0


def cmd_format(c: WalksnailClient, args) -> int:
    if not _confirm(args, f"format the {args.target} SD card"):
        return 2
    (c.format_vtx_sd if args.target == "vtx" else c.format_goggles_sd)()
    print(f"format {args.target} SD sent")
    return 0


def cmd_live(c: WalksnailClient, args) -> int:
    url = c.rtsp_url
    if not args.force:
        try:
            probe = WalksnailClient(c.host, timeout=2.0)  # fast precheck
            if not probe.vtx_connected():
                print("warning: vtx_connect=0 (no air unit) — the stream will be "
                      "empty. Power the drone/VTX, or pass --force.", file=sys.stderr)
                return 2
        except Exception as e:  # noqa: BLE001 — best-effort precheck
            print(f"warning: could not read device state ({e}); trying anyway", file=sys.stderr)
    transport = "udp" if args.udp else "tcp"
    print(f"opening {url} [{transport}]  (q/ESC quit, s snapshot)")
    from .video import show_live
    show_live(c.host, transport=transport, osd=args.osd)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="walksnail", description=__doc__)
    ap.add_argument("--host", default=p.DEFAULT_HOST, help="goggles IP (default 192.168.42.1)")
    ap.add_argument("--timeout", type=float, default=5.0)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="device version / serials").set_defaults(fn=cmd_info)
    sub.add_parser("state", help="live telemetry (devicestate)").set_defaults(fn=cmd_state)

    pr = sub.add_parser("records", help="list DVR recordings")
    pr.add_argument("--start", type=int, default=0)
    pr.add_argument("--limit", type=int, default=20)
    pr.set_defaults(fn=cmd_records)

    pd = sub.add_parser("download", help="download a DVR clip")
    pd.add_argument("filename")
    pd.add_argument("dest", nargs="?", default=None)
    pd.set_defaults(fn=cmd_download)

    pp = sub.add_parser("play", help="play a DVR clip (stream from goggles)")
    pp.add_argument("filename")
    pp.add_argument("--file", action="store_true", help="filename is a local path")
    pp.set_defaults(fn=cmd_play)

    pa = sub.add_parser("pull-all", help="download all DVR clips to a folder")
    pa.add_argument("dest", nargs="?", default="dvr")
    pa.add_argument("--limit", type=int, default=100000)
    pa.add_argument("--overwrite", action="store_true")
    pa.set_defaults(fn=cmd_pull_all)

    px = sub.add_parser("delete", help="delete a DVR clip (irreversible)")
    px.add_argument("filename")
    px.add_argument("--yes", action="store_true")
    px.set_defaults(fn=cmd_delete)

    sub.add_parser("settime", help="sync goggles clock to local time").set_defaults(fn=cmd_settime)

    prb = sub.add_parser("reboot", help="reboot the goggles")
    prb.add_argument("--yes", action="store_true")
    prb.set_defaults(fn=cmd_reboot)

    pfr = sub.add_parser("factory-reset", help="factory reset the goggles")
    pfr.add_argument("--yes", action="store_true")
    pfr.set_defaults(fn=cmd_factory_reset)

    pf = sub.add_parser("format", help="format an SD card")
    pf.add_argument("target", choices=["goggles", "vtx"])
    pf.add_argument("--yes", action="store_true")
    pf.set_defaults(fn=cmd_format)

    pl = sub.add_parser("live", help="open the live RTSP feed in a window")
    pl.add_argument("--force", action="store_true", help="skip the vtx_connect precheck")
    pl.add_argument("--udp", action="store_true",
                    help="use RTP/UDP transport (lower latency, may tear on loss)")
    pl.add_argument("--osd", action="store_true",
                    help="overlay telemetry (battery/temp/link/bitrate)")
    pl.set_defaults(fn=cmd_live)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = WalksnailClient(args.host, timeout=args.timeout)
    try:
        return args.fn(client, args)
    except p.GogglesError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"network error talking to {args.host}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
