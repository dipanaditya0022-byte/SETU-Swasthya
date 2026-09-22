import 'package:dio/dio.dart';

import '../core/network/api_exception.dart';
import '../models/auth_requests.dart';

abstract interface class EmailAuthRemoteDataSource {
  Future<void> sendOtp(EmailOtpRequest request);
  Future<Map<String, dynamic>> verifyOtp(EmailOtpVerifyRequest request);
}

class DioEmailAuthRemoteDataSource implements EmailAuthRemoteDataSource {
  const DioEmailAuthRemoteDataSource(this._dio);
  final Dio _dio;

  @override
  Future<void> sendOtp(EmailOtpRequest request) async {
    try {
      await _dio.post<void>('/auth/otp/request', data: request.toJson());
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }

  @override
  Future<Map<String, dynamic>> verifyOtp(EmailOtpVerifyRequest request) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/otp/verify',
        data: request.toJson(),
      );
      return response.data ?? const {};
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The OTP response was invalid.',
        details: error,
      );
    }
  }
}
