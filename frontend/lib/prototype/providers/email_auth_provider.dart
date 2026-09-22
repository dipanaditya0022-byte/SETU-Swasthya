import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../repositories/email_auth_repository.dart';
import '../services/email_auth_remote_data_source.dart';
import 'api_providers.dart';
import 'prototype_session_provider.dart';

enum EmailAuthStatus { idle, sending, sent, verifying, authenticated, error }

class EmailAuthState {
  const EmailAuthState({
    this.status = EmailAuthStatus.idle,
    this.email,
    this.accessToken,
    this.errorMessage,
    this.otpSent = false,
  });

  final EmailAuthStatus status;
  final String? email;
  final String? accessToken;
  final String? errorMessage;
  final bool otpSent;

  bool get isBusy =>
      status == EmailAuthStatus.sending || status == EmailAuthStatus.verifying;
}

final emailAuthRepositoryProvider = Provider<EmailAuthRepository>((ref) {
  return EmailAuthRepositoryImpl(
    DioEmailAuthRemoteDataSource(ref.watch(apiClientProvider).dio),
  );
});

final emailAuthBackendConfiguredProvider = Provider<bool>(
  (ref) => prototypeApiBaseUrl.isNotEmpty,
);

final emailAuthProvider = NotifierProvider<EmailAuthController, EmailAuthState>(
  EmailAuthController.new,
);

class EmailAuthController extends Notifier<EmailAuthState> {
  @override
  EmailAuthState build() => const EmailAuthState();

  Future<void> sendOtp(String email) async {
    if (state.isBusy) return;
    state = EmailAuthState(status: EmailAuthStatus.sending, email: email);
    if (prototypeDemoMode) {
      state = EmailAuthState(
        status: EmailAuthStatus.sent,
        email: email,
        otpSent: true,
      );
      return;
    }
    if (!ref.read(emailAuthBackendConfiguredProvider)) {
      state = EmailAuthState(
        status: EmailAuthStatus.error,
        email: email,
        errorMessage: 'API_BASE_URL is required for email OTP.',
      );
      return;
    }
    try {
      await ref.read(emailAuthRepositoryProvider).sendOtp(email);
      state = EmailAuthState(
        status: EmailAuthStatus.sent,
        email: email,
        otpSent: true,
      );
    } on ApiException catch (error) {
      state = EmailAuthState(
        status: EmailAuthStatus.error,
        email: email,
        errorMessage: _message(error),
      );
    }
  }

  Future<void> verifyOtp(String otp) async {
    if (state.isBusy || state.email == null || !state.otpSent) return;
    final email = state.email!;
    state = EmailAuthState(
      status: EmailAuthStatus.verifying,
      email: email,
      otpSent: true,
    );
    if (prototypeDemoMode) {
      state = otp == '123456'
          ? EmailAuthState(
              status: EmailAuthStatus.authenticated,
              email: email,
              accessToken: 'demo-session-token',
              otpSent: true,
            )
          : EmailAuthState(
              status: EmailAuthStatus.error,
              email: email,
              errorMessage: 'Wrong demo OTP. Use 123456.',
              otpSent: true,
            );
      return;
    }
    try {
      final token = await ref
          .read(emailAuthRepositoryProvider)
          .verifyOtp(email, otp);
      state = EmailAuthState(
        status: EmailAuthStatus.authenticated,
        email: email,
        accessToken: token,
        otpSent: true,
      );
    } on ApiException catch (error) {
      state = EmailAuthState(
        status: EmailAuthStatus.error,
        email: email,
        errorMessage: _message(error),
        otpSent: true,
      );
    }
  }

  void changeEmail() => state = const EmailAuthState();

  String _message(ApiException error) {
    final detail = error.details?.toString().toLowerCase() ?? '';
    if (detail.contains('expired')) return 'OTP expired. Request a new code.';
    return switch (error) {
      ClientApiException(statusCode: 429) =>
        'Too many attempts. Wait before requesting another OTP.',
      ClientApiException(statusCode: 410) => 'OTP expired. Request a new code.',
      ClientApiException(statusCode: 400) ||
      ClientApiException(statusCode: 401) ||
      ClientApiException(statusCode: 403) ||
      ClientApiException(statusCode: 422) ||
      ValidationApiException() =>
        'Invalid email or OTP. Check the details and try again.',
      ApiTimeoutException() => 'Request timed out. Try again.',
      ServerApiException() =>
        'Email OTP service is unavailable. Try again later.',
      NoInternetException() => 'No internet connection. Check your network.',
      UnexpectedApiException(message: final message?) => message,
      _ => 'Could not complete email OTP. Try again.',
    };
  }
}
