import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import 'models/patient.dart';
import 'models/referral_local.dart';
import 'prototype/app.dart';
import 'prototype/core/storage/local_database.dart';
import 'sync_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Hive.initFlutter();
  if (!Hive.isAdapterRegistered(0)) {
    Hive.registerAdapter(PatientLocalAdapter());
  }
  if (!Hive.isAdapterRegistered(1)) {
    Hive.registerAdapter(ReferralLocalAdapter());
  }
  await Hive.openBox<PatientLocal>('patients');
  await Hive.openBox<ReferralLocal>('referrals');
  await LocalDatabase.open();
  SyncService().start();
  runApp(const SetuSwasthyaApp());
}
