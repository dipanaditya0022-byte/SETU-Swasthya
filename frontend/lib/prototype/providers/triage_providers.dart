import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/triage.dart';
import '../repositories/triage_repository.dart';
import '../services/triage_remote_data_source.dart';
import 'api_providers.dart';

final triageRemoteDataSourceProvider = Provider<TriageRemoteDataSource>(
  (ref) => DioTriageRemoteDataSource(ref.watch(apiClientProvider).dio),
);

final triageRepositoryProvider = Provider<TriageRepository>(
  (ref) => TriageRepositoryImpl(ref.watch(triageRemoteDataSourceProvider)),
);

enum TriageStatus { idle, submitting, success, error }

class TriageState {
  const TriageState({
    this.status = TriageStatus.idle,
    this.response,
    this.errorMessage,
  });

  final TriageStatus status;
  final TriageEvaluationResponse? response;
  final String? errorMessage;

  bool get isSubmitting => status == TriageStatus.submitting;
}

final triageControllerProvider =
    NotifierProvider<TriageController, TriageState>(TriageController.new);

class TriageController extends Notifier<TriageState> {
  @override
  TriageState build() => const TriageState();

  Future<void> submit(TriageEvaluationRequest request) async {
    if (state.isSubmitting) return;
    state = const TriageState(status: TriageStatus.submitting);
    try {
      final response = await ref
          .read(triageRepositoryProvider)
          .createTriage(request);
      state = TriageState(status: TriageStatus.success, response: response);
    } on ApiException catch (error) {
      state = TriageState(
        status: TriageStatus.error,
        errorMessage: _messageFor(error),
      );
    }
  }

  static String _messageFor(ApiException error) => switch (error) {
    ValidationApiException() => 'Please check the triage details.',
    ClientApiException(statusCode: 401) ||
    ClientApiException(
      statusCode: 403,
    ) => 'Authentication is required for triage.',
    ClientApiException() => 'The triage request was not accepted.',
    NoInternetException() =>
      'Unable to connect. Check your internet connection and try again.',
    ApiTimeoutException() => 'The triage request timed out. Please try again.',
    ServerApiException() =>
      'Something went wrong on the server. Please try again.',
    _ => 'Unable to submit triage. Please try again.',
  };
}
