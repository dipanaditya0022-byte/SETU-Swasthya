import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/core/storage/local_database.dart';
import 'package:setu_swasthya/prototype/core/storage/sync_operation.dart';
import 'package:setu_swasthya/prototype/models/auth_requests.dart';
import 'package:setu_swasthya/prototype/models/patient.dart';
import 'package:setu_swasthya/prototype/models/referral.dart';
import 'package:setu_swasthya/prototype/repositories/patient_repository.dart';
import 'package:setu_swasthya/prototype/repositories/referral_repository.dart';
import 'package:setu_swasthya/prototype/services/connectivity_service.dart';
import 'package:setu_swasthya/prototype/services/patient_remote_data_source.dart';
import 'package:setu_swasthya/prototype/services/referral_remote_data_source.dart';
import 'package:setu_swasthya/prototype/services/sync_remote_data_source.dart';
import 'package:setu_swasthya/prototype/services/sync_service.dart';

const patientId = '123e4567-e89b-12d3-a456-426614174000';
const fromFacilityId = '123e4567-e89b-12d3-a456-426614174001';
const destinationFacilityId = '123e4567-e89b-12d3-a456-426614174002';

void main() {
  late Directory directory;
  late LocalDatabase database;

  setUpAll(() async {
    directory = await Directory.systemTemp.createTemp('setu_sync_test_');
    Hive.init(directory.path);
  });

  setUp(() async {
    database = await LocalDatabase.open();
    await database.patients.clear();
    await database.referrals.clear();
    await database.syncOperations.clear();
  });

  tearDown(() async {
    await database.close();
  });

  tearDownAll(() async {
    await directory.delete(recursive: true);
  });

  test(
    'Hive persists patient and referral records with sync metadata',
    () async {
      await database.savePatient('patient-local', {
        'local_id': 'patient-local',
        'sync_status': 'pending',
        'data': {'full_name': 'Asha'},
      });
      await database.saveReferral('referral-local', {
        'local_id': 'referral-local',
        'sync_status': 'synced',
        'data': {'reason': 'Review'},
      });

      expect(database.patients.get('patient-local')['sync_status'], 'pending');
      expect(database.referrals.get('referral-local')['sync_status'], 'synced');
    },
  );

  test('offline patient registration queues only network failures', () async {
    final sync = _syncService(database);
    final repository = PatientRepositoryImpl(
      _FakePatientSource(error: const NoInternetException()),
      localDatabase: database,
      syncService: sync,
    );

    final result = await repository.registerPatientOfflineAware(_request());

    expect(result.isPending, isTrue);
    expect(database.queue.single.type, SyncOperationType.patientRegistration);
    expect(database.queue.single.status, SyncOperationStatus.pending);
    expect(database.patients.values.single['sync_status'], 'pending');
  });

  test(
    'server validation errors are not converted to offline records',
    () async {
      final sync = _syncService(database);
      final repository = PatientRepositoryImpl(
        _FakePatientSource(
          error: const ValidationApiException(statusCode: 422),
        ),
        localDatabase: database,
        syncService: sync,
      );

      await expectLater(
        repository.registerPatientOfflineAware(_request()),
        throwsA(isA<ValidationApiException>()),
      );
      expect(database.queue, isEmpty);
      expect(database.patients.values, isEmpty);
    },
  );

  test(
    'offline referral creation persists a pending queue operation',
    () async {
      final sync = _syncService(database);
      final repository = ReferralRepositoryImpl(
        _FakeReferralSource(error: const NoInternetException()),
        localDatabase: database,
        syncService: sync,
      );

      final result = await repository.createReferralOfflineAware(_referral());

      expect(result.isPending, isTrue);
      expect(database.queue.single.type, SyncOperationType.referralCreation);
      expect(database.referrals.values.single['sync_status'], 'pending');
    },
  );

  test(
    'sync attempt retains failed state when response is undocumented',
    () async {
      final remote = _FakeSyncRemote(
        response: const SyncBatchResult(acknowledged: false),
      );
      final service = _syncService(database, remote: remote);
      await service.enqueue(
        type: SyncOperationType.referralCreation,
        payload: _referral().toJson(),
      );

      final result = await service.syncPending();

      expect(result.synced, 0);
      expect(database.queue.single.status, SyncOperationStatus.failed);
      expect(database.queue.single.lastError, contains('not acknowledged'));
    },
  );

  test(
    'sync retries network failures and prevents duplicate simultaneous runs',
    () async {
      final remote = _FakeSyncRemote(delay: Completer<void>());
      final service = _syncService(database, remote: remote);
      await service.enqueue(
        type: SyncOperationType.patientRegistration,
        payload: _request().toJson(),
      );

      final first = service.syncPending();
      final second = await service.syncPending();
      expect(second.message, 'Sync already running.');
      remote.delay!.complete();
      await first;
      expect(remote.calls, 1);

      remote.error = const NoInternetException();
      await service.syncPending();
      expect(database.queue.single.status, SyncOperationStatus.failed);
      expect(database.queue.single.attempts, greaterThan(1));
    },
  );

  test('connectivity transition triggers sync service callback', () async {
    final gateway = _FakeConnectivityGateway();
    final remote = _FakeSyncRemote(
      response: const SyncBatchResult(acknowledged: false),
    );
    final service = SyncService(
      database: database,
      remoteDataSource: remote,
      connectivity: gateway,
    );
    await service.enqueue(
      type: SyncOperationType.referralCreation,
      payload: _referral().toJson(),
    );
    final completed = Completer<void>();
    service.onConnectivityRestored = () async {
      await service.syncPending();
      completed.complete();
    };
    service.startConnectivityMonitoring();
    gateway.emit(true);
    await completed.future;
    expect(remote.calls, 1);
    await service.dispose();
  });
}

