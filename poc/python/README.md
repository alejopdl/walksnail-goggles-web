# walksnail-client (Python PoC)

Cross-platform client for the **Walksnail Avatar HD Goggles X**, talking the
reverse-engineered LAN protocol (see [`../../PROTOCOL_SPEC.md`](../../PROTOCOL_SPEC.md)).
Runs on macOS / Linux / Windows — no Android app required.

- **Control plane** (device info, telemetry, DVR listing/download): pure stdlib,
  zero dependencies.
- **Live view** (H.264/RTSP → window): needs the `[video]` extra (PyAV + OpenCV).

## Install

```bash
cd poc/python
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # control plane only
pip install -e ".[video]"   # + live view (PyAV/OpenCV)
```

## Use

Join your computer to the goggles Wi-Fi (`Walksnail_XXXX`, pass `12345678`),
then:

```bash
walksnail info          # goggles + air-unit versions / serials
walksnail state         # live telemetry (vtx_connect, voltages, temps, bitrate)
walksnail records --limit 20
walksnail download AvatarG0531.mp4    # save a clip locally
walksnail play AvatarG0531.mp4        # stream-play a recording (space=pause)
walksnail pull-all dvr/               # download all clips into ./dvr
walksnail delete AvatarG0531.mp4 --yes
walksnail settime                     # sync goggles clock
walksnail live --osd                  # live feed + telemetry overlay
walksnail live --udp                  # RTP/UDP transport (resilient to loss)
# device control (destructive — need --yes):
walksnail reboot --yes
walksnail factory-reset --yes
walksnail format goggles --yes        # or: format vtx --yes
```

In the live window: **q**/**ESC** quit, **s** save a PNG snapshot. In `play`:
**space** pause/resume, **q**/**ESC** quit.

All commands accept `--host` (default `192.168.42.1`) and `--timeout`.

### Library

```python
from walksnail_client import WalksnailClient
c = WalksnailClient()
print(c.get_version().goggles_sw)     # '39.44.15'
print(c.get_device_state())           # telemetry dict
for r in c.list_records(limit=10)["rows"]:
    print(r["szFileName"], r["duration"])

from walksnail_client.video import live_frames, LatestFrameReader

# (a) simple sequential generator — good for recording/processing
for frame in live_frames():               # numpy BGR frames
    ...                                   # feed to OpenCV / OBS / your UI

# (b) low-latency: background decoder that keeps only the newest frame
reader = LatestFrameReader(transport="tcp").start()  # or transport="udp"
while True:
    frame = reader.read()                 # newest frame or None; self-healing
    if frame is not None:
        ...
```

## Layout
```
walksnail_client/
  protocol.py   wire format: szCmd builders, endpoints, response parsing (pure)
  client.py     WalksnailClient — HTTP control (urllib, zero deps)
  video.py      RTSP live view via PyAV: live_frames, LatestFrameReader,
                show_live (latest-frame + reconnect + optional OSD/snapshot)
  cli.py        `walksnail` command
examples/       connect.py, live_view.py
tests/          test_protocol.py  (pytest; no device needed)
```

Run the tests (no device needed):
```bash
pip install pytest && pytest -q
```

## Status
Verified end-to-end against real goggles (SW 39.44.15) + air unit (AvatarMini):
control plane, DVR listing, and the **live H.264/RTSP feed decoded and rendered
on macOS** with low latency. `live` requires a linked air unit
(`vtx_connect == 1`).

## Notes
This is interoperability research on owned hardware. No decompiled code is used
here — only the observed wire protocol.
