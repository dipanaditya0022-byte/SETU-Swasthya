import 'package:dio/dio.dart';

import '../core/network/api_exception.dart';
import '../models/dashboard.dart';

abstract interface class DashboardRemoteDataSource {
  Future<DashboardResponse> getFacilityDashboard(
    String orgUnitId, {
    DateTime? date,
  });
}

class DioDashboardRemoteDataSource implements DashboardRemoteDataSource {
  const DioDashboardRemoteDataSource(this._dio);

  final Dio _dio;

  @override
  Future<DashboardResponse> getFacilityDashboard(
    String orgUnitId, {
    DateTime? date,
  }) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/dashboard/facility/$orgUnitId',
        queryParameters: date == null
            ? null
            : <String, dynamic>{'date': dashboardDateValue(date)},
      );
      return DashboardResponse.fromJson(response.data ?? const {});
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The dashboard response was invalid.',
        details: error,
      );
    }
  }
}