SyncService _syncService(
  LocalDatabase database, {
  SyncRemoteDataSource? remote,
}) => SyncService(
  database: database,
  remoteDataSource: remote ?? _FakeSyncRemote(),
  connectivity: _FakeConnectivityGateway(),
);

PatientRegistrationRequest _request() => const PatientRegistrationRequest(
  fullName: 'Asha Devi',
  sex: PatientSex.female,
  mobile: '9999999999',
  villageLgdCode: 'V-1',
  preferredLanguage: 'hi',
  consentKeepRecord: true,
  consentShareSpecialist: false,
  consentShareFacility: true,
  consentAnonymisedPlanning: false,
  consentMode: ConsentMode.digitalSelf,
  otpToken: 'verified-otp-token',
);

Referral _referral() => const Referral(
  patientId: patientId,
  fromFacilityId: fromFacilityId,
  destinationFacilityId: destinationFacilityId,
  reason: 'Specialist review',
  urgency: 'URGENT',
);

class _FakePatientSource implements PatientRemoteDataSource {
  _FakePatientSource({this.error});
  final ApiException? error;

  @override
  Future<void> registerPatient(PatientRegistrationRequest request) async {
    if (error != null) throw error!;
  }

  @override
  Future<Patient> createPatient(Patient patient) => throw UnimplementedError();

  @override
  Future<Patient> getPatient(String patientId) => throw UnimplementedError();

  @override
  Future<void> requestRegistrationOtp(OtpRequestBody request) =>
      throw UnimplementedError();

  @override
  Future<Map<String, dynamic>> verifyRegistrationOtp(OtpVerifyBody request) =>
      throw UnimplementedError();
}

class _FakeReferralSource implements ReferralRemoteDataSource {
  _FakeReferralSource({this.error});
  final ApiException? error;

  @override
  Future<Referral> createReferral(Referral referral) async {
    if (error != null) throw error!;
    return referral;
  }

  @override
  Future<void> updateReferralStatus(
    String id,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  ) => throw UnimplementedError();
}

class _FakeSyncRemote implements SyncRemoteDataSource {
  _FakeSyncRemote({this.response, this.delay});
  final SyncBatchResult? response;
  final Completer<void>? delay;
  ApiException? error;
  int calls = 0;

  @override
  Future<SyncBatchResult> sync(List<SyncOperation> operations) async {
    calls++;
    if (delay != null) await delay!.future;
    if (error != null) throw error!;
    return response ?? const SyncBatchResult(acknowledged: false);
  }
}

class _FakeConnectivityGateway implements ConnectivityGateway {
  final _controller = StreamController<bool>.broadcast();

  @override
  Stream<bool> get onOnlineChanged => _controller.stream;

  @override
  Future<bool> get isOnline async => true;

  void emit(bool online) => _controller.add(online);
}
