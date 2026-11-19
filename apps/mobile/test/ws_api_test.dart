// The goggles' HTTP server chokes on concurrent connections, so a request that
// times out has to give its socket back before the next one opens one.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ws_wifi_stream/services/ws_api.dart';

const _timeout = Duration(milliseconds: 300);

/// Loopback goggles that accept every request and answer late, or never.
class _StuckGoggles {
  final ServerSocket _server;
  final Duration? answerAfter;
  int accepted = 0;
  int open = 0;
  int maxOpen = 0;
  final received = StringBuffer();

  _StuckGoggles._(this._server, this.answerAfter) {
    _server.listen(_serve);
  }

  static Future<_StuckGoggles> start({Duration? answerAfter}) async =>
      _StuckGoggles._(
          await ServerSocket.bind(InternetAddress.loopbackIPv4, 0),
          answerAfter);

  String get host => '127.0.0.1:${_server.port}';

  void _serve(Socket socket) {
    accepted++;
    open++;
    if (open > maxOpen) maxOpen = open;
    var closed = false;
    void onClosed() {
      if (closed) return;
      closed = true;
      open--;
      socket.destroy();
    }

    socket.done.catchError((_) {});
    var answered = false;
    socket.listen(
      (data) {
        received.write(latin1.decode(data));
        final delay = answerAfter;
        if (delay == null || answered) return;
        answered = true;
        Timer(delay, () {
          if (closed) return;
          const body = '{"nRetVal":0,"stValue":{}}';
          socket.write('HTTP/1.1 200 OK\r\n'
              'Content-Type: application/json\r\n'
              'Content-Length: ${body.length}\r\n\r\n$body');
        });
      },
      onDone: onClosed,
      onError: (_) => onClosed(),
      cancelOnError: true,
    );
  }

  Future<void> close() => _server.close();
}

Future<void> _pollUntilTimeouts(WSApi api, int times) async {
  for (var i = 0; i < times; i++) {
    await expectLater(api.getDeviceState(), throwsA(isA<TimeoutException>()));
    await Future.delayed(const Duration(milliseconds: 50));
  }
}

void main() {
  test('a poll the goggles never answer is closed before the next one opens',
      () async {
    final goggles = await _StuckGoggles.start();
    final api = WSApi(host: goggles.host, timeout: _timeout);

    await _pollUntilTimeouts(api, 3);

    expect(goggles.maxOpen, 1);
    expect(goggles.open, 0);
    expect(goggles.accepted, 3);
    api.dispose();
    await goggles.close();
  });

  test('a poll answered after the timeout is closed before the next one opens',
      () async {
    final goggles = await _StuckGoggles.start(answerAfter: _timeout * 2);
    final api = WSApi(host: goggles.host, timeout: _timeout);

    await _pollUntilTimeouts(api, 3);

    expect(goggles.maxOpen, 1);
    expect(goggles.open, 0);
    expect(goggles.accepted, 3);
    api.dispose();
    await goggles.close();
  });

  test('a poll that cannot connect stops trying when it times out', () async {
    // backlog 1, one client in it and nobody accepting: the kernel drops the
    // next SYNs, like goggles that are off or out of WiFi range.
    final server =
        await ServerSocket.bind(InternetAddress.loopbackIPv4, 0, backlog: 1);
    final filler = await Socket.connect(server.address, server.port);
    final api = WSApi(host: '127.0.0.1:${server.port}', timeout: _timeout);

    await _pollUntilTimeouts(api, 2);
    var late = -1; // the filler
    server.listen((socket) {
      late++;
      socket.destroy();
    });
    await Future.delayed(const Duration(seconds: 3));

    expect(late, 0, reason: 'a timed-out connect retried its SYN and got in');
    api.dispose();
    filler.destroy();
    await server.close();
  });

  test('a delete that times out is sent once and never again', () async {
    final goggles = await _StuckGoggles.start();
    final api = WSApi(host: goggles.host, timeout: _timeout);

    await expectLater(api.deleteRecord('AvatarG0001.mp4'),
        throwsA(isA<TimeoutException>()));
    await Future.delayed(_timeout * 3);

    expect('deletegasrecord'.allMatches(goggles.received.toString()).length, 1);
    expect(goggles.accepted, 1);
    api.dispose();
    await goggles.close();
  });
}
