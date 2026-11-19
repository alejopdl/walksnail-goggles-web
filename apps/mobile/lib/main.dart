import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'providers/goggles_state.dart';
import 'screens/dashboard.dart';
import 'services/video_config.dart';

void main() {
  // Initialize the fvp/libmdk video backend (live-latency mode, HW decoders,
  // default RTSP transport). See services/video_config.dart.
  configureFvp();

  runApp(const WSApp());
}

class WSApp extends StatelessWidget {
  const WSApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => GogglesState(),
      child: MaterialApp(
        title: 'WS WiFi Stream',
        debugShowCheckedModeBanner: false,
        theme: ThemeData.dark().copyWith(
          scaffoldBackgroundColor: Colors.black,
          colorScheme: ColorScheme.fromSeed(
            seedColor: Colors.cyanAccent,
            brightness: Brightness.dark,
          ),
        ),
        home: const DashboardScreen(),
      ),
    );
  }
}
