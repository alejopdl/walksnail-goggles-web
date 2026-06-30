# Walksnail Goggles X Protocol Specification (Reverse Engineered)

Status: **fully verified live** against real hardware (goggles SW 39.44.15,
SN AvatarX_079060; air unit AvatarMini, SW 39.44.15). Control plane exercised
end-to-end; live H.264/RTSP feed decoded and rendered on macOS via the Python
PoC. Recorded (DVR) and live video both confirmed H.264 1080p60.

All communication is over the goggles' own Wi-Fi AP. No TLS, no auth observed.
Documented by observing the goggles' own network traffic, for interoperability.

| Item | Value |
|---|---|
| Goggles AP | SSID `Walksnail_XXXX`, pass `12345678` |
| Goggles IP | `192.168.42.1` (client gets `192.168.42.x` via DHCP) |
| HTTP | port 80 |
| RTSP | port 554 |

## Transmission architecture (how the goggles talk)

The app (`d9` package = Goggles X client) contains code for six channels, but
only **four are actually served** by Goggles X firmware 39.44.15. Legend:
✅ verified live · ❌ confirmed NOT served by this firmware.

| # | Channel | Transport / port | Purpose | Status |
|---|---------|------------------|---------|--------|
| 1 | JSON control | HTTP POST `/ajaxcom` | system query/control (`SysQuery`/`SysCtrl`) | ✅ |
| 2 | Records query | HTTP POST `/querydata` | DVR listing (`query_record`) | ✅ |
| 3 | File transfer | HTTP GET `/record/<f>`, POST `/uploadfile` | DVR download, firmware upload | ✅ download |
| 4 | Live video | RTSP/RTP, TCP/UDP **554** | H.264 live feed `live.ch01` | ✅ |
| 5 | Event push | raw TCP socket **3333** | async status events | ❌ `connect: refused` |
| 6 | CGI control | HTTP POST `/` body `custom=1&cmd=<id>` | numeric HiSilicon cmds | ❌ root `302 → /index.asp` |

Channels 5–6 exist in the client only as **shared infra for the Caddx camera
line**; the Goggles X firmware does not serve them (empirically: port 3333
refuses connections, and `POST /` redirects to the embedded web UI instead of
processing `custom=1&cmd`). **The complete Goggles X surface is channels 1–4.**
This is corroborated by the goggles' own embedded web UI (see below), which
drives the exact same commands over `/ajaxcom`.

### Embedded web UI (`http://192.168.42.1/index.asp`)
The goggles run a small HiSilicon web server. `index.asp` → `pages/config.asp`
with a 3-node tree: **version & upgrade · device control · SD record list** —
i.e. the same feature set as the app. Its `control.asp` buttons map 1:1 to our
commands (`rebootdev`→reboot, `updatereboot`, `defaultdev`→default,
`setdevtime`→settime, `formatgassd`→gassdcardformat, `formatvtxsd`→vtxsdcardformat),
and `common.js` posts `szCmd` to `/ajaxcom`. A generic helper `setVParam` builds
`{"SetEnv":{"VideoParam":[{…,"nChannel":0}]}}`, but no video-param page is exposed
for the goggles (generic HiSilicon infra, not a Goggles X function).

### Captured live session (verified, drone linked)
```
C→S OPTIONS  → 200; Public: OPTIONS,DESCRIBE,SETUP,TEARDOWN,PLAY,PAUSE,GET_PARAMETER,SET_PARAMETER
C→S DESCRIBE → 200 application/sdp:
      m=video 0 RTP/AVP 96 · a=rtpmap:96 H264/90000 · a=control:track0
      a=fmtp:96 packetization-mode=1;profile-level-id=644028;sprop-parameter-sets=<SPS>,<PPS>
C→S SETUP rtsp://<host>/live.ch01/track0  Transport: RTP/AVP/TCP;unicast;interleaved=0-1
      → 200; Session: 696310B8; Transport: RTP/AVP/TCP;unicast;interleaved=0-1
C→S PLAY  Session: 696310B8; Range: npt=0.000-  → 200
S→C  $-framed interleaved RTP on channel 0:
      RTP v2 pt=96 ssrc=0x6a7e054c ts=332254764 (90kHz)
      seq+0 NAL 7 (SPS) · seq+1 NAL 8 (PPS) · seq+2.. FU-A of NAL 5 (IDR), start=1 then continuations
```
Note: SPS/PPS are sent **in-band** before each IDR (not only in the SDP), so a
decoder can join mid-stream. All packets of one frame share a timestamp; the RTP
**marker bit** ends the access unit. This trace was captured over an adb TCP
tunnel to port 554 (RTSP-over-TCP keeps one connection, so it tunnels cleanly).

### Live video transport (RTSP → RTP → H.264) — the core of the feed

