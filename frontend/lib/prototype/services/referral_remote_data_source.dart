import 'package:dio/dio.dart';

import '../core/network/api_exception.dart';
import '../models/referral.dart';

abstract interface class ReferralRemoteDataSource {
  Future<Referral> createReferral(Referral referral);
  Future<void> updateReferralStatus(
    String referralId,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  );
}

class DioReferralRemoteDataSource implements ReferralRemoteDataSource {
  const DioReferralRemoteDataSource(this._dio);

  final Dio _dio;

  @override
  Future<Referral> createReferral(Referral referral) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/referrals/',
        data: referral.toJson(),
      );
      return Referral.fromJson(response.data!);
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on Object catch (error) {
      throw UnexpectedApiException(
        message: 'The referral response was invalid.',
        details: error,
      );
    }
  }

  @override
  Future<void> updateReferralStatus(
    String referralId,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  ) async {
    try {
      await _dio.patch<void>(
        '/referrals/$referralId/status',
        queryParameters: {'status': referralStateValue(status)},
        data: body?.toJson(),
      );
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }
}
