# Walksnail Goggles X — Open-Source Cross-Platform Client

An **open-source client** for the Walksnail Avatar HD **Goggles X** — live view,
telemetry, device control and DVR media management from any computer or browser,
**no Android app required**. Python first; the protocol is plain HTTP/JSON +
standard RTSP, so ports to other platforms are straightforward.

> [!IMPORTANT]
> **Unofficial project. Not affiliated with, authorized, or endorsed by Caddx,
> Walksnail, or any manufacturer.** "Walksnail", "Caddx" and "Avatar" are
> trademarks of their respective owners and are used here only to describe the
> hardware this software interoperates with. This is independent interoperability
> work for hardware the authors own; it ships **no** vendor firmware, app, or
> decompiled code. Use at your own risk.

## What you get
- **Live video** — the goggles' H.264/RTSP feed, decoded with low latency.
- **Telemetry** — battery, temperature, bitrate, MCS, SD space, link state.
- **DVR media** — list, play, download (single/batch) and delete recorded clips.
- **Device control** — set clock, reboot, format SD, factory reset.
- **Two front-ends** — a CLI (`walksnail`) and a browser **Web Ground Station**.

## Hardware
- Goggles: Walksnail Avatar HD **Goggles X** (tested on SW 39.44.15)
- A linked air unit (e.g. Avatar Pro / Mini) for live video
- Goggles Wi-Fi AP: SSID `Walksnail_XXXX`, default pass `12345678`, IP `192.168.42.1`

## How it works
The goggles expose an ordinary LAN protocol — no custom video transport:

- **Live video:** `rtsp://192.168.42.1/live.ch01` — H.264 High@4.0, 1920×1080,
  60 fps, standard RTP/RTSP (also plays in VLC/ffplay).
- **Control:** `POST http://192.168.42.1/ajaxcom`, body `szCmd=<JSON>`
  (`version`, `devicestate`, `onlinequery`, `SysCtrl` actions).
- **DVR:** list via `POST /querydata {"query_record":…}`, download
  `GET /record/<file>.mp4`, delete via `SysCtrl/deletegasrecord`.

Full wire format in [PROTOCOL_SPEC.md](PROTOCOL_SPEC.md); every feature → command
is inventoried in [FEATURE_MAP.md](FEATURE_MAP.md).

## Quick start (CLI)
Join your computer to the goggles Wi-Fi (`Walksnail_XXXX` / `12345678`), then:
```bash
cd poc/python
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[video]"
walksnail info            # versions / serials
walksnail state           # telemetry (battery, temp, vtx_connect, bitrate)
walksnail records         # list DVR clips
walksnail live --osd      # live feed + telemetry overlay (q/ESC quit, s snapshot)
```
See [poc/python/README.md](poc/python/README.md).

## Web Ground Station
A browser-based ground station (FastAPI + single-file SPA): live video, telemetry
and media management from any device on the goggles' Wi-Fi. Full docs:
[poc/python/WEB_README.md](poc/python/WEB_README.md).

```bash
cd poc/python
pip install -e ".[web]"
walksnail-web                                # goggles at 192.168.42.1, UI on :8080
walksnail-web --bind 127.0.0.1 --port 5080   # localhost only
# open http://localhost:8080
```

- **Live view** — MJPEG transcode of the RTSP feed, self-healing, TCP/UDP, quality/FPS/scale controls.
- **Telemetry** — WebSocket push (battery, temp, bitrate sparkline, MCS, SD, distance) with adaptive colour thresholds.
- **Media library** (`Media` button / `m`) — browse, play in-browser, download (single or batch), and delete the goggles' DVR clips. Opening it pauses the live stream so a light device isn't transcoding video and serving files at once.
- **Recording status** — live REC indicators for goggles/air unit. Note: this firmware does **not** expose remote start/stop (see [FEATURE_MAP.md](FEATURE_MAP.md)); recording is toggled on the goggles.
- **Polish** — responsive down to phone widths, hover tooltips on every metric, keyboard shortcuts (`O S F , R M`), hardened settings drawer, and a single-instance lock (the goggles' RTSP is single-session).

> [!NOTE]
> The goggles serve the live RTSP feed to **one client at a time**. Close the
> phone app's live view (and any `ffplay`) before connecting, or video won't appear.

## Tests
```bash
cd poc/python && pip install -e ".[web]"
python -m pytest tests/ -q     # 46 hardware-free unit tests (protocol, REST/WS/MJPEG, SPA)
```

## License
[MIT](LICENSE) — covers the original code in this repository only. It grants no
rights to the Caddx/Walksnail app, firmware, or trademarks. No vendor APK,
firmware, or decompiled code is included or redistributed.
