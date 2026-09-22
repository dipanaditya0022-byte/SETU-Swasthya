import '../core/network/api_exception.dart';
import '../core/storage/local_database.dart';
import '../core/storage/offline_write_result.dart';
import '../core/storage/sync_operation.dart';
import '../models/auth_requests.dart';
import '../models/patient.dart';
import '../services/patient_remote_data_source.dart';
import '../services/sync_service.dart';

import 'package:uuid/uuid.dart';

abstract interface class PatientRepository {
  Future<Patient> createPatient(Patient patient);
  Future<Patient> getPatient(String patientId);
  Future<void> requestRegistrationOtp(String mobile);
  Future<String> verifyRegistrationOtp(String mobile, String otp);
  Future<void> registerPatient(PatientRegistrationRequest request);
}

abstract interface class OfflineAwarePatientRepository {
  Future<OfflineWriteResult<void>> registerPatientOfflineAware(
    PatientRegistrationRequest request,
  );
}

class PatientRepositoryImpl
    implements PatientRepository, OfflineAwarePatientRepository {
  const PatientRepositoryImpl(
    this._remoteDataSource, {
    this.localDatabase,
    this.syncService,
  });

  final PatientRemoteDataSource _remoteDataSource;
  final LocalDatabase? localDatabase;
  final SyncService? syncService;

  @override
  Future<Patient> createPatient(Patient patient) =>
      _remoteDataSource.createPatient(patient);

  @override
  Future<Patient> getPatient(String patientId) =>
      _remoteDataSource.getPatient(patientId);

  @override
  Future<void> requestRegistrationOtp(String mobile) =>
      _remoteDataSource.requestRegistrationOtp(
        OtpRequestBody(mobile: mobile, purpose: OtpPurpose.patientRegistration),
      );

  @override
  Future<String> verifyRegistrationOtp(String mobile, String otp) async {
    final response = await _remoteDataSource.verifyRegistrationOtp(
      OtpVerifyBody(mobile: mobile, otp: otp),
    );
    final token = response['otp_token'];
    if (token is! String || token.isEmpty) {
      throw const UnexpectedApiException(
        message: 'The OTP verification response did not contain an OTP token.',
      );
    }
    return token;
  }

  @override
  Future<void> registerPatient(PatientRegistrationRequest request) =>
      _remoteDataSource.registerPatient(request);

  @override
  Future<OfflineWriteResult<void>> registerPatientOfflineAware(
    PatientRegistrationRequest request,
  ) async {
    try {
      await _remoteDataSource.registerPatient(request);
      final localId = localDatabase == null ? null : const Uuid().v4();
      if (localId != null) {
        await localDatabase!.savePatient(localId, {
          'local_id': localId,
          'sync_status': 'synced',
          'data': request.toJson(),
        });
      }
      return OfflineWriteResult(
        disposition: OfflineWriteDisposition.online,
        localId: localId,
      );
    } on ApiException catch (error) {
      if (error is! NoInternetException && error is! ApiTimeoutException) {
        rethrow;
      }
      if (localDatabase == null || syncService == null) rethrow;
      final localId = await syncService!.enqueue(
        type: SyncOperationType.patientRegistration,
        payload: request.toJson(),
      );
      await localDatabase!.savePatient(localId, {
        'local_id': localId,
        'sync_status': 'pending',
        'data': request.toJson(),
      });
      return OfflineWriteResult(
        disposition: OfflineWriteDisposition.pending,
        localId: localId,
      );
    }
  }
}
