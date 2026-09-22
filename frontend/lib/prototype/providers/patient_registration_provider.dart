import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../core/storage/offline_write_result.dart';
import '../models/patient.dart';
import '../repositories/patient_repository.dart';
import 'api_providers.dart';

enum RegistrationStatus {
  idle,
  requestingOtp,
  verifyingOtp,
  submitting,
  success,
  failure,
}

class PatientRegistrationState {
  const PatientRegistrationState({
    this.status = RegistrationStatus.idle,
    this.otpToken,
    this.errorMessage,
    this.pendingOffline = false,
  });

  final RegistrationStatus status;
  final String? otpToken;
  final String? errorMessage;
  final bool pendingOffline;

  bool get isBusy =>
      status == RegistrationStatus.requestingOtp ||
      status == RegistrationStatus.verifyingOtp ||
      status == RegistrationStatus.submitting;

  PatientRegistrationState copyWith({
    RegistrationStatus? status,
    String? otpToken,
    String? errorMessage,
    bool clearError = false,
    bool? pendingOffline,
  }) {
    return PatientRegistrationState(
      status: status ?? this.status,
      otpToken: otpToken ?? this.otpToken,
      errorMessage: clearError ? null : errorMessage ?? this.errorMessage,
      pendingOffline: pendingOffline ?? this.pendingOffline,
    );
  }
}

final patientRegistrationProvider =
    NotifierProvider<PatientRegistrationController, PatientRegistrationState>(
      PatientRegistrationController.new,
    );

class PatientRegistrationController extends Notifier<PatientRegistrationState> {
  PatientRepository get _repository => ref.read(patientRepositoryProvider);

  @override
  PatientRegistrationState build() => const PatientRegistrationState();

  Future<void> requestOtp(String mobile) async {
    if (state.isBusy) return;
    state = state.copyWith(
      status: RegistrationStatus.requestingOtp,
      clearError: true,
    );
    try {
      await _repository.requestRegistrationOtp(mobile);
      state = state.copyWith(status: RegistrationStatus.idle);
    } on ApiException catch (error) {
      _setFailure(error);
    }
  }

  Future<void> verifyOtp(String mobile, String otp) async {
    if (state.isBusy) return;
    state = state.copyWith(
      status: RegistrationStatus.verifyingOtp,
      clearError: true,
    );
    try {
      final token = await _repository.verifyRegistrationOtp(mobile, otp);
      state = state.copyWith(status: RegistrationStatus.idle, otpToken: token);
    } on ApiException catch (error) {
      _setFailure(error);
    }
  }

  Future<void> submit(PatientRegistrationRequest request) async {
    if (state.isBusy) return;
    if (state.otpToken == null || state.otpToken!.isEmpty) {
      state = state.copyWith(
        status: RegistrationStatus.failure,
        errorMessage: 'Verify the OTP before submitting registration.',
      );
      return;
    }
    state = state.copyWith(
      status: RegistrationStatus.submitting,
      clearError: true,
    );
    try {
      final result = _repository is OfflineAwarePatientRepository
          ? await (_repository as OfflineAwarePatientRepository)
                .registerPatientOfflineAware(request)
          : OfflineWriteResult<void>(
              disposition: OfflineWriteDisposition.online,
            );
      if (_repository is! OfflineAwarePatientRepository) {
        await _repository.registerPatient(request);
      }
      state = state.copyWith(
        status: RegistrationStatus.success,
        pendingOffline: result.isPending,
      );
    } on ApiException catch (error) {
      _setFailure(error);
    }
  }

  void clearResult() {
    state = const PatientRegistrationState();
  }

  void _setFailure(ApiException error) {
    state = state.copyWith(
      status: RegistrationStatus.failure,
      errorMessage: _formatDiagnosticMessage(error),
    );
  }
}

String _formatDiagnosticMessage(ApiException error) {
  final baseMessage = switch (error) {
    ValidationApiException() => 'Please check the registration details.',
    ClientApiException(statusCode: 401) =>
      'Authentication is required for this request.',
    ClientApiException() => 'The request could not be accepted.',
    NoInternetException() => 'No internet connection is available.',
    ApiTimeoutException() => 'The request timed out. Please try again.',
    ServerApiException() =>
      'The server is unavailable. Please try again later.',
    _ => 'Something unexpected happened. Please try again.',
  };

  final diagnostics = <String>[];

  final dioError = error.details is DioException
      ? error.details as DioException
      : null;

  if (dioError != null) {
    diagnostics.add('type: ${dioError.type.name}');
  }

  final statusCode = error.statusCode ?? dioError?.response?.statusCode;
  if (statusCode != null) {
    diagnostics.add('status: $statusCode');
  }

  final underlying =
      dioError?.error ??
      (error.message != null && error.message != baseMessage
          ? error.message
          : null);
  if (underlying != null) {
    final sanitizedError = _sanitizeString(underlying.toString());
    if (sanitizedError.isNotEmpty) {
      diagnostics.add('error: $sanitizedError');
    }
  }

  final responseData =
      dioError?.response?.data ??
      (error.details is! DioException ? error.details : null);
  if (responseData != null) {
    final sanitizedData = _sanitizeDetail(responseData);
    if (sanitizedData.isNotEmpty) {
      diagnostics.add('detail: $sanitizedData');
    }
  }

  if (diagnostics.isEmpty) {
    return baseMessage;
  }

  return '$baseMessage (${diagnostics.join(', ')})';
}

String _sanitizeString(String text) {
  return text.replaceAll(
    RegExp(
      r'(password|secret|access_token|refresh_token|token|otp)[\s:=]+([^\s,)]+)',
      caseSensitive: false,
    ),
    r'$1: [REDACTED]',
  );
}

String _sanitizeDetail(Object? data) {
  if (data == null) return '';
  if (data is Map) {
    final sanitized = _sanitizeMap(data);
    return sanitized.isEmpty ? '' : sanitized.toString();
  }
  return _sanitizeString(data.toString());
}

Map<String, dynamic> _sanitizeMap(Map data) {
  final result = <String, dynamic>{};
  for (final entry in data.entries) {
    final key = entry.key.toString();
    if (_isSensitiveKey(key)) {
      result[key] = '[REDACTED]';
    } else if (entry.value is Map) {
      result[key] = _sanitizeMap(entry.value as Map);
    } else if (entry.value is List) {
      result[key] = _sanitizeList(entry.value as List);
    } else {
      result[key] = entry.value;
    }
  }
  return result;
}

List<dynamic> _sanitizeList(List list) {
  return list.map((item) {
    if (item is Map) return _sanitizeMap(item);
    if (item is List) return _sanitizeList(item);
    return item;
  }).toList();
}

bool _isSensitiveKey(String key) {
  final lower = key.toLowerCase();
  return lower == 'otp' ||
      lower == 'otp_token' ||
      lower == 'password' ||
      lower == 'secret' ||
      lower == 'access_token' ||
      lower == 'refresh_token' ||
      lower == 'authorization';
}
