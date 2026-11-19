# WS WiFi Stream — mobile app

**WS WiFi Stream** is a modern, low-latency mobile app, built with Flutter, that works with Walksnail Avatar FPV goggles.

**Platforms:** Android ✅ · iOS 🚧 *(builds and runs; not released yet — live video and DVR downloads require a physical iPhone on the goggles WiFi)*

## Features

- **Ultra-Low Latency RTSP Stream:** Uses `fvp` (mdksdk) to render the RTSP stream natively with hardware acceleration, achieving minimal latency similar to the official app.
- **Auto-Connect Watchdog:** A background loop continuously polls the goggles' telemetry (`/ajaxcom`, every 500 ms). The video stream automatically starts when the VTX connects and stops when it disconnects.
- **Smart OSD Overlay:** Telemetry data (voltage, bitrate, signal, REC status) rendered as a clean Flutter overlay. Supports "Always On" and "Auto-Hide" modes.
- **DVR Gallery:**
  - Fast, lazy-loaded list of DVR recordings from the goggles' SD card.
  - Multi-select mode for batch downloading.
  - Downloads with progress bars: on both **Android** and **iOS**, clips are saved to the phone's gallery / **Photos** library in the album "WS WiFi Stream" via `gal`.
  - Cancel downloads mid-flight.
  - Sort by name, duration, and file size.
- **Platform Integration:** Screen rotation control and immersive fullscreen. Hardware video decode is platform-aware — MediaCodec on Android, VideoToolbox on iOS.

## Architecture

- **State Management:** Uses `Provider` for reactive UI updates (`GogglesState`).
- **Networking:** Custom HTTP polling loop for real-time telemetry extraction (`WSApi`).
- **Video Player:** `fvp` is used to decode the raw `rtsp://192.168.42.1/live.ch01` stream directly, skipping high-level flutter players that buffer heavily.

## Development Setup

### Prerequisites
- Flutter 3.44+ (Dart ≥ 3.12.2)
- **Android:** Android SDK & NDK, OpenJDK 17
- **iOS:** Xcode (full install, not just Command Line Tools) + an iOS Simulator runtime. Minimum deployment target is **iOS 14**. Uses Swift Package Manager — no CocoaPods/Podfile needed.

### Build Instructions

Run these commands from `apps/mobile`.

1. **Get dependencies:**
   ```bash
   flutter pub get
   ```

2. **Run in debug mode (USB / device):**
   ```bash
   flutter run
   ```

3. **Build Release APK (Android):**
   ```bash
   flutter build apk --release
   ```
   *The output will be in `build/app/outputs/flutter-apk/app-release.apk`*

4. **Build for iOS Simulator:**
   ```bash
   flutter build ios --debug --simulator
   ```
   *For a real device use `flutter build ipa` (set your bundle ID and signing team in Xcode first — the default `com.example.wswifistream` is a placeholder).*

## Known Limitations

- **Thumbnails:** Generating thumbnails from the goggles' HTTP server over WiFi is slow and blocks the connection. Thumbnails are intentionally replaced by stylized placeholders with the clip number to ensure fast gallery loading.

## Author
alejopdl
