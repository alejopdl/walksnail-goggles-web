/// Pure Dart HTTP client for the FPV goggles control plane.
///
/// Ported 1:1 from the Python `protocol.py` + `client.py`.
/// All calls go directly from the phone to the goggles over WiFi (no proxy).
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import '../models/device_state.dart';

class WSApi {
  static const defaultHost = '192.168.42.1';
  static const _epAjaxcom = '/ajaxcom';
  static const _epQuerydata = '/querydata';

  final String host;
  final Duration timeout;
  final http.Client _client;

  WSApi({
    this.host = defaultHost,
    this.timeout = const Duration(seconds: 5),
  }) : _client = IOClient(
            // An abort only reaches a request once it is connected; without
            // this a connect to absent goggles lingers ~30 s in SYN_SENT.
            HttpClient()..connectionTimeout = timeout);

  String get rtspUrl => 'rtsp://$host/live.ch01';

  // --------------- transport ---------------

  Future<Map<String, dynamic>> _post(
      String endpoint, Map<String, dynamic> bodyObj) async {
    final szCmd = 'szCmd=${jsonEncode(bodyObj)}';
    final uri = Uri.parse('http://$host$endpoint');

    // No 'Connection: close': the goggles run a tiny embedded HTTP server and a
    // fresh TCP connection per poll (twice a second) floods it with churn. We
    // reuse one pooled keep-alive connection (shared [_client]) so polling stays
    // on a single socket — otherwise, on some platforms, closed sockets pile up
    // and polls fail in bursts, flapping the UI online/offline.
    final response = await _send(
        uri, {'Content-Type': 'application/x-www-form-urlencoded'}, szCmd,
        timeout);

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final ret = data['nRetVal'] as int? ?? 0;
    if (ret != 0) {
      throw WSApiError(ret, data['szError']?.toString() ?? '');
    }
    return data;
  }

  /// POSTs [body], giving up after [limit]. A timed-out request is aborted, not
  /// just abandoned: otherwise its socket stays open and the next request opens
  /// another one beside it, on a server that copes with one at a time.
  Future<http.Response> _send(Uri uri, Map<String, String> headers,
      String body, Duration limit) async {
    final abort = Completer<void>();
    final request =
        http.AbortableRequest('POST', uri, abortTrigger: abort.future)
          ..headers.addAll(headers)
          ..body = body;
    try {
      return await _client
          .send(request)
          .then(http.Response.fromStream)
          .timeout(limit);
    } on TimeoutException {
      abort.complete();
      rethrow;
    }
  }

  Future<Map<String, dynamic>> _ajax(Map<String, dynamic> bodyObj) =>
      _post(_epAjaxcom, bodyObj);

  Future<Map<String, dynamic>> _query(Map<String, dynamic> bodyObj) =>
      _post(_epQuerydata, bodyObj);

  // --------------- system queries ---------------

  /// Check if the goggles are reachable on the network.
  Future<bool> isOnline() async {
    try {
      final data = await _ajax({'SysQuery': {'onlinequery': {}}});
      return (data['stValue'] as Map?)?['online'] == 1;
    } catch (_) {
      return false;
    }
  }

  /// Full device telemetry (battery, temp, link, bitrate, etc.).
  ///
  /// Throws on a failed poll (rather than returning [DeviceState.disconnected])
  /// so the caller can apply hysteresis — a single dropped poll on a weak link
  /// shouldn't be indistinguishable from a real disconnect.
  Future<DeviceState> getDeviceState() async {
    final data = await _ajax({'SysQuery': {'devicestate': 0}});
    final stValue = data['stValue'] as Map<String, dynamic>? ?? {};
    return DeviceState.fromJson(stValue);
  }

  /// Device version info (serial numbers, firmware versions).
  Future<Map<String, dynamic>> getVersion() async {
    final data = await _ajax({'SysQuery': {'version': {}}});
    return data['stValue'] as Map<String, dynamic>? ?? {};
  }

  // --------------- system controls ---------------

  Future<void> setTime(DateTime when) async {
    await _ajax({
      'SysCtrl': {
        'settime': {
          'dwYear': when.year,
          'byMonth': when.month,
          'byDay': when.day,
          'byHour': when.hour,
          'byMinute': when.minute,
          'bySecond': when.second,
        }
      }
    });
  }

  Future<void> reboot() => _ajax({'SysCtrl': {'reboot': {}}});
  Future<void> factoryReset() => _ajax({'SysCtrl': {'default': {}}});
  Future<void> formatGogglesSd() =>
      _ajax({'SysCtrl': {'gassdcardformat': {}}});
  Future<void> formatVtxSd() => _ajax({'SysCtrl': {'vtxsdcardformat': {}}});

  // --------------- DVR records ---------------

  /// List DVR recordings. Returns {'total': int, 'rows': [...]}.
  Future<Map<String, dynamic>> listRecords(
      {int start = 0, int limit = 1215752191}) async {
    // DVR queries can be slow if there are many files on the SD card.
    final szCmd = 'szCmd=${jsonEncode({'query_record': {'start': start, 'limit': limit}})}';  
    final uri = Uri.parse('http://$host$_epQuerydata');
    final response = await _send(
        uri,
        {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Connection': 'close',
        },
        szCmd,
        const Duration(seconds: 15));
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final ret = data['nRetVal'] as int? ?? 0;
    if (ret != 0) {
      throw WSApiError(ret, data['szError']?.toString() ?? '');
    }
    return data;
  }

  /// Direct download URL for a DVR clip. The filename is percent-encoded so a
  /// rogue/odd name can't break the URL or escape the /record/ path.
  String recordUrl(String filename) =>
      'http://$host/record/${Uri.encodeComponent(filename)}';

  Future<void> deleteRecord(String filename) async {
    await _ajax({
      'SysCtrl': {
        'deletegasrecord': {'szFileName': checkClipName(filename)}
      }
    });
  }

  void dispose() {
    _client.close();
  }
}

final _clipName = RegExp(r'^[A-Za-z0-9._-]+$');

/// Returns [filename] if it is a plain DVR file name; throws otherwise.
///
/// The szCmd body is not form-encoded, so `&`, `%` or quotes in a name could
/// add a second command; `/` or `..` would escape a local folder.
String checkClipName(String filename) {
  if (!_clipName.hasMatch(filename) || filename == '.' || filename == '..') {
    throw ArgumentError.value(filename, 'filename', 'invalid clip name');
  }
  return filename;
}

class WSApiError implements Exception {
  final int code;
  final String message;
  WSApiError(this.code, this.message);

  @override
  String toString() => 'WSApiError($code): $message';
}
