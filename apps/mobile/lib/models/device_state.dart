/// Strongly typed model for FPV goggles telemetry data.
///
/// Parsed from the `stValue` field of a `devicestate` query response.
/// JSON keys sourced from the actual goggles protocol:
///   vtx_connect, gas_voltage, vtx_voltage, vtx_tempeture, gas_tempeture,
///   bitrate, u8_mcs, distance, gas_sd_space, vtx_sd_space,
///   gas_rec_state, vtx_rec_state, delaytime
class DeviceState {
  final bool isVtxConnected;
  final double gogglesVoltage;
  final double vtxVoltage;
  final int vtxTemp;
  final int gogglesTemp;
  final int bitrate;
  final int mcs;
  final int distance;
  final int gogglesSdSpaceMb;
  final int vtxSdSpaceMb;
  final bool gogglesRecording;
  final bool vtxRecording;
  final int delayMs;

  const DeviceState({
    this.isVtxConnected = false,
    this.gogglesVoltage = 0.0,
    this.vtxVoltage = 0.0,
    this.vtxTemp = 0,
    this.gogglesTemp = 0,
    this.bitrate = 0,
    this.mcs = 0,
    this.distance = 0,
    this.gogglesSdSpaceMb = 0,
    this.vtxSdSpaceMb = 0,
    this.gogglesRecording = false,
    this.vtxRecording = false,
    this.delayMs = 0,
  });

  /// The "empty" state shown when we can't reach the goggles at all.
  static const disconnected = DeviceState();

  factory DeviceState.fromJson(Map<String, dynamic> json) {
    return DeviceState(
      isVtxConnected: _parseInt(json['vtx_connect']) == 1,
      gogglesVoltage: _parseDouble(json['gas_voltage']),
      vtxVoltage: _parseDouble(json['vtx_voltage']),
      vtxTemp: _parseInt(json['vtx_tempeture']),
      gogglesTemp: _parseInt(json['gas_tempeture']),
      bitrate: _parseInt(json['bitrate']),
      mcs: _parseInt(json['u8_mcs']),
      distance: _parseInt(json['distance']),
      gogglesSdSpaceMb: _parseInt(json['gas_sd_space']),
      vtxSdSpaceMb: _parseInt(json['vtx_sd_space']),
      gogglesRecording: _parseInt(json['gas_rec_state']) == 1,
      vtxRecording: _parseInt(json['vtx_rec_state']) == 1,
      delayMs: _parseInt(json['delaytime']),
    );
  }

  /// Human-readable bitrate (e.g. "24.2 Mbps").
  String get bitrateFormatted {
    if (bitrate <= 0) return '--';
    final mbps = bitrate / 1e6;
    return '${mbps.toStringAsFixed(1)} Mbps';
  }

  static double _parseDouble(dynamic value) {
    if (value == null) return 0.0;
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }

  static int _parseInt(dynamic value) {
    if (value == null) return 0;
    if (value is num) return value.toInt();
    if (value is String) return int.tryParse(value) ?? 0;
    return 0;
  }
}
