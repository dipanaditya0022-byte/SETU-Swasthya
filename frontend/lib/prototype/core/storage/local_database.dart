import 'package:hive_flutter/hive_flutter.dart';

import 'sync_operation.dart';

class LocalDatabase {
  LocalDatabase._({
    required this.patients,
    required this.referrals,
    required this.syncOperations,
  });

  static const patientsBoxName = 'setu_patients';
  static const referralsBoxName = 'setu_referrals';
  static const syncOperationsBoxName = 'setu_sync_operations';
  static LocalDatabase? current;

  final Box<dynamic> patients;
  final Box<dynamic> referrals;
  final Box<dynamic> syncOperations;

  static Future<LocalDatabase> open() async {
    final database = LocalDatabase._(
      patients: await Hive.openBox<dynamic>(patientsBoxName),
      referrals: await Hive.openBox<dynamic>(referralsBoxName),
      syncOperations: await Hive.openBox<dynamic>(syncOperationsBoxName),
    );
    current = database;
    return database;
  }

  Future<void> savePatient(String localId, Map<String, dynamic> record) =>
      patients.put(localId, record);

  Future<void> saveReferral(String localId, Map<String, dynamic> record) =>
      referrals.put(localId, record);

  Future<void> saveOperation(SyncOperation operation) =>
      syncOperations.put(operation.id, operation.toMap());

  List<SyncOperation> get queue =>
      syncOperations.values.whereType<Map>().map(SyncOperation.fromMap).toList()
        ..sort((a, b) => a.createdAt.compareTo(b.createdAt));

  Future<void> close() async {
    await patients.close();
    await referrals.close();
    await syncOperations.close();
    if (identical(current, this)) current = null;
  }
}
