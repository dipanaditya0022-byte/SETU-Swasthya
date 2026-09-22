import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  test(
    'mobile OTP login exchanges otp_token, stores tokens, and injects Bearer',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final requests = <RequestOptions>[];
      final service = ApiService(dio: dio);
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            requests.add(options);
            final data = switch (options.path) {
              '/auth/otp/request' => <String, dynamic>{
                'otp_sent': true,
                'expires_in': 300,
              },
              '/auth/otp/verify' => <String, dynamic>{
                'otp_token': 'verified-otp-token',
                'expires_in': 300,
              },
              '/auth/login' => <String, dynamic>{
                'access_token': 'access-token',
                'refresh_token': 'refresh-token',
                'token_type': 'bearer',
                'expires_in': 3600,
              },
              _ => <String, dynamic>{},
            };
            handler.resolve(
              Response<Map<String, dynamic>>(
                requestOptions: options,
                statusCode: 200,
                data: data,
              ),
            );
          },
        ),
      );

      await service.requestLoginOtp('+919000000106');
      final session = await service.verifyLoginOtp(
        mobile: '+919000000106',
        otp: '654321',
      );
      await dio.get<Map<String, dynamic>>('/dashboard/facility/facility-id');

      expect(session.accessToken, 'access-token');
      expect(await service.storage.read(key: 'access_token'), 'access-token');
      expect(await service.storage.read(key: 'refresh_token'), 'refresh-token');
      expect(requests.take(3).map((request) => request.path), [
        '/auth/otp/request',
        '/auth/otp/verify',
        '/auth/login',
      ]);
      expect(requests[0].data, {'mobile': '+919000000106', 'purpose': 'LOGIN'});
      expect(requests[1].data, {'mobile': '+919000000106', 'otp': '654321'});
      expect(requests[2].data, {
        'mobile': '+919000000106',
        'otp_token': 'verified-otp-token',
      });
      expect(requests[3].headers['Authorization'], 'Bearer access-token');
    },
  );

  test(
    'logout clears secure tokens even when server revocation fails',
    () async {
      FlutterSecureStorage.setMockInitialValues({
        'access_token': 'access-token',
        'refresh_token': 'refresh-token',
      });
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final service = ApiService(dio: dio);
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) => handler.reject(
            DioException.connectionError(
              requestOptions: options,
              reason: 'offline',
            ),
          ),
        ),
      );

      await service.logout();

      expect(await service.storage.read(key: 'access_token'), isNull);
      expect(await service.storage.read(key: 'refresh_token'), isNull);
    },
  );
}
