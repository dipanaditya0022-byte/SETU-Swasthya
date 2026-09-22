import 'package:dio/dio.dart';

import '../core/network/api_exception.dart';
import '../models/triage.dart';

abstract interface class TriageRemoteDataSource {
  Future<TriageEvaluationResponse> createTriage(
    TriageEvaluationRequest request,
  );
}

class DioTriageRemoteDataSource implements TriageRemoteDataSource {
  const DioTriageRemoteDataSource(this._dio);

  final Dio _dio;

  @override
  Future<TriageEvaluationResponse> createTriage(
    TriageEvaluationRequest request,
  ) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/triage/',
        data: request.toJson(),
      );
      return TriageEvaluationResponse.fromJson(response.data!);
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The triage response was invalid.',
        details: error,
      );
    }
  }
}
