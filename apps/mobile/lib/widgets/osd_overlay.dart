/// Translucent OSD overlay that sits on top of the video feed.
///
/// Shows telemetry icons + values. Supports three visibility modes:
///   - hidden (default): icons hidden, tap screen to show temporarily
///   - always on: icons permanently visible
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/goggles_state.dart';

enum OsdMode {
  /// OSD hidden by default; tap to show temporarily.
  autoHide,
  /// OSD always visible.
  alwaysOn,
}

class OsdOverlay extends StatefulWidget {
  final OsdMode mode;
  final VoidCallback? onTap;

  const OsdOverlay({
    super.key,
    this.mode = OsdMode.autoHide,
    this.onTap,
  });

  @override
  State<OsdOverlay> createState() => _OsdOverlayState();
}

class _OsdOverlayState extends State<OsdOverlay>
    with SingleTickerProviderStateMixin {
  bool _visible = false;
  Timer? _hideTimer;
  late AnimationController _fadeController;
  late Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _fadeAnimation = CurvedAnimation(
      parent: _fadeController,
      curve: Curves.easeInOut,
    );

    if (widget.mode == OsdMode.alwaysOn) {
      _visible = true;
      _fadeController.value = 1.0;
    }
  }

  @override
  void didUpdateWidget(OsdOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.mode == OsdMode.alwaysOn) {
      _show(permanent: true);
    }
  }

  void _show({bool permanent = false}) {
    _hideTimer?.cancel();
    setState(() => _visible = true);
    _fadeController.forward();

    if (!permanent && widget.mode == OsdMode.autoHide) {
      _hideTimer = Timer(const Duration(seconds: 4), () {
        _fadeController.reverse().then((_) {
          if (mounted) setState(() => _visible = false);
        });
      });
    }
  }

  void _handleTap() {
    widget.onTap?.call();
    if (widget.mode == OsdMode.autoHide) {
      if (_visible) {
        _hideTimer?.cancel();
        _fadeController.reverse().then((_) {
          if (mounted) setState(() => _visible = false);
        });
      } else {
        _show();
      }
    }
  }

  @override
  void dispose() {
    _hideTimer?.cancel();
    _fadeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: _handleTap,
      behavior: HitTestBehavior.translucent,
      child: FadeTransition(
        opacity: _fadeAnimation,
        child: Consumer<GogglesState>(
          builder: (context, goggles, _) {
            final s = goggles.state;
            return Stack(
              children: [
                // Top bar: VTX status + Bitrate (left-aligned to avoid control buttons on right)
                Positioned(
                  top: 12,
                  left: 16,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _OsdChip(
                        icon: Icons.wifi,
                        label: s.isVtxConnected ? 'LINKED' : 'NO VTX',
                        color: s.isVtxConnected ? Colors.greenAccent : Colors.redAccent,
                      ),
                      const SizedBox(width: 8),
                      _OsdChip(
                        icon: Icons.speed,
                        label: s.bitrateFormatted,
                        color: Colors.cyanAccent,
                      ),
                    ],
                  ),
                ),
                // Bottom bar: Battery, Temp, SD, Delay
                Positioned(
                  bottom: 12,
                  left: 16,
                  right: 16,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceAround,
                    children: [
                      _OsdChip(
                        icon: Icons.battery_full,
                        label: '${s.vtxVoltage.toStringAsFixed(1)}V',
                        color: s.vtxVoltage > 3.5
                            ? Colors.greenAccent
                            : Colors.redAccent,
                      ),
                      _OsdChip(
                        icon: Icons.thermostat,
                        label: '${s.vtxTemp}°C',
                        color: s.vtxTemp < 60
                            ? Colors.cyanAccent
                            : Colors.orangeAccent,
                      ),
                      _OsdChip(
                        icon: Icons.sd_card,
                        label: '${s.gogglesSdSpaceMb} MB',
                        color: Colors.white70,
                      ),
                      _OsdChip(
                        icon: Icons.timer,
                        label: '${s.delayMs} ms',
                        color: Colors.white70,
                      ),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// A single translucent OSD chip with an icon and a value.
class _OsdChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;

  const _OsdChip({
    required this.icon,
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.45),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.3), width: 0.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 16),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