1. **RTSP session** (TCP 554, plain RTSP/1.0, no auth):
   - `OPTIONS` → server advertises `OPTIONS, DESCRIBE, SETUP, TEARDOWN, PLAY,
     PAUSE, GET_PARAMETER, SET_PARAMETER`.
   - `DESCRIBE` → SDP (only non-empty when `vtx_connect == 1`). One media line:
     `m=video 0 RTP/AVP 96`, `a=rtpmap:96 H264/90000`, `a=control:track0`
     (relative control → tunnelable), `a=fmtp:96 packetization-mode=1;
     profile-level-id=644028; sprop-parameter-sets=<SPS>,<PPS>`.
   - `SETUP track0` → client picks transport: **RTP/AVP/TCP (interleaved)** for
     reliability, or **RTP/AVP/UDP** (server returns `server_port`) for lower
     latency. Server returns a `Session` id.
   - `PLAY` → RTP media starts flowing; periodic RTSP keepalive via
     `GET_PARAMETER`/`OPTIONS`.
2. **RTP framing** (payload type 96, 90 kHz clock): standard RFC 3550 header
   (V=2, sequence number for reorder/loss detection, timestamp = capture time at
   90 kHz, SSRC). The **marker bit** flags the last packet of an access unit
   (frame). On UDP, packets can be lost/reordered → the consumer must reorder by
   sequence and tolerate gaps; on TCP-interleaved they arrive in order on the
   RTSP socket framed by a `$ <channel> <len16>` prefix.
3. **H.264 payload** (RFC 6184): NAL units, fragmented across RTP packets with
   **FU-A** when larger than the MTU; SPS/PPS come from the SDP
   `sprop-parameter-sets` (and may also be in-band). Decoded parameters:
   **High Profile, Level 4.0, 1920×1080, 60 fps** (SPS verified). One IDR
   keyframe per GOP starts a decodable sequence — a late joiner shows nothing
   until the next keyframe.
4. **In the Android app**: the URL `rtsp://192.168.42.1/live.ch01` is handed to
   `IjkMediaPlayer` (FFmpeg-based) via `m.rxt.player.PlayerView`, rendered to a
   `SurfaceView`. Our PoC replaces this with PyAV/FFmpeg → identical pipeline.
5. **Latency**: dominated by encoder GOP + Wi-Fi jitter buffering. Minimise on
   the client with `nobuffer`/`low_delay`/`max_delay=0`/`reorder_queue_size=0`
   and a drop-to-latest render (see PHASE3). UDP shaves a bit more at the cost of
   tearing on loss.

### Event channel (TCP 3333) ❌ not served here

Client class `com.hao.acase.socket.CameraEventMessage` (`b7.alpha`) would open a
raw TCP socket to `192.168.42.1:3333`, read event strings framed as
`<Cmd>NNNN</Cmd><Status>NN</Status>`, and dispatch `(cmd,status)` (handlers seen:
`cmd 3020` recording state, `status 11`=started/`12`=stopped; `cmd 2020`).
**Empirically the goggles refuse connections on 3333** — this firmware does not
provide the push channel. A client must **poll `devicestate`** instead (e.g.
`gas_rec_state`/`vtx_rec_state`) for the same information.

### CGI control channel (`custom=1&cmd=<id>`) ❌ not served here

The client also has a CGI form (`POST /` body `custom=1&cmd=<id>[&par=][&str=]`,
ids `3001/3016/3019/3037/2017`). **Empirically `POST /` returns `302 → /index.asp`**
— the goggles serve a web page at root, not this CGI. It is Caddx-camera-line
infra unused by the Goggles X. All real control goes through `/ajaxcom` (ch 1).

## Connection lifecycle
1. Join goggles Wi-Fi (`192.168.42.1` reachable).
2. (optional) `onlinequery` to confirm the device is up.
3. `version` / `devicestate` for device info + telemetry.
4. Live view: RTSP `PLAY rtsp://192.168.42.1/live.ch01` (needs VTX linked).
5. DVR: `query_record` to list, `GET /record/<file>` to download.

## Command plane — HTTP

Two endpoints. Body is form-encoded `szCmd=<JSON>` (Content-Type
`application/x-www-form-urlencoded`); header `Connection: close`. Response is
JSON `{"nRetVal":<0=ok, !=0 error>, ...}`.

### A) `POST /ajaxcom` — system query & control (`SysQuery` / `SysCtrl`)

| Command (`szCmd`) | Response `stValue` |
|---|---|
| `{"SysQuery":{"version":{}}}` | `Goggles_HW_Version, Goggles_SN, Goggles_SW_Version, TX_SN, TX_HW_Version, TX_SW_Version` |
| `{"SysQuery":{"devicestate":0}}` | telemetry (see below) |
| `{"SysQuery":{"onlinequery":{}}}` | `{"online":1}` |
| `{"SysCtrl":{"settime":{"dwYear":Y,"byMonth":M,"byDay":D,"byHour":h,"byMinute":m,"bySecond":s}}}` | set goggles clock |
| `{"SysCtrl":{"reboot":{}}}` | reboot goggles |
| `{"SysCtrl":{"default":{}}}` | factory reset |
| `{"SysCtrl":{"vtxsdcardformat":{}}}` | format VTX SD |
| `{"SysCtrl":{"gassdcardformat":{}}}` | format goggles SD |

#### Example responses (captured)

