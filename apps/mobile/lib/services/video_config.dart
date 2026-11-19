/// Live-video backend (fvp / libmdk) configuration.
///
/// Kept in one place so both app startup and the in-flight TCP/UDP toggle use
/// the same options. Re-calling [configureFvp] at runtime is safe: fvp stores
/// these as *static* options that only the NEXT created player reads, so the
/// existing player is untouched — the caller recreates the player afterwards.
import 'dart:io' show Platform;
import 'package:fvp/fvp.dart' as fvp;

/// RTSP transport for the live feed.
///   • `tcp` — clean image, the default (matches the desktop app).
///   • `udp` — can lower latency on a weak link, at the cost of artifacts.
String rtspTransport = 'tcp';

/// (Re)configure the fvp backend for the current [rtspTransport].
void configureFvp() {
  // Hardware decoder per platform, FFmpeg as the software fallback.
  final hwDecoders = Platform.isIOS || Platform.isMacOS
      ? ['VT', 'FFmpeg']
      : ['MediaCodec', 'FFmpeg'];

  fvp.registerWith(options: {
    // 2 = live-stream mode: drop frames to always show the LATEST content.
    // This is the minimum-latency trade-off an FPV feed wants (1 = VOD, which
    // buffers for smoothness and adds noticeable delay).
    'lowLatency': 2,
    'video.decoders': hwDecoders,
    // Applied AFTER fvp's hardcoded default, so this wins.
    'player': {
      'avformat.rtsp_transport': rtspTransport,
    },
  });
}
