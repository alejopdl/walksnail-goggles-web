// Tests for GogglesState polling and its telemetry hysteresis.
//
// Mirrors the desktop fix: a brief control-plane poll failure must NOT flap the
// UI offline (the goggles are still there) — only sustained silence, past the
// offline-grace window, should read as disconnected. Durations are injected so
// the test runs in well under a second.
import 'package:flutter_test/flutter_test.dart';
import 'package:ws_wifi_stream/models/device_state.dart';
import 'package:ws_wifi_stream/providers/goggles_state.dart';
import 'package:ws_wifi_stream/services/ws_api.dart';

/// A WSApi stand-in whose telemetry the test drives directly.
class _FakeApi extends WSApi {
  bool fail = false;
  DeviceState next;
  Duration latency = Duration.zero;
  int calls = 0;
  int inFlight = 0;
  int maxInFlight = 0;
  _FakeApi(this.next);

  @override
  Future<DeviceState> getDeviceState() async {
    calls++;
    inFlight++;
    if (inFlight > maxInFlight) maxInFlight = inFlight;
    try {
      await Future.delayed(latency);
      if (fail) throw Exception('telemetry drop');
      return next;
    } finally {
      inFlight--;
    }
  }
}

const _linked = DeviceState(isVtxConnected: true, gogglesVoltage: 22.9);

void main() {
  test('reads online after a few good polls', () async {
    final g = GogglesState(
      api: _FakeApi(_linked),
      pollInterval: const Duration(milliseconds: 20),
      offlineGrace: const Duration(milliseconds: 300),
    );
    await Future.delayed(const Duration(milliseconds: 120));
    expect(g.gogglesReachable, isTrue);
    expect(g.isVtxConnected, isTrue); // debounced link settled true
    g.dispose();
  });

  test('a brief telemetry drop does NOT flap offline (hysteresis)', () async {
    final api = _FakeApi(_linked);
    final g = GogglesState(
      api: api,
      pollInterval: const Duration(milliseconds: 20),
      offlineGrace: const Duration(milliseconds: 400),
    );
    await Future.delayed(const Duration(milliseconds: 120));
    expect(g.gogglesReachable, isTrue);

    api.fail = true; // polls start failing
    await Future.delayed(const Duration(milliseconds: 150)); // still within grace
    expect(g.gogglesReachable, isTrue,
        reason: 'must hold last state through a short drop, not flap offline');

    await Future.delayed(const Duration(milliseconds: 450)); // now past grace
    expect(g.gogglesReachable, isFalse,
        reason: 'sustained silence should finally read offline');
    g.dispose();
  });

  test('recovers to online when telemetry returns', () async {
    final api = _FakeApi(_linked);
    final g = GogglesState(
      api: api,
      pollInterval: const Duration(milliseconds: 20),
      offlineGrace: const Duration(milliseconds: 200),
    );
    await Future.delayed(const Duration(milliseconds: 80));
    api.fail = true;
    await Future.delayed(const Duration(milliseconds: 400)); // drop offline
    expect(g.gogglesReachable, isFalse);

    api.fail = false; // link is back
    await Future.delayed(const Duration(milliseconds: 120));
    expect(g.gogglesReachable, isTrue);
    g.dispose();
  });

  test('never has more than one poll in flight when the goggles are slow',
      () async {
    final api = _FakeApi(_linked)
      ..latency = const Duration(milliseconds: 100);
    final g = GogglesState(
      api: api,
      pollInterval: const Duration(milliseconds: 20),
      offlineGrace: const Duration(milliseconds: 400),
    );
    await Future.delayed(const Duration(milliseconds: 350));
    g.pausePolling();
    await Future.delayed(const Duration(milliseconds: 150)); // let it drain
    expect(api.maxInFlight, 1);
    expect(api.calls, greaterThanOrEqualTo(3),
        reason: 'polling must keep going, one request after another');
    g.dispose();
  });

  test('time spent paused does not count toward going offline', () async {
    final api = _FakeApi(_linked);
    final g = GogglesState(
      api: api,
      pollInterval: const Duration(milliseconds: 20),
      offlineGrace: const Duration(milliseconds: 300),
    );
    await Future.delayed(const Duration(milliseconds: 120));
    expect(g.isVtxConnected, isTrue);

    g.pausePolling(); // gallery open
    await Future.delayed(const Duration(milliseconds: 500)); // longer than grace
    api.fail = true; // first poll after closing the gallery drops
    g.resumePolling();
    await Future.delayed(const Duration(milliseconds: 10));
    expect(g.gogglesReachable, isTrue,
        reason: 'one dropped poll after a pause must not read as offline');
    expect(g.isVtxConnected, isTrue);

    await Future.delayed(const Duration(milliseconds: 400)); // past grace
    expect(g.gogglesReachable, isFalse,
        reason: 'sustained silence after resuming still reads offline');
    g.dispose();
  });
}
