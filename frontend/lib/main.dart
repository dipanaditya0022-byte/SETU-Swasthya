import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import 'core/theme/app_theme.dart';
import 'models/patient.dart';
import 'models/referral_local.dart';
import 'screens/login_screen.dart';
import 'sync_service.dart';

void main() async {
  // Ensure Flutter engine is fully initialized
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize Hive and open the local patients box
  await Hive.initFlutter();
  if (!Hive.isAdapterRegistered(0)) {
  Hive.registerAdapter(PatientLocalAdapter());
}

if (!Hive.isAdapterRegistered(1)) {
  Hive.registerAdapter(ReferralLocalAdapter());
}

await Hive.openBox<PatientLocal>('patients');
await Hive.openBox<ReferralLocal>('referrals');

  SyncService().start();

  runApp(const SetuSwasthyaApp());
}

class SetuSwasthyaApp extends StatelessWidget {
  const SetuSwasthyaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SETU-Swasthya',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme(),
      home: const LoginScreen(),
    );
  }
}