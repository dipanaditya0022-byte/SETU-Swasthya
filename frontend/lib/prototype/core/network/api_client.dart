import 'package:dio/dio.dart';

typedef AccessTokenProvider = String? Function();

class ApiClient {
  ApiClient({
    String? baseUrl,
    AccessTokenProvider? accessTokenProvider,
    Dio? dio,
  }) : dio = dio ?? _buildDio(baseUrl, accessTokenProvider);

  final Dio dio;

  static Dio _buildDio(
    String? baseUrl,
    AccessTokenProvider? accessTokenProvider,
  ) {
    final configuredBaseUrl =
        baseUrl ?? const String.fromEnvironment('API_BASE_URL');
    final dio = Dio(
      BaseOptions(
        baseUrl: configuredBaseUrl,
        connectTimeout: const Duration(seconds: 10),
        sendTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 20),
        contentType: Headers.jsonContentType,
        responseType: ResponseType.json,
      ),
    );

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = accessTokenProvider?.call();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
      ),
    );
    return dio;
  }
}
