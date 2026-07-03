# Changelog

All notable changes to WS WiFi Stream are documented here.

## 1.0.2

### Fixed / Improved
- **Safer transport settle delay (3 s).** The settle window between tearing down the
  old RTSP session and opening a new one has been increased from 1.5 s to **3 s** on
  both desktop and Android. The shorter window proved insufficient in real-world
  conditions, causing the first TCP→UDP switch to hang until the app was restarted.
- **Countdown UI when switching transport.** Instead of silently freezing for 3 s,
  the app now shows an hourglass overlay with a visible **3 → 2 → 1** countdown and
  the message *"Closing old session…"* — so you know the wait is intentional and how
  long it will take. (Desktop + Android.)

### Removed
- **Resolution setting removed from desktop.** The resolution control only downscaled
  the preview image in your browser; it did not change what the goggles capture or
  record. Removing it avoids confusion — the goggles' own menu is the only place that
  controls capture resolution.

## 1.0.1


Connection-stability release. Fixes the goggles appearing to connect/disconnect
repeatedly (status and telemetry flickering online↔offline) while the video kept
playing — reported most on Windows.

### Fixed
- **Status/telemetry flapping online↔offline.** The control plane opened a fresh
  TCP connection for every telemetry poll (twice a second). On the goggles' tiny
  embedded HTTP server that connection churn made polls fail in bursts —
  especially on Windows, where closed sockets linger. The app now uses **one
  persistent (keep-alive) connection** and reuses it across polls, transparently
  reconnecting if the socket goes stale. *(Desktop + Android.)*
- **UI no longer flaps on a single dropped poll.** Added hysteresis: a brief
  telemetry blip shows a soft "Reconnecting…" and keeps the last data on screen;
  it only reads "Offline" after a few seconds of real silence — and never while
  the live video is flowing (if there are frames, the goggles are reachable).
  *(Desktop + Android.)*
- **Windows: a second copy is now refused.** The single-instance guard (which
  stops two ground stations from wedging the single-session RTSP feed) previously
  did nothing on Windows; it now takes a real lock there too.
- **The LIVE badge no longer sticks.** It now reflects whether real frames are
  decoding — a VTX link with no video reads "Connecting", and a feed that dies
  drops out of LIVE — instead of showing a stale LIVE over a frozen frame.

### Android
- **Lower latency.** The live player now runs in true live-stream mode (drops
  stale frames to always show the latest) instead of the buffered VOD mode.
- **TCP/UDP toggle.** Switch the RTSP transport on the fly from the video screen
  (TCP = clean default, UDP = lower latency on a weak link).
- **Auto-recovery after losing the feed.** If another device grabs the single
  RTSP session and the video freezes, the app now detects the stall, shows a
  clear "reboot the goggles" hint, and keeps retrying — so it reconnects on its
  own once the session is free again (no more frozen-on-last-frame).

### Notes
- Live video is single-session on the goggles: don't run two apps streaming the
  same goggles at once — it can even crash the goggles (see the README's
  *One device at a time*).

## 1.0.0

- First public release under the **WS WiFi Stream** name.
- Live video (TCP/UDP), battery & signal telemetry, and a DVR recordings manager.
- macOS (Apple Silicon) and Windows desktop builds, Android APK.
- Debug mode (`--debug`) for capturing a session log when reporting issues.
