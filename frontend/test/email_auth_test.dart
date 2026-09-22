import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/core/network/api_client.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/auth_requests.dart';
import 'package:setu_swasthya/prototype/providers/email_auth_provider.dart';
import 'package:setu_swasthya/prototype/repositories/email_auth_repository.dart';
import 'package:setu_swasthya/prototype/services/email_auth_remote_data_source.dart';

void main() {
  test('email OTP models send only the required email contract fields', () {
    expect(const EmailOtpRequest('user@gmail.com').toJson(), {
      'email': 'user@gmail.com',
    });
    expect(const EmailOtpVerifyRequest('user@gmail.com', '123456').toJson(), {
      'email': 'user@gmail.com',
      'otp': '123456',
    });
  });

  test(
    'email OTP repository sends exact paths and extracts access token',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final requests = <RequestOptions>[];
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            requests.add(options);
            handler.resolve(
              Response<Map<String, dynamic>>(
                requestOptions: options,
                statusCode: 200,
                data: options.path.endsWith('verify')
                    ? {'access_token': 'real-token'}
                    : {},
              ),
            );
          },
        ),
      );
      final repository = EmailAuthRepositoryImpl(
        DioEmailAuthRemoteDataSource(dio),
      );

      await repository.sendOtp('user@gmail.com');
      expect(
        await repository.verifyOtp('user@gmail.com', '123456'),
        'real-token',
      );
      expect(requests.map((request) => request.path), [
        '/auth/otp/request',
        '/auth/otp/verify',
      ]);
      expect(requests[0].data, {'email': 'user@gmail.com'});
      expect(requests[1].data, {'email': 'user@gmail.com', 'otp': '123456'});
    },
  );

  test(
    'controller gates access on verified token and handles expired OTP',
    () async {
      final repository = _FakeEmailAuthRepository();
      final container = ProviderContainer(
        overrides: [
          emailAuthBackendConfiguredProvider.overrideWithValue(true),
          emailAuthRepositoryProvider.overrideWithValue(repository),
        ],
      );
      addTearDown(container.dispose);
      final controller = container.read(emailAuthProvider.notifier);

      await controller.sendOtp('user@gmail.com');
      expect(container.read(emailAuthProvider).status, EmailAuthStatus.sent);
      expect(container.read(emailAuthProvider).accessToken, isNull);

      repository.error = const ClientApiException(statusCode: 410);
      await controller.verifyOtp('111111');
      expect(
        container.read(emailAuthProvider).errorMessage,
        contains('expired'),
      );
      expect(container.read(emailAuthProvider).accessToken, isNull);

      repository.error = null;
      await controller.verifyOtp('123456');
      expect(
        container.read(emailAuthProvider).status,
        EmailAuthStatus.authenticated,
      );
      expect(container.read(emailAuthProvider).accessToken, 'real-token');
    },
  );

  test('controller gives specific OTP failure messages', () async {
    final repository = _FakeEmailAuthRepository();
    final container = ProviderContainer(
      overrides: [
        emailAuthBackendConfiguredProvider.overrideWithValue(true),
        emailAuthRepositoryProvider.overrideWithValue(repository),
      ],
    );
    addTearDown(container.dispose);
    final controller = container.read(emailAuthProvider.notifier);
    await controller.sendOtp('user@gmail.com');

    for (final scenario in <(ApiException, String)>[
      (const ClientApiException(statusCode: 403), 'Invalid email or OTP'),
      (const ClientApiException(statusCode: 429), 'Too many attempts'),
      (const ApiTimeoutException(), 'timed out'),
      (const ServerApiException(statusCode: 503), 'unavailable'),
    ]) {
      repository.error = scenario.$1;
      await controller.verifyOtp('111111');
      expect(
        container.read(emailAuthProvider).errorMessage,
        contains(scenario.$2),
      );
    }
    expect(container.read(emailAuthProvider).accessToken, isNull);
  });

  test('ApiClient adds Bearer token only when supplied', () async {
    String? captured;
    final client = ApiClient(
      baseUrl: 'https://example.test',
      accessTokenProvider: () => 'real-token',
    );
    client.dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          captured = options.headers['Authorization'] as String?;
          handler.resolve(Response(requestOptions: options, statusCode: 200));
        },
      ),
    );
    await client.dio.get('/patients/one');
    expect(captured, 'Bearer real-token');
  });
}

class _FakeEmailAuthRepository implements EmailAuthRepository {
  ApiException? error;

  @override
  Future<void> sendOtp(String email) async {
    if (error != null) throw error!;
  }

  @override
  Future<String> verifyOtp(String email, String otp) async {
    if (error != null) throw error!;
    return 'real-token';
  }
}
