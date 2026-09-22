import '../core/network/api_exception.dart';
import '../core/storage/local_database.dart';
import '../core/storage/offline_write_result.dart';
import '../core/storage/sync_operation.dart';
import '../models/referral.dart';
import '../services/referral_remote_data_source.dart';
import '../services/sync_service.dart';

import 'package:uuid/uuid.dart';

abstract interface class ReferralRepository {
  Future<Referral> createReferral(Referral referral);
  Future<void> updateReferralStatus(
    String referralId,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  );
}

abstract interface class OfflineAwareReferralRepository {
  Future<OfflineWriteResult<Referral>> createReferralOfflineAware(
    Referral referral,
  );
}

class ReferralRepositoryImpl
    implements ReferralRepository, OfflineAwareReferralRepository {
  const ReferralRepositoryImpl(
    this._remoteDataSource, {
    this.localDatabase,
    this.syncService,
  });

  final ReferralRemoteDataSource _remoteDataSource;
  final LocalDatabase? localDatabase;
  final SyncService? syncService;

  @override
  Future<Referral> createReferral(Referral referral) =>
      _remoteDataSource.createReferral(referral);

  @override
  Future<void> updateReferralStatus(
    String referralId,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  ) => _remoteDataSource.updateReferralStatus(referralId, status, body);

  @override
  Future<OfflineWriteResult<Referral>> createReferralOfflineAware(
    Referral referral,
  ) async {
    try {
      final result = await _remoteDataSource.createReferral(referral);
      final localId = result.id ?? referral.id ?? const Uuid().v4();
      if (localDatabase != null) {
        await localDatabase!.saveReferral(localId, {
          'local_id': localId,
          'sync_status': 'synced',
          'data': result.toJson(),
        });
      }
      return OfflineWriteResult(
        disposition: OfflineWriteDisposition.online,
        value: result,
        localId: localId,
      );
    } on ApiException catch (error) {
      if (error is! NoInternetException && error is! ApiTimeoutException) {
        rethrow;
      }
      if (localDatabase == null || syncService == null) rethrow;
      final localId = await syncService!.enqueue(
        type: SyncOperationType.referralCreation,
        payload: referral.toJson(),
      );
      await localDatabase!.saveReferral(localId, {
        'local_id': localId,
        'sync_status': 'pending',
        'data': referral.toJson(),
      });
      return OfflineWriteResult(
        disposition: OfflineWriteDisposition.pending,
        value: referral,
        localId: localId,
      );
    }
  }
}
