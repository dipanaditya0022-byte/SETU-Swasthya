import 'package:flutter/foundation.dart';
import 'package:hive/hive.dart';
import 'package:connectivity_plus/connectivity_plus.dart';

import 'dart:async';

import 'models/patient.dart';
import 'api_service.dart';

class SyncService {
  final ApiService _apiService = ApiService();
  StreamSubscription<List<ConnectivityResult>>? _connectivitySubscription;
  bool _isSyncing = false;

  void start() {
    _connectivitySubscription ??= Connectivity().onConnectivityChanged.listen((
      results,
    ) {
      if (_hasNetworkConnection(results)) {
        syncUnsyncedPatients();
      }
    });

    Connectivity().checkConnectivity().then((results) {
      if (_hasNetworkConnection(results)) {
        syncUnsyncedPatients();
      }
    });
  }

  bool _hasNetworkConnection(List<ConnectivityResult> results) {
    return results.any((result) => result != ConnectivityResult.none);
  }

  Future<void> syncUnsyncedPatients() async {
    if (_isSyncing) {
      return;
    }

    _isSyncing = true;
    final box = Hive.box<PatientLocal>('patients');

    try {
      final unsyncedPatients = box.values.where((p) => !p.synced).toList();

      if (unsyncedPatients.isEmpty) {
        debugPrint('No offline patients to sync.');
        return;
      }

      for (var patient in unsyncedPatients) {
        if (patient.phone.trim().isEmpty || patient.facilityId.trim().isEmpty) {
          debugPrint(
            'Skipping unsynced patient ${patient.clientUuid} because it is missing phone/facilityId (older Hive record).',
          );
          continue;
        }

        try {
          final createdPatient = await _apiService.createPatient(
            name: patient.name,
            age: patient.age,
            village: patient.village,
            phone: patient.phone,
            facilityId: patient.facilityId,
            clientUuid: patient.clientUuid,
          );

          final backendPatientId = (createdPatient['id'] ?? '')
              .toString()
              .trim();
          if (backendPatientId.isNotEmpty) {
            patient.backendPatientId = backendPatientId;
          }

          patient.synced = true;
          await patient.save();
        } catch (e) {
          debugPrint('Failed to sync patient ${patient.name}: $e');
          break;
        }
      }
    } finally {
      _isSyncing = false;
    }
  }
}
