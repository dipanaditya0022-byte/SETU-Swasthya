import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../core/storage/local_database.dart';
import '../core/storage/offline_write_result.dart';
import '../models/referral.dart';
import '../repositories/referral_repository.dart';
import '../services/referral_remote_data_source.dart';
import 'api_providers.dart';
import 'sync_providers.dart';

final referralRemoteDataSourceProvider = Provider<ReferralRemoteDataSource>(
  (ref) => DioReferralRemoteDataSource(ref.watch(apiClientProvider).dio),
);

final referralRepositoryProvider = Provider<ReferralRepository>(
  (ref) => ReferralRepositoryImpl(
    ref.watch(referralRemoteDataSourceProvider),
    localDatabase: LocalDatabase.current,
    syncService: LocalDatabase.current == null
        ? null
        : ref.watch(syncServiceProvider),
  ),
);

enum ReferralStatus { idle, creating, updating, success, error }

class ReferralStateData {
  const ReferralStateData({
    this.status = ReferralStatus.idle,
    this.referral,
    this.currentStatus,
    this.errorMessage,
    this.pendingOffline = false,
  });

  final ReferralStatus status;
  final Referral? referral;
  final ReferralState? currentStatus;
  final String? errorMessage;
  final bool pendingOffline;

  bool get isBusy =>
      status == ReferralStatus.creating || status == ReferralStatus.updating;
}

final referralControllerProvider =
    NotifierProvider<ReferralController, ReferralStateData>(
      ReferralController.new,
    );

class ReferralController extends Notifier<ReferralStateData> {
  @override
  ReferralStateData build() => const ReferralStateData();

  Future<void> create(Referral referral) async {
    if (state.isBusy) return;
    state = const ReferralStateData(status: ReferralStatus.creating);
    try {
      final repository = ref.read(referralRepositoryProvider);
      final result = repository is OfflineAwareReferralRepository
          ? await (repository as OfflineAwareReferralRepository)
                .createReferralOfflineAware(referral)
          : OfflineWriteResult<Referral>(
              disposition: OfflineWriteDisposition.online,
              value: await repository.createReferral(referral),
            );
      state = ReferralStateData(
        status: ReferralStatus.success,
        referral: result.value,
        currentStatus: result.value?.status,
        pendingOffline: result.isPending,
      );
    } on ApiException catch (error) {
      _fail(error);
    }
  }

  Future<void> updateStatus(
    String referralId,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  ) async {
    if (state.isBusy) return;
    state = ReferralStateData(
      status: ReferralStatus.updating,
      referral: state.referral,
      currentStatus: state.currentStatus,
    );
    try {
      await ref
          .read(referralRepositoryProvider)
          .updateReferralStatus(referralId, status, body);
      state = ReferralStateData(
        status: ReferralStatus.success,
        referral: state.referral,
        currentStatus: status,
      );
    } on ApiException catch (error) {
      _fail(error);
    }
  }

  void _fail(ApiException error) {
    final message = switch (error) {
      ValidationApiException() => 'Please check the referral details.',
      ClientApiException(statusCode: 401) ||
      ClientApiException(
        statusCode: 403,
      ) => 'Authentication is required for this referral action.',
      ClientApiException(statusCode: 404) => 'Referral not found.',
      ClientApiException() => 'The referral request was not accepted.',
      NoInternetException() =>
        'Unable to connect. Check your internet connection and try again.',
      ApiTimeoutException() =>
        'The referral request timed out. Please try again.',
      ServerApiException() =>
        'Something went wrong on the server. Please try again.',
      _ => 'Unable to complete the referral action. Please try again.',
    };
    state = ReferralStateData(
      status: ReferralStatus.error,
      referral: state.referral,
      currentStatus: state.currentStatus,
      errorMessage: message,
    );
  }
}
