# WS WiFi Stream — desktop app (Python)

Cross-platform client for the **Walksnail Avatar HD Goggles X**, talking their
LAN protocol over WiFi. Runs on macOS / Linux / Windows — no Android app required.

- **Control plane** (device info, telemetry, DVR listing/download): pure stdlib,
  zero dependencies.
- **Live view** (H.264/RTSP → window): needs the `[video]` extra (PyAV + OpenCV).

## Install

```bash
cd apps/desktop
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # control plane only
pip install -e ".[video]"   # + live view (PyAV/OpenCV)
```

## Use

Join your computer to the goggles Wi-Fi (`Walksnail_XXXX`, pass `12345678`),
then:

```bash
ws info          # goggles + air-unit versions / serials
ws state         # live telemetry (vtx_connect, voltages, temps, bitrate)
ws records --limit 20
ws download AvatarG0531.mp4    # save a clip locally
ws play AvatarG0531.mp4        # stream-play a recording (space=pause)
ws pull-all dvr/               # download all clips into ./dvr
ws delete AvatarG0531.mp4 --yes
ws settime                     # sync goggles clock
ws live --osd                  # live feed + telemetry overlay
ws live --udp                  # RTP/UDP transport (resilient to loss)
# device control (destructive — need --yes):
ws reboot --yes
ws factory-reset --yes
ws format goggles --yes        # or: format vtx --yes
```

In the live window: **q**/**ESC** quit, **s** save a PNG snapshot. In `play`:
**space** pause/resume, **q**/**ESC** quit.

All commands accept `--host` (default `192.168.42.1`) and `--timeout`.

### Library

```python
from ws_client import WSClient
c = WSClient()
print(c.get_version().goggles_sw)     # '39.44.15'
print(c.get_device_state())           # telemetry dict
for r in c.list_records(limit=10)["rows"]:
    print(r["szFileName"], r["duration"])

from ws_client.video import live_frames, LatestFrameReader

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
ws_client/
  protocol.py   wire format: szCmd builders, endpoints, response parsing (pure)
  client.py     WSClient — HTTP control (urllib, zero deps)
  video.py      RTSP live view via PyAV: live_frames, LatestFrameReader,
                show_live (latest-frame + reconnect + optional OSD/snapshot)
  cli.py        `ws` command
examples/       connect.py, live_view.py
tests/          pytest suites (no device needed); manual/ needs real goggles
```

Run the tests (no device needed):
```bash
pip install -e ".[web,dev]" && pytest -q
```

## Status
Verified end-to-end against real goggles (SW 39.44.15) + air unit (AvatarMini):
control plane, DVR listing, and the **live H.264/RTSP feed decoded and rendered
on macOS** with low latency. `live` requires a linked air unit
(`vtx_connect == 1`).

## Notes
The client talks to the goggles over their local WiFi network (default host
`192.168.42.1`).
