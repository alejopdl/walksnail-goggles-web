// Tests for how the dashboard's live video player behaves around the gallery,
// with a fake video platform that records which players are open.
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:video_player/video_player.dart';
import 'package:video_player_platform_interface/video_player_platform_interface.dart';
import 'package:ws_wifi_stream/models/device_state.dart';
import 'package:ws_wifi_stream/providers/goggles_state.dart';
import 'package:ws_wifi_stream/screens/dashboard.dart';
import 'package:ws_wifi_stream/services/ws_api.dart';

/// Playback position always advances, so the stall monitor never has a reason
/// to restart a player on its own.
class _FakePlayers extends VideoPlayerPlatform {
  final Duration connectTime;
  int opened = 0;
  int released = 0;
  int _ticks = 0;
  final _events = <int, StreamController<VideoEvent>>{};

  _FakePlayers({this.connectTime = Duration.zero});

  int get live => opened - released;

  @override
  Future<void> init() async {}

  @override
  Future<int?> createWithOptions(VideoCreationOptions options) async {
    final id = ++opened;
    // An async onCancel keeps the controller's dispose() on the test's fake
    // clock; without it, cancel() returns a root-zone future that only
    // completes after the test ends.
    final events = StreamController<VideoEvent>(onCancel: () async {});
    _events[id] = events;
    Future.delayed(
        connectTime,
        () => events.add(VideoEvent(
              eventType: VideoEventType.initialized,
              duration: const Duration(hours: 1),
              size: const Size(1280, 720),
            )));
    return id;
  }

  @override
  Stream<VideoEvent> videoEventsFor(int playerId) => _events[playerId]!.stream;

  @override
  Future<void> dispose(int playerId) async {
    released++;
    _events.remove(playerId);
  }

  @override
  Future<void> play(int playerId) async {}

  @override
  Future<void> pause(int playerId) async {}

  @override
  Future<void> setLooping(int playerId, bool looping) async {}

  @override
  Future<void> setVolume(int playerId, double volume) async {}

  @override
  Future<void> setPlaybackSpeed(int playerId, double speed) async {}

  @override
  Future<Duration> getPosition(int playerId) async =>
      Duration(milliseconds: 100 * ++_ticks);

  @override
  Widget buildViewWithOptions(VideoViewOptions options) => const SizedBox();
}

/// Goggles with the VTX linked and an empty SD card.
class _LinkedApi extends WSApi {
  @override
  Future<DeviceState> getDeviceState() async =>
      const DeviceState(isVtxConnected: true);

  @override
  Future<Map<String, dynamic>> listRecords(
          {int start = 0, int limit = 1215752191}) async =>
      {'rows': []};
}

Future<GogglesState> _showLiveVideo(
    WidgetTester tester, _FakePlayers players) async {
  VideoPlayerPlatform.instance = players;
  final g = GogglesState(
      api: _LinkedApi(), pollInterval: const Duration(milliseconds: 100));
  await tester.pumpWidget(ChangeNotifierProvider.value(
      value: g, child: const MaterialApp(home: DashboardScreen())));
  await _pumpSeconds(tester, 1); // link debounced, video up
  return g;
}

Future<void> _pumpSeconds(WidgetTester tester, double seconds) async {
  for (var t = 0; t < seconds * 10; t++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _close(WidgetTester tester, GogglesState g) async {
  await tester.pumpWidget(const SizedBox());
  g.dispose();
  await tester.pump(const Duration(seconds: 5));
}

void main() {
  testWidgets('releases the live video while the gallery is open',
      (tester) async {
    final players = _FakePlayers();
    final g = await _showLiveVideo(tester, players);
    expect(players.live, 1);
    expect(find.byType(VideoPlayer), findsOneWidget);

    await tester.tap(find.byIcon(Icons.video_library));
    await _pumpSeconds(tester, 30);
    expect(players.live, 0);
    expect(players.opened, 1, reason: 'nothing reopens it under the gallery');

    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await _pumpSeconds(tester, 1);
    expect(players.opened, 2);
    expect(players.live, 1);
    expect(find.byType(VideoPlayer), findsOneWidget);
    await _close(tester, g);
  });

  testWidgets('waits for the RTSP session to settle before reopening',
      (tester) async {
    final players = _FakePlayers();
    final g = await _showLiveVideo(tester, players);
    expect(find.byType(VideoPlayer), findsOneWidget);

    await tester.tap(find.byIcon(Icons.video_library));
    await _pumpSeconds(tester, 1);
    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await _pumpSeconds(tester, 1);
    expect(players.opened, 1, reason: 'released under 3 s ago');

    await _pumpSeconds(tester, 1.5);
    expect(players.opened, 2);
    expect(players.live, 1);
    await _close(tester, g);
  });

  testWidgets('drops a player that finishes connecting under the gallery',
      (tester) async {
    final players = _FakePlayers(connectTime: const Duration(seconds: 2));
    final g = await _showLiveVideo(tester, players); // still connecting
    expect(players.opened, 1);
    expect(find.byType(VideoPlayer), findsNothing);

    await tester.tap(find.byIcon(Icons.video_library));
    await _pumpSeconds(tester, 5);
    expect(players.live, 0);
    await _close(tester, g);
  });
}
