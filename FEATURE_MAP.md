# Goggles X — Complete Function Map (for client replication)

Every function the CaddxFPV beta exposes for the **Goggles X**, mapped to its
wire command and channel, with PoC status. Derived from the `d9` package (the
Goggles X client). The goggles feature set is small and fully enumerated — the
app is essentially **live view + DVR + basic device control** (channel/image/OSD
tuning is done in the goggles' own menu, not the app).

Legend: ✅ implemented & live-verified · 🟡 implemented, not live-verified ·
🔎 spec'd from code, not yet implemented · ❌ in app code but NOT served by
Goggles X fw 39.44.15 · ch# = channel from PROTOCOL_SPEC.

> Cross-checked against the goggles' **own embedded web UI** (`/index.asp` →
> `pages/config.asp`): its tree is version&upgrade / device control / SD records,
> driving the same `/ajaxcom` commands — confirming the surface below is complete.

## Connect / status
| Function | Wire | ch | PoC |
|---|---|---|---|
| Online check | `POST /ajaxcom {"SysQuery":{"onlinequery":{}}}` → `{online}` | 1 | ✅ `client.online()` / `walksnail` (implicit) |
| Device info / versions | `… {"SysQuery":{"version":{}}}` → Goggles_*/TX_* | 1 | ✅ `get_version()` / `walksnail info` |
| Live telemetry | `… {"SysQuery":{"devicestate":0}}` → gas_*/vtx_* | 1 | ✅ `get_device_state()` / `walksnail state` |
| Push events (record start/stop, link) | TCP `:3333` | 5 | ❌ refused — **poll `devicestate`** (`gas_rec_state`) instead |
| Stream/record mode via CGI | `POST / custom=1&cmd=3037` | 6 | ❌ root → 302 /index.asp (CGI not served) |

## Live video
| Function | Wire | ch | PoC |
|---|---|---|---|
| Live feed (H.264 1080p60) | `rtsp://<host>/live.ch01` | 4 | ✅ `walksnail live` (TCP/UDP, OSD, snapshot) |
| Snapshot from live | client-side frame grab | 4 | ✅ 's' key in `live` |

## DVR (recorded files) — "reading recorded files" phase
| Function | Wire | ch | PoC |
|---|---|---|---|
| List recordings | `POST /querydata {"query_record":{"start","limit"}}` → rows | 2 | ✅ `list_records()` / `walksnail records` |
| Download a clip | `GET /record/<szFileName>` | 3 | ✅ `download_record()` / `walksnail download` |
| Play a clip | `GET /record/<f>` → decode | 3 | 🟡 `walksnail play <f>` (PyAV; same path as live) |
| Delete a clip | `POST /ajaxcom {"SysCtrl":{"deletegasrecord":{"szFileName":"<f>"}}}` | 1 | ✅ `delete_record()` / `walksnail delete` (wire format served, verified) |
| Pull all clips | iterate list + download | 2/3 | 🟡 `walksnail pull-all` |

## Device control
| Function | Wire | ch | PoC |
|---|---|---|---|
| Set clock | `… {"SysCtrl":{"settime":{dwYear,byMonth,byDay,byHour,byMinute,bySecond}}}` | 1 | ✅ `set_time()` / `walksnail settime` (verified, nRetVal 0) |
| Reboot | `… {"SysCtrl":{"reboot":{}}}` | 1 | 🟡 `reboot()` / `walksnail reboot --yes` (not run) |
| Factory reset | `… {"SysCtrl":{"default":{}}}` | 1 | 🟡 `factory_reset()` / `walksnail factory-reset --yes` |
| Format goggles SD | `… {"SysCtrl":{"gassdcardformat":{}}}` | 1 | 🟡 `walksnail format goggles --yes` |
| Format VTX SD | `… {"SysCtrl":{"vtxsdcardformat":{}}}` | 1 | 🟡 `walksnail format vtx --yes` |

## Firmware update
| Function | Wire | ch | PoC |
|---|---|---|---|
| Upload image | `POST /uploadfile?szUpLoadType=ImportUpdate` (multipart, field `filename`, e.g. `AvatarX_Gnd_<ver>.img`) | 3 | 🔎 not implemented (risky; document only) |
| Apply + reboot | `… {"SysCtrl":{"updatereboot":{}}}` | 1 | 🔎 not implemented |

## Channels NOT served by this firmware (do not implement)
- **Event socket TCP :3333** — `connect: refused`. Use `devicestate` polling.
- **CGI `custom=1&cmd=`** (ids `3001/3016/3019/3037/2017`) — `POST /` redirects
  to the web UI. These are Caddx-camera-line infra, dead for the Goggles X.

## Not part of the goggles app (done in goggles menu, not over Wi-Fi)
Channel/frequency, bandwidth/power, image profile, OSD layout, DVR resolution —
these are **not** in the app's wire protocol; they're set on the goggles
hardware. So "replicate all app functions" = the tables above. (The firmware's
generic `SetEnv/VideoParam` helper exists but is not exposed for the goggles.)

## Verification backlog
- ✅ Live RTSP `SETUP`/`PLAY` + RTP/H.264 headers verified against real hardware
  (H.264 1080p60, standard RTP/RTSP — reproducible with `ffprobe`/`ffplay`).
- `reboot` / `factory-reset` / `format` — implemented, `--yes`-guarded; run only
  on explicit request (destructive).
