import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'core/config/api_config.dart';
import 'models/auth_session.dart';
import 'models/current_user.dart';

class ApiService {
  ApiService({Dio? dio, FlutterSecureStorage? storage})
    : dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: ApiConfig.baseUrl,
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 10),
              headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
              },
            ),
          ),
      storage = storage ?? const FlutterSecureStorage() {
    this.dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await this.storage.read(key: 'access_token');

          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }

          handler.next(options);
        },
      ),
    );
  }

  static final ApiService instance = ApiService();

  final Dio dio;
  final FlutterSecureStorage storage;
  bool _hasAuthenticatedSession = false;

  bool get hasAuthenticatedSession => _hasAuthenticatedSession;

  static String? _extractErrorMessage(dynamic data) {
    if (data is Map) {
      final detail = data['detail'];
      if (detail is String && detail.isNotEmpty) {
        return detail;
      }
      if (detail is Map) {
        final message = detail['detail'] ?? detail['message'];
        if (message is String && message.isNotEmpty) {
          return message;
        }
      }
      final message = data['message'];
      if (message is String && message.isNotEmpty) {
        return message;
      }
    }

    return null;
  }

  Never _throwAuthenticationException(
    DioException error, {
    required String fallbackMessage,
  }) {
    final backendMessage = _extractErrorMessage(error.response?.data);

    if (error.type == DioExceptionType.connectionTimeout ||
        error.type == DioExceptionType.receiveTimeout ||
        error.type == DioExceptionType.sendTimeout ||
        error.type == DioExceptionType.connectionError ||
        error.type == DioExceptionType.unknown) {
      throw const AuthenticationException(
        'Unable to reach the server. Please check your network and try again.',
      );
    }

    throw AuthenticationException(backendMessage ?? fallbackMessage);
  }

  Future<void> requestLoginOtp(String mobile) async {
    try {
      await dio.post<void>(
        '/auth/otp/request',
        data: {'mobile': mobile, 'purpose': 'LOGIN'},
      );
    } on DioException catch (error) {
      _throwAuthenticationException(
        error,
        fallbackMessage: 'Unable to send the OTP. Please try again.',
      );
    }
  }

  Future<AuthSession> verifyLoginOtp({
    required String mobile,
    required String otp,
  }) async {
    try {
      final response = await dio.post<Map<String, dynamic>>(
        '/auth/otp/verify',
        data: {'mobile': mobile, 'otp': otp},
      );
      final otpToken = response.data?['otp_token'];
      if (otpToken is! String || otpToken.isEmpty) {
        throw const AuthenticationException(
          'OTP verification did not return a login token.',
        );
      }

      return await login(mobile: mobile, otpToken: otpToken);
    } on AuthenticationException {
      rethrow;
    } on DioException catch (error) {
      _throwAuthenticationException(
        error,
        fallbackMessage: 'Unable to verify the OTP. Please try again.',
      );
    }
  }

  Future<AuthSession> login({
    String? mobile,
    String? email,
    String? password,
    String? otpToken,
    String? deviceFingerprint,
    String? deviceLabel,
  }) async {
    try {
      final response = await dio.post(
        '/auth/login',
        data: {
          if (mobile != null && mobile.isNotEmpty) 'mobile': mobile,
          if (email != null && email.isNotEmpty) 'email': email,
          if (password != null && password.isNotEmpty) 'password': password,
          if (otpToken != null && otpToken.isNotEmpty) 'otp_token': otpToken,
          if (deviceFingerprint != null && deviceFingerprint.isNotEmpty)
            'device_fingerprint': deviceFingerprint,
          if (deviceLabel != null && deviceLabel.isNotEmpty)
            'device_label': deviceLabel,
        },
      );

      final data = Map<String, dynamic>.from(response.data as Map? ?? const {});

      if (data['mfa_required'] == true) {
        throw MfaRequiredException(
          challengeToken: (data['mfa_challenge_token'] ?? '').toString(),
        );
      }

      final session = AuthSession.fromJson(data);
      if (session.accessToken.isEmpty) {
        throw const AuthenticationException(
          'Sign-in response did not contain an access token.',
        );
      }

      await storage.write(key: 'access_token', value: session.accessToken);

      if (session.refreshToken != null && session.refreshToken!.isNotEmpty) {
        await storage.write(key: 'refresh_token', value: session.refreshToken!);
      }

      _hasAuthenticatedSession = true;
      return session;
    } on AuthenticationException {
      rethrow;
    } on MfaRequiredException {
      rethrow;
    } on DioException catch (error) {
      _throwAuthenticationException(
        error,
        fallbackMessage: 'Unable to sign in. Please try again.',
      );
    }
  }

  Future<Map<String, dynamic>> createPatient({
    required String name,
    required int age,
    required String village,
    required String phone,
    required String facilityId,
    required String clientUuid,
  }) async {
    try {
      final response = await dio.post(
        '/patients/',
        data: {
          'name': name.trim(),
          'age': age,
          'village': village.trim(),
          'phone': phone.trim(),
          'facility_id': facilityId,
          'client_uuid': clientUuid,
        },
      );

      final data = response.data;

      if (data is Map) {
        return Map<String, dynamic>.from(data);
      }

      return {'value': data};
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ??
              'Your session is not authorized to register a patient.',
        );
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ?? 'Unable to register the patient. Please try again.',
      );
    }
  }

  Future<Map<String, dynamic>> createTriage({
    required String patientId,
    required String facilityId,
    required String triageDisposition,
  }) async {
    try {
      final response = await dio.post(
        '/triage/',
        data: {
          'patient_id': patientId,
          'facility_id': facilityId,
          'triage_disposition': triageDisposition,
        },
      );

      final data = response.data;

      if (data is Map) {
        return Map<String, dynamic>.from(data);
      }

      return {'value': data};
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ??
              'You are not authorized to save this triage encounter.',
        );
      }

      if (error.response?.statusCode == 404) {
        throw AuthenticationException(
          backendMessage ?? 'Patient not found for this triage record.',
        );
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ??
            'Unable to save the triage encounter. Please try again.',
      );
    }
  }

  Future<List<Map<String, dynamic>>> getPatients() async {
    try {
      final response = await dio.get('/patients/');
      final data = response.data;

      if (data is! List) {
        return const [];
      }

      return data
          .map((item) => Map<String, dynamic>.from(item as Map? ?? const {}))
          .toList(growable: false);
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ?? 'You are not authorized to view patients.',
        );
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ?? 'Unable to load patients. Please try again.',
      );
    }
  }

  Future<List<Map<String, dynamic>>> getFacilities() async {
    try {
      final response = await dio.get('/facilities/');
      final data = response.data;

      if (data is! List) {
        return const [];
      }

      return data
          .map((item) => Map<String, dynamic>.from(item as Map? ?? const {}))
          .toList(growable: false);
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ?? 'You are not authorized to view facilities.',
        );
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ?? 'Unable to load facilities. Please try again.',
      );
    }
  }

  Future<Map<String, dynamic>> createReferral({
    required String patientId,
    required String fromFacilityId,
    required String destinationFacilityId,
    required String reason,
    required String urgency,
  }) async {
    try {
      final response = await dio.post(
        '/referrals/',
        data: {
          'patient_id': patientId,
          'from_facility_id': fromFacilityId,
          'destination_facility_id': destinationFacilityId,
          'reason': reason.trim(),
          'urgency': urgency,
        },
      );

      final data = response.data;

      if (data is Map) {
        return Map<String, dynamic>.from(data);
      }

      return {'value': data};
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ?? 'You are not authorized to create this referral.',
        );
      }

      if (error.response?.statusCode == 404) {
        throw AuthenticationException(
          backendMessage ?? 'Patient not found for this referral.',
        );
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ?? 'Unable to submit the referral. Please try again.',
      );
    }
  }

  Future<List<Map<String, dynamic>>> getReferrals({
    required String facilityId,
  }) async {
    try {
      final response = await dio.get(
        '/referrals/',
        queryParameters: {'facility_id': facilityId},
      );
      final data = response.data;

      if (data is! List) {
        return const [];
      }

      return data
          .map((item) => Map<String, dynamic>.from(item as Map? ?? const {}))
          .toList(growable: false);
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ?? 'You are not authorized to view referrals.',
        );
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ?? 'Unable to load referrals. Please try again.',
      );
    }
  }

  Future<Map<String, dynamic>> updateReferralStatus({
    required String referralId,
    required String status,
    Map<String, dynamic>? body,
  }) async {
    try {
      final response = await dio.patch(
        '/referrals/$referralId/status',
        queryParameters: {'status': status},
        data: body,
      );
      final data = response.data;

      if (data is Map) {
        return Map<String, dynamic>.from(data);
      }

      return {'value': data};
    } on DioException catch (error) {
      final backendMessage = _extractErrorMessage(error.response?.data);

      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw AuthenticationException(
          backendMessage ?? 'You are not authorized to update this referral.',
        );
      }

      if (error.response?.statusCode == 404) {
        throw AuthenticationException(backendMessage ?? 'Referral not found.');
      }

      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError ||
          error.type == DioExceptionType.unknown) {
        throw const NetworkException(
          'Unable to reach the server. Please check your network and try again.',
        );
      }

      throw AuthenticationException(
        backendMessage ?? 'Unable to update the referral. Please try again.',
      );
    }
  }

  Future<CurrentUser> getCurrentUser() async {
    final response = await dio.get('/auth/me');

    return CurrentUser.fromJson(
      Map<String, dynamic>.from(response.data as Map? ?? const {}),
    );
  }

  Future<AuthSession> refreshToken() async {
    final refreshToken = await storage.read(key: 'refresh_token');

    if (refreshToken == null || refreshToken.isEmpty) {
      throw AuthenticationException('No refresh token available.');
    }

    final response = await dio.post(
      '/auth/token/refresh',
      data: {'refresh_token': refreshToken},
    );

    final session = AuthSession.fromJson(
      Map<String, dynamic>.from(response.data as Map? ?? const {}),
    );

    await storage.write(key: 'access_token', value: session.accessToken);

    if (session.refreshToken != null && session.refreshToken!.isNotEmpty) {
      await storage.write(key: 'refresh_token', value: session.refreshToken!);
    }

    return session;
  }

  Future<void> logoutLocal() async {
    await storage.delete(key: 'access_token');
    await storage.delete(key: 'refresh_token');
    _hasAuthenticatedSession = false;
  }

  Future<void> logout() async {
    try {
      await dio.post<void>('/auth/logout');
    } on DioException {
      // Local credentials must still be removed if the server is unreachable.
    } finally {
      await logoutLocal();
    }
  }
}

class MfaRequiredException implements Exception {
  final String challengeToken;

  const MfaRequiredException({required this.challengeToken});

  @override
  String toString() => 'MFA verification required.';
}

class AuthenticationException implements Exception {
  final String message;

  const AuthenticationException(this.message);

  @override
  String toString() => message;
}

class NetworkException implements Exception {
  final String message;

  const NetworkException([
    this.message =
        'Unable to reach the server. Please check your network and try again.',
  ]);

  @override
  String toString() => message;
}
