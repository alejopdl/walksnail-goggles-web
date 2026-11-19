/// Main flight dashboard screen.
///
/// Combines:
///   - Full-screen RTSP video player (fvp)
///   - Translucent OSD overlay (auto-hide / always-on)
///   - Watchdog: auto-starts video when VTX connects, destroys when it disconnects
///   - Gallery button to navigate to the DVR screen
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:video_player/video_player.dart';
import '../providers/goggles_state.dart';
import '../services/video_config.dart';
import '../widgets/osd_overlay.dart';
import 'gallery_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  VideoPlayerController? _controller;
  bool _videoReady = false;
  bool _wasVtxConnected = false;
  OsdMode _osdMode = OsdMode.autoHide;
  bool _isLandscape = true;

  // ── Stall detection & auto-recovery ──────────────────────────────────────
  // The goggles serve a SINGLE RTSP session. If another device (e.g. the PC app)
  // grabs it, our player just freezes on its last frame — no error is raised and
  // VTX stays "connected", so the watchdog never fires. We watch the playback
  // position: if it stops advancing while VTX is up, we tear the player down and
  // reconnect. If it stays stuck after a few tries we flag it "wedged" (tell the
  // user to reboot the goggles) but KEEP retrying slowly, so it recovers on its
  // own once the other device releases the session.
  static const _stallTimeout = Duration(seconds: 6);      // no new frames = stalled
  static const _wedgedRetryEvery = Duration(seconds: 8);  // slow retry once wedged
  static const _maxRestarts = 3;                          // then declare wedged
  Timer? _monitorTimer;
  String? _currentUrl;
  bool _starting = false;
  bool _wedged = false;
  int _restartAttempts = 0;
  Duration _lastPos = Duration.zero;
  DateTime _lastProgressTs = DateTime.now();
  DateTime _lastRestartTs = DateTime.fromMillisecondsSinceEpoch(0);

  // ── Transport settle state ────────────────────────────────────────────────
  // When switching TCP↔UDP we must wait for the goggles to release the single
  // RTSP session before opening a new one.  During those 3 seconds we show a
  // countdown overlay so the user knows the app is intentionally pausing.
  static const _rtspSettle = Duration(seconds: 3);
  bool _isSettling = false;
  int _settleCountdown = 3;
  Timer? _settleTimer;

  // The live feed is released while the DVR gallery is open, so downloads get
  // the goggles to themselves and the stall monitor doesn't restart it unseen.
  bool _inGallery = false;

  @override
  void initState() {
    super.initState();
    // Start in landscape.
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    // Watch the live feed for stalls (see the fields above) every 2s.
    _monitorTimer = Timer.periodic(
        const Duration(seconds: 2), (_) => _monitorVideo());
  }

  @override
  void dispose() {
    _monitorTimer?.cancel();
    _settleTimer?.cancel();
    _controller?.dispose(); // not _destroyPlayer(): no setState during dispose
    SystemChrome.setPreferredOrientations(DeviceOrientation.values);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    super.dispose();
  }

  // --------------- Watchdog (auto-start/stop video) ---------------

  void _onGogglesUpdate(GogglesState goggles) {
    final vtxNow = goggles.isVtxConnected;

    if (vtxNow && !_wasVtxConnected) {
      // VTX just connected → start video (fresh recovery state).
      _restartAttempts = 0;
      _wedged = false;
      _startPlayer(goggles.api.rtspUrl);
    } else if (!vtxNow && _wasVtxConnected) {
      // VTX just disconnected → tear down video and reset recovery state.
      _destroyPlayer();
      _currentUrl = null;
      _restartAttempts = 0;
      _wedged = false;
    }

    _wasVtxConnected = vtxNow;
  }

  Future<void> _startPlayer(String url) async {
    if (_starting || _inGallery) return;  // don't overlap init attempts (monitor ticks fast)
    _starting = true;
    _currentUrl = url;
    _lastPos = Duration.zero;
    _lastProgressTs = DateTime.now();
    _destroyPlayer();

    final controller = VideoPlayerController.networkUrl(Uri.parse(url));
    try {
      await controller.initialize();
      await controller.play();
      if (!mounted || _inGallery) {
        controller.dispose();
        return;
      }
      controller.addListener(_onPlayerValue);
      setState(() {
        _controller = controller;
        _videoReady = true;
      });
    } catch (e) {
      debugPrint('RTSP player error: $e');
      controller.dispose();  // clean up the failed controller; monitor will retry
    } finally {
      _starting = false;
    }
  }

  void _destroyPlayer() {
    _controller?.removeListener(_onPlayerValue);
    _controller?.dispose();
    _controller = null;
    if (mounted) {
      setState(() => _videoReady = false);
    }
  }

  /// Fires on every player value change — treat an advancing position as proof
  /// that real frames are flowing, and clear any stall/wedged state.
  void _onPlayerValue() {
    final c = _controller;
    if (c == null) return;
    if (c.value.position > _lastPos) {
      _lastPos = c.value.position;
      _lastProgressTs = DateTime.now();
      if (_wedged || _restartAttempts != 0) {
        if (mounted) {
          setState(() {
            _wedged = false;
            _restartAttempts = 0;
          });
        }
      }
    }
  }

  /// Periodic health check: if VTX is up but the feed isn't progressing, rebuild
  /// the player. Rate-limited, and backs off (but never gives up) once wedged.
  void _monitorVideo() {
    if (!mounted || !_wasVtxConnected || _starting) return;
    final c = _controller;
    final stalled = c == null ||
        !_videoReady ||
        c.value.hasError ||
        DateTime.now().difference(_lastProgressTs) >= _stallTimeout;
    if (!stalled) return;

    final backoff = _wedged ? _wedgedRetryEvery : _stallTimeout;
    if (DateTime.now().difference(_lastRestartTs) < backoff) return;

    _lastRestartTs = DateTime.now();
    _restartAttempts++;
    if (_restartAttempts >= _maxRestarts && !_wedged && mounted) {
      setState(() => _wedged = true);
    }
    if (_currentUrl != null) _startPlayer(_currentUrl!);
  }

  void _toggleOsdMode() {
    setState(() {
      _osdMode =
          _osdMode == OsdMode.autoHide ? OsdMode.alwaysOn : OsdMode.autoHide;
    });
  }

  /// Switch the RTSP transport (TCP ↔ UDP) and rebuild the player with it.
  /// Shows a 3-second countdown while the goggles release the old RTSP session.
  void _toggleTransport() async {
    if (_isSettling) return; // ignore taps during countdown
    setState(() {
      rtspTransport = rtspTransport == 'tcp' ? 'udp' : 'tcp';
      _isSettling = true;
      _settleCountdown = 3;
    });
    configureFvp(); // updates fvp's options for the next player
    _restartAttempts = 0;
    _wedged = false;

    final url = _currentUrl;
    if (url != null) {
      _destroyPlayer();
      _starting = true; // prevent watchdog from interfering during delay

      // Tick the countdown every second so the user sees 3 → 2 → 1.
      _settleTimer = Timer.periodic(const Duration(seconds: 1), (t) {
        if (!mounted) { t.cancel(); return; }
        setState(() => _settleCountdown--);
        if (_settleCountdown <= 0) t.cancel();
      });

      // After 3 s the goggles have had time to free the RTSP session.
      await Future.delayed(_rtspSettle);
      _settleTimer?.cancel();

      _starting = false;
      if (mounted) {
        setState(() => _isSettling = false);
        if (_currentUrl == url) _startPlayer(url);
      }
    } else {
      // No active URL — just clear the settling flag.
      setState(() => _isSettling = false);
    }
  }

  Future<void> _openGallery() async {
    _inGallery = true;
    _destroyPlayer();
    final settled = Future<void>.delayed(_rtspSettle);
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const GalleryScreen()),
    );
    await settled;
    _inGallery = false;
    if (!mounted || !_wasVtxConnected) return;
    _restartAttempts = 0;
    _wedged = false;
    _startPlayer(context.read<GogglesState>().api.rtspUrl);
  }

  // --------------- build ---------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Consumer<GogglesState>(
        builder: (context, goggles, _) {
          // Run the watchdog check on every state update.
          WidgetsBinding.instance.addPostFrameCallback((_) {
            _onGogglesUpdate(goggles);
          });

          return Stack(
            fit: StackFit.expand,
            children: [
              // Layer 1: Video feed (or waiting indicator).
              _buildVideoLayer(goggles),

              // Layer 2: OSD telemetry overlay.
              OsdOverlay(mode: _osdMode),

              // Layer 3: Persistent controls (Gallery button + OSD toggle).
              _buildControls(),
            ],
          );
        },
      ),
    );
  }

  Widget _buildVideoLayer(GogglesState goggles) {
    // Show the live feed only when it's actually playing and not stuck.
    if (_videoReady && _controller != null && !_wedged && !_isSettling) {
      return Center(
        child: AspectRatio(
          aspectRatio: _controller!.value.aspectRatio,
          child: VideoPlayer(_controller!),
        ),
      );
    }

    // Settling — transport switch in progress, countdown overlay.
    if (_isSettling) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.timer_outlined, color: Colors.amber, size: 56),
            const SizedBox(height: 16),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 32),
              child: Text(
                'Waiting for old session to close…',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white54,
                  fontSize: 16,
                  fontWeight: FontWeight.w300,
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '$_settleCountdown',
              style: const TextStyle(
                color: Colors.amber,
                fontSize: 48,
                fontWeight: FontWeight.w700,
                fontFeatures: [FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
      );
    }

    // Otherwise show the most informative status.
    final IconData icon;
    final String message;
    final bool spinner;
    final Color iconColor;
    if (_wedged) {
      icon = Icons.warning_amber_rounded;
      message = 'Video stuck. Reboot the goggles to recover.\n'
          '(Another app may be holding the feed — the goggles allow only one.)';
      spinner = true; // keep trying in the background
      iconColor = Colors.amber;
    } else if (!goggles.gogglesReachable) {
      icon = Icons.wifi_off;
      message = 'Connect to Goggles WiFi...';
      spinner = false;
      iconColor = Colors.white24;
    } else if (!_wasVtxConnected) {
      icon = Icons.link;
      message = 'Goggles connected. Waiting for VTX link...';
      spinner = true;
      iconColor = Colors.white24;
    } else {
      icon = Icons.autorenew;
      message = 'Reconnecting video...';
      spinner = true;
      iconColor = Colors.white24;
    }

    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: iconColor, size: 64),
          const SizedBox(height: 16),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.white38,
                fontSize: 16,
                fontWeight: FontWeight.w300,
              ),
            ),
          ),
          if (spinner)
            const Padding(
              padding: EdgeInsets.only(top: 16),
              child: SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.cyanAccent,
                ),
              ),
            ),
        ],
      ),
    );
  }

  void _toggleOrientation() {
    setState(() => _isLandscape = !_isLandscape);
    if (_isLandscape) {
      SystemChrome.setPreferredOrientations([
        DeviceOrientation.landscapeLeft,
        DeviceOrientation.landscapeRight,
      ]);
    } else {
      SystemChrome.setPreferredOrientations([
        DeviceOrientation.portraitUp,
        DeviceOrientation.portraitDown,
      ]);
    }
  }

  Widget _buildControls() {
    return Positioned(
      top: 8,
      right: 8,
      child: SafeArea(
        child: Row(
          children: [
            // Transport toggle (TCP ↔ UDP).
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: TextButton(
                onPressed: _toggleTransport,
                style: TextButton.styleFrom(
                  minimumSize: const Size(0, 36),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  foregroundColor: Colors.white70,
                  backgroundColor: Colors.white.withValues(alpha: 0.08),
                ),
                child: Text(
                  rtspTransport.toUpperCase(),
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
            ),
            // Rotate screen button.
            IconButton(
              icon: Icon(
                _isLandscape ? Icons.screen_lock_portrait : Icons.screen_lock_landscape,
                color: Colors.white54,
                size: 22,
              ),
              onPressed: _toggleOrientation,
              tooltip: 'Rotate Screen',
            ),
            // OSD toggle button.
            IconButton(
              icon: Icon(
                _osdMode == OsdMode.alwaysOn
                    ? Icons.visibility
                    : Icons.visibility_off,
                color: Colors.white54,
                size: 22,
              ),
              onPressed: _toggleOsdMode,
              tooltip: _osdMode == OsdMode.alwaysOn
                  ? 'OSD: Always On'
                  : 'OSD: Auto-Hide',
            ),
            // Gallery button.
            IconButton(
              icon: const Icon(
                Icons.video_library,
                color: Colors.white54,
                size: 22,
              ),
              onPressed: _openGallery,
              tooltip: 'DVR Gallery',
            ),
          ],
        ),
      ),
    );
  }
}
