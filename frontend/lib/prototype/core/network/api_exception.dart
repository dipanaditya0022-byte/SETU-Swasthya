import 'package:dio/dio.dart';

sealed class ApiException implements Exception {
  const ApiException({this.message, this.statusCode, this.details});

  final String? message;
  final int? statusCode;
  final Object? details;

  @override
  String toString() => message ?? runtimeType.toString();

  factory ApiException.fromDio(DioException error) {
    final statusCode = error.response?.statusCode;
    if (error.type == DioExceptionType.connectionError) {
      return NoInternetException(message: error.message, details: error);
    }
    if (error.type == DioExceptionType.connectionTimeout ||
        error.type == DioExceptionType.sendTimeout ||
        error.type == DioExceptionType.receiveTimeout) {
      return ApiTimeoutException(message: error.message, details: error);
    }
    if (statusCode != null && statusCode >= 400 && statusCode < 500) {
      if (statusCode == 422) {
        return ValidationApiException(
          message: 'The API rejected the request.',
          statusCode: statusCode,
          details: error.response?.data,
        );
      }
      return ClientApiException(
        message: 'The API request was rejected.',
        statusCode: statusCode,
        details: error.response?.data,
      );
    }
    if (statusCode != null && statusCode >= 500) {
      return ServerApiException(
        message: 'The API server failed to process the request.',
        statusCode: statusCode,
        details: error.response?.data,
      );
    }
    return UnexpectedApiException(
      message: error.message ?? error.error?.toString(),
      statusCode: statusCode,
      details: error,
    );
  }
}

final class NoInternetException extends ApiException {
  const NoInternetException({super.message, super.details});
}

final class ApiTimeoutException extends ApiException {
  const ApiTimeoutException({super.message, super.details});
}

final class ClientApiException extends ApiException {
  const ClientApiException({super.message, super.statusCode, super.details});
}

final class ValidationApiException extends ApiException {
  const ValidationApiException({
    super.message,
    super.statusCode,
    super.details,
  });
}

final class ServerApiException extends ApiException {
  const ServerApiException({super.message, super.statusCode, super.details});
}

final class UnexpectedApiException extends ApiException {
  const UnexpectedApiException({
    super.message,
    super.statusCode,
    super.details,
  });
}

final class InvalidPatientIdException extends ApiException {
  const InvalidPatientIdException({
    super.message = 'The patient ID is invalid.',
  });
}

final class DashboardConfigurationException extends ApiException {
  const DashboardConfigurationException({
    super.message = 'The dashboard org unit is not configured.',
  });
}