`version` (air unit linked):
```json
{"nRetVal":0,"stValue":{
  "Goggles_HW_Version":"4.0","Goggles_SN":"AvatarX_079060",
  "Goggles_SW_Version":"39.44.15",
  "TX_SN":"AvatarMini_0965B4","TX_HW_Version":"3.3","TX_SW_Version":"39.44.15"}}
```
With no air unit, the `TX_*` fields are placeholders (`"--------"`, `"-.-"`,
`"-.-.-"`).

`devicestate` (air unit linked):
```json
{"nRetVal":0,"stValue":{
  "gas_type":3,"vtx_connect":1,"sky_prj_name":0,"gas_rec_state":0,
  "gas_voltage":22.92,"delaytime":36137,"gas_sd_space":521,"sharemode":0,
  "u8_mcs":4,"distance":0,"bitrate":24206560,"vtx_rec_state":0,
  "vtx_voltage":4.16,"vtx_sd_space":5,"vtx_tempeture":41,"gas_tempeture":49}}
```

#### `devicestate.stValue` field reference
(`gas_*` = goggles/ground side, `vtx_*` = air unit)

| Field | Meaning (observed) |
|---|---|
| `gas_type` | goggles model id (3 = Goggles X) |
| `vtx_connect` | **1 = air unit linked** (live video available), 0 = not |
| `sky_prj_name` | air-unit project/profile id |
| `gas_rec_state` / `vtx_rec_state` | recording on goggles SD / VTX SD (0/1) |
| `gas_voltage` / `vtx_voltage` | battery volts (goggles pack / VTX, float) |
| `gas_sd_space` / `vtx_sd_space` | free SD space (units ~ unconfirmed) |
| `gas_tempeture` / `vtx_tempeture` | temperature °C (note misspelling) |
| `bitrate` | live video bitrate, bits/s (0 when no link) |
| `u8_mcs` | radio MCS index |
| `distance` | link distance estimate |
| `delaytime` | uptime/latency counter (ms) |
| `sharemode` | sharing mode flag |

### B) `POST /querydata` — DVR records

| Command (`szCmd`) | Response |
|---|---|
| `{"query_record":{"start":0,"limit":N}}` | `{"nRetVal":0,"total":T,"rows":[{"szFileName","duration"},...]}` |
| `{"deletegasrecord":...}` | delete record(s) |

DVR file download: `GET http://192.168.42.1/record/<szFileName>` (plain HTTP,
ranges supported). Files are `AvatarG####.mp4`.

### Firmware
`POST http://192.168.42.1/uploadfile?szUpLoadType=ImportUpdate` — multipart,
field `filename` (e.g. `AvatarX_Gnd_<ver>.img`); followed by `updatereboot`.

## Video plane — RTSP (live SDP VERIFIED with VTX linked)

- URL: `rtsp://192.168.42.1/live.ch01`, port 554.
- Server methods: `OPTIONS, DESCRIBE, SETUP, TEARDOWN, PLAY, PAUSE,
  GET_PARAMETER, SET_PARAMETER`.
- A media stream/SDP exists only when a VTX/air unit is linked
  (`vtx_connect:1`); otherwise DESCRIBE returns empty.
- Live stream (DESCRIBE → SDP, confirmed):
  - `m=video 0 RTP/AVP 96`, `a=rtpmap:96 H264/90000`, `a=control:track0`
  - `a=fmtp:96 packetization-mode=1; profile-level-id=644028;
    sprop-parameter-sets=Z2RAKKxNQPAET8s3BgYGQAAAAwBAAAAeIQM=,aO44sA==`
  - Decoded SPS → **H.264 High Profile, Level 4.0, 1920×1080, 60 fps**
    (matches DVR recordings exactly). RTP timestamp clock 90 kHz.
- Standard RTP/RTSP — consumable by `ffplay rtsp://192.168.42.1/live.ch01`,
  ffmpeg, PyAV, VLC, GStreamer with no proprietary handling. **Confirmed
  decoded/rendered live on macOS** via the Python PoC (`walksnail live`).
- DVR recordings (e.g. `AvatarG####.mp4`): H.264 1080p60, yuvj420p,
  ~17.8 Mbps, MP4 container.

### Low-latency consumption notes
Default FFmpeg buffering adds latency that *grows* over time; use de-buffering
flags and always render the newest frame (drop stale). Reference command:
```
ffplay -fflags nobuffer -flags low_delay -rtsp_transport tcp -framedrop \
       rtsp://192.168.42.1/live.ch01
```
TCP is reliable; UDP (`-rtsp_transport udp`) can be lower latency but loses
packets → corrupt frames, so a consumer must tolerate/skip them. The PoC's
`walksnail live` implements both (latest-frame thread, resilient UDP).

## Error handling
- `nRetVal: 0` = success. Non-zero = error; `-100` observed when a command is
  sent to the wrong endpoint (e.g. `SysQuery` to `/querydata`).
- `szError` carries an optional message string.

## Quirks / notes
- Two endpoints with the same `szCmd=` body convention is easy to get wrong —
  `SysQuery`/`SysCtrl` ⇒ `/ajaxcom`; record ops ⇒ `/querydata`.
- No authentication or TLS on any goggles endpoint.
- `vtx_connect` gates whether live video is available.
