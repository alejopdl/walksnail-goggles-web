// Tests for the DVR gallery against a loopback stand-in for the goggles' HTTP
// server, which records how many requests it is serving at once.
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:ws_wifi_stream/models/device_state.dart';
import 'package:ws_wifi_stream/providers/goggles_state.dart';
import 'package:ws_wifi_stream/screens/gallery_screen.dart';
import 'package:ws_wifi_stream/services/ws_api.dart';

/// Talks to the loopback server for the gallery, but keeps telemetry off the
/// wire so only gallery requests are counted.
class _GalleryApi extends WSApi {
  _GalleryApi(int port) : super(host: '127.0.0.1:$port');

  @override
  Future<DeviceState> getDeviceState() async => DeviceState.disconnected;
}

class _Goggles {
  late HttpServer _server;
  final bool sendLength;
  final Duration listDelay;
  final int clipBytes;
  int heads = 0;
  int headsDuringDownload = 0;
  int inFlight = 0;
  int maxInFlight = 0;
  bool downloading = false;
  final perFile = <String, int>{};

  _Goggles({
    this.sendLength = true,
    this.listDelay = Duration.zero,
    this.clipBytes = 64 * 1024,
  });

  int get port => _server.port;
  int get maxHeadsPerFile => perFile.values.fold(0, (a, b) => a > b ? a : b);

  Future<void> start(int clips) async {
    _server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _server.listen((req) async {
      inFlight++;
      if (inFlight > maxInFlight) maxInFlight = inFlight;
      try {
        if (req.method == 'HEAD') {
          heads++;
          if (downloading) headsDuringDownload++;
          perFile[req.uri.path] = (perFile[req.uri.path] ?? 0) + 1;
          await Future.delayed(const Duration(milliseconds: 50));
          if (sendLength) req.response.headers.contentLength = 12345678;
        } else if (req.method == 'GET') {
          downloading = true;
          req.response.headers.contentLength = clipBytes;
          for (var sent = 0; sent < clipBytes; sent += 8 * 1024) {
            req.response.add(List.filled(8 * 1024, 0));
            await req.response.flush();
            await Future.delayed(const Duration(milliseconds: 40));
          }
          downloading = false;
        } else {
          await utf8.decodeStream(req);
          await Future.delayed(listDelay);
          req.response.write(jsonEncode({
            'nRetVal': 0,
            'rows': [
              for (var i = 1; i <= clips; i++)
                {
                  'szFileName': 'AvatarG${i.toString().padLeft(4, '0')}.mp4',
                  'duration': 30,
                }
            ],
          }));
        }
        await req.response.close();
      } catch (_) {
        // The client went away mid-request (test teardown).
      } finally {
        inFlight--;
      }
    });
  }

  Future<void> stop() => _server.close(force: true);
}

Future<GogglesState> _openGallery(WidgetTester tester, _Goggles goggles,
    {int clips = 20}) async {
  HttpOverrides.global = null; // flutter_test answers every request with 400
  late GogglesState g;
  await tester.runAsync(() async {
    await goggles.start(clips);
    g = GogglesState(
        api: _GalleryApi(goggles.port),
        pollInterval: const Duration(hours: 1));
  });
  await tester.pumpWidget(ChangeNotifierProvider.value(
      value: g, child: const MaterialApp(home: GalleryScreen())));
  return g;
}

/// Lets real I/O run, rebuilding the screen each step like a download's
/// progress ticks do.
Future<void> _runFor(WidgetTester tester, Duration total) async {
  const step = Duration(milliseconds: 100);
  for (var t = Duration.zero; t < total; t += step) {
    await tester.runAsync(() => Future.delayed(step));
    // ignore: invalid_use_of_protected_member
    tester.state(find.byType(GalleryScreen)).setState(() {});
    await tester.pump();
  }
}

Future<void> _close(
    WidgetTester tester, GogglesState g, _Goggles goggles) async {
  await tester.pumpWidget(const SizedBox());
  g.dispose();
  await tester.runAsync(() async {
    await Future.delayed(const Duration(milliseconds: 200));
    await goggles.stop();
  });
  await tester.pump(const Duration(seconds: 30)); // expire request timeouts
}

void main() {
  testWidgets('asks each clip for its size once, one request at a time',
      (tester) async {
    final goggles = _Goggles();
    final g = await _openGallery(tester, goggles);
    await _runFor(tester, const Duration(seconds: 2));

    expect(goggles.maxInFlight, 1);
    expect(goggles.heads, greaterThan(1));
    expect(goggles.maxHeadsPerFile, 1);
    expect(find.textContaining('11.8 MB'), findsWidgets);
    await _close(tester, g, goggles);
  });

  testWidgets('does not ask again when the goggles send no size',
      (tester) async {
    final goggles = _Goggles(sendLength: false);
    final g = await _openGallery(tester, goggles, clips: 3);
    await _runFor(tester, const Duration(seconds: 3));

    expect(goggles.perFile.length, 3);
    expect(goggles.heads, 3);
    await _close(tester, g, goggles);
  });

  testWidgets('sends no size request while a clip downloads', (tester) async {
    final tmp = Directory.systemTemp.createTempSync('gallery_test');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/path_provider'),
        (call) async => tmp.path);
    final goggles = _Goggles(clipBytes: 128 * 1024);
    final g = await _openGallery(tester, goggles);
    await _runFor(tester, const Duration(milliseconds: 300));
    final headsBefore = goggles.heads;

    await tester.tap(find.byIcon(Icons.download).first);
    await _runFor(tester, const Duration(seconds: 2));

    expect(goggles.headsDuringDownload, 0);
    expect(goggles.maxInFlight, 1);
    expect(goggles.heads, greaterThan(headsBefore),
        reason: 'size requests resume once the download is done');
    await _close(tester, g, goggles);
    tmp.deleteSync(recursive: true);
  });

  testWidgets('leaving the gallery while the list loads does not throw',
      (tester) async {
    final goggles = _Goggles(listDelay: const Duration(milliseconds: 300));
    final g = await _openGallery(tester, goggles, clips: 3);
    await tester.pumpWidget(const SizedBox()); // back out right away
    for (var i = 0; i < 8; i++) {
      await tester.runAsync(
          () => Future.delayed(const Duration(milliseconds: 100)));
      await tester.pump();
    }

    expect(tester.takeException(), isNull);
    await _close(tester, g, goggles);
  });
}
