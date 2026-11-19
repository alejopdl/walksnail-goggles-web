// A clip name from the goggles' listing goes unencoded into the szCmd form body
// and into a local file path, so names outside the DVR charset must be refused
// before either is built.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ws_wifi_stream/screens/gallery_screen.dart';
import 'package:ws_wifi_stream/services/ws_api.dart';

void main() {
  test('delete with a crafted clip name sends nothing to the goggles',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final bodies = <String>[];
    server.listen((req) async {
      bodies.add(await utf8.decoder.bind(req).join());
      req.response.write('{"nRetVal":0}');
      await req.response.close();
    });
    final api = WSApi(host: '127.0.0.1:${server.port}');

    Object? error;
    try {
      await api.deleteRecord('x&szCmd={%22SysCtrl%22:{%22reboot%22:{}}}&z=');
    } catch (e) {
      error = e;
    }

    expect(bodies, isEmpty);
    expect(error, isArgumentError);
    api.dispose();
    await server.close(force: true);
  });

  test('a downloaded clip cannot be written outside the temp folder', () {
    expect(() => clipTempPath('/data/cache', '../../shared_prefs/x.xml'),
        throwsArgumentError);
    expect(clipTempPath('/data/cache', 'AvatarG0531.mp4'),
        '/data/cache/AvatarG0531.mp4');
  });
}
