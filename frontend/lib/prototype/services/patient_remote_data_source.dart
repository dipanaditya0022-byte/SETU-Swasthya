import 'package:dio/dio.dart';

import '../core/network/api_exception.dart';
import '../models/auth_requests.dart';
import '../models/patient.dart';

abstract interface class PatientRemoteDataSource {
  Future<Patient> createPatient(Patient patient);
  Future<Patient> getPatient(String patientId);
  Future<void> requestRegistrationOtp(OtpRequestBody request);
  Future<Map<String, dynamic>> verifyRegistrationOtp(OtpVerifyBody request);
  Future<void> registerPatient(PatientRegistrationRequest request);
}

class DioPatientRemoteDataSource implements PatientRemoteDataSource {
  const DioPatientRemoteDataSource(this._dio);

  final Dio _dio;

  @override
  Future<Patient> createPatient(Patient patient) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/patients/',
        data: patient.toJson(),
      );
      return Patient.fromJson(response.data!);
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The patient response was invalid.',
        details: error,
      );
    }
  }

  @override
  Future<Patient> getPatient(String patientId) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/patients/$patientId',
      );
      return Patient.fromJson(response.data!);
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The patient response was invalid.',
        details: error,
      );
    }
  }

  @override
  Future<void> requestRegistrationOtp(OtpRequestBody request) async {
    try {
      await _dio.post<void>('/auth/otp/request', data: request.toJson());
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }

  @override
  Future<Map<String, dynamic>> verifyRegistrationOtp(
    OtpVerifyBody request,
  ) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/otp/verify',
        data: request.toJson(),
      );
      return response.data ?? const <String, dynamic>{};
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The OTP verification response was invalid.',
        details: error,
      );
    }
  }

  @override
  Future<void> registerPatient(PatientRegistrationRequest request) async {
    try {
      await _dio.post<void>('/auth/patient/register', data: request.toJson());
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }
}
