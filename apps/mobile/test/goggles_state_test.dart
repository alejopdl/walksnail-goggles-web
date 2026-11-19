// Tests for the telemetry hysteresis in GogglesState.
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
  _FakeApi(this.next);

  @override
  Future<DeviceState> getDeviceState() async {
    if (fail) throw Exception('telemetry drop');
    return next;
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
}
