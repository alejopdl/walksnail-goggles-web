/// Central state provider for the goggles connection.
///
/// Polls `devicestate` in a background loop. Exposes [state] (live telemetry)
/// and [isVtxConnected] (Watchdog trigger).
///
/// Reliability (mirrors the desktop app's fixes):
///  * VTX link state is **debounced** (needs a couple of agreeing polls) so a
///    single flaky reading while the goggles boot doesn't rapidly start/stop the
///    player — rapid restarts can wedge the goggles' single-session RTSP server.
///  * Polling can be **paused** (e.g. while the gallery is open / downloading)
///    so we don't hammer the goggles' tiny HTTP server.
import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/device_state.dart';
import '../services/ws_api.dart';

class GogglesState extends ChangeNotifier {
  final WSApi _api;

  // Accept a VTX link-state change only after this many agreeing polls.
  static const _vtxDebounce = 2;
  // Poll cadence + offline hysteresis. Injectable so tests can drive them fast;
  // production defaults (500ms / 5s) match the desktop app. Holding the last
  // telemetry through a brief silence stops the UI flapping online/offline when
  // the odd poll drops on a weak link.
  final Duration _pollInterval;
  final Duration _offlineGrace;
  DateTime _lastOk = DateTime.fromMillisecondsSinceEpoch(0);

  DeviceState _state = DeviceState.disconnected;
  DeviceState get state => _state;

  bool _gogglesReachable = false;
  bool get gogglesReachable => _gogglesReachable;

  // Debounced VTX link state — this is what the Watchdog reacts to.
  bool _stableVtx = false;
  int _vtxPending = 0;
  bool get isVtxConnected => _stableVtx;

  DateTime? _pausedAt; // non-null while paused
  bool _polling = false;
  Timer? _pollTimer;

  GogglesState({
    WSApi? api,
    Duration pollInterval = const Duration(milliseconds: 500),
    Duration offlineGrace = const Duration(seconds: 5),
  })  : _api = api ?? WSApi(),
        _pollInterval = pollInterval,
        _offlineGrace = offlineGrace {
    _startPolling();
  }

  void _startPolling() {
    _pollTimer = Timer.periodic(_pollInterval, (_) async {
      await _tick();
    });
    _tick(); // run immediately on creation
  }

  /// Pause polling (e.g. while the gallery is open) so a heavy DVR query /
  /// download doesn't compete with telemetry on the goggles.
  void pausePolling() => _pausedAt ??= DateTime.now();
  void resumePolling() {
    final pausedAt = _pausedAt;
    if (pausedAt != null) {
      // Paused time isn't silence from the goggles: without this, the first
      // dropped poll after closing the gallery reads as offline and restarts
      // the video player.
      _lastOk = _lastOk.add(DateTime.now().difference(pausedAt));
      _pausedAt = null;
    }
    _tick();
  }

  Future<void> _tick() async {
    // One poll at a time: when the goggles answer slower than the interval,
    // skip ticks instead of stacking concurrent requests on their HTTP server.
    if (_pausedAt != null || _polling) return;
    _polling = true;
    try {
      final newState = await _api.getDeviceState();
      _gogglesReachable = true;
      _lastOk = DateTime.now();
      _state = newState;

      // Debounce the VTX link state.
      final raw = newState.isVtxConnected;
      if (raw != _stableVtx) {
        _vtxPending++;
        if (_vtxPending >= _vtxDebounce) {
          _stableVtx = raw;
          _vtxPending = 0;
        }
      } else {
        _vtxPending = 0;
      }

      // Always notify so the OSD values refresh on screen.
      notifyListeners();
    } catch (_) {
      // Transient poll failure. Hold the last telemetry (and the stable VTX, so
      // the player doesn't flap) and only declare the goggles offline after a
      // sustained silence — a single dropped poll on a weak link is normal and
      // shouldn't blank the UI.
      if (_gogglesReachable &&
          DateTime.now().difference(_lastOk) >= _offlineGrace) {
        _gogglesReachable = false;
        _state = DeviceState.disconnected;
        _stableVtx = false;
        _vtxPending = 0;
        notifyListeners();
      }
    } finally {
      _polling = false;
    }
  }

  /// Sync goggles clock to the phone's current time.
  Future<void> syncTime() async {
    await _api.setTime(DateTime.now());
  }

  /// Reboot the goggles.
  Future<void> reboot() async {
    await _api.reboot();
  }

  /// Format the goggles SD card.
  Future<void> formatGogglesSd() async {
    await _api.formatGogglesSd();
  }

  WSApi get api => _api;

  @override
  void dispose() {
    _pollTimer?.cancel();
    _api.dispose();
    super.dispose();
  }
}
