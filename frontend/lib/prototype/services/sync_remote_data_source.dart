import 'package:dio/dio.dart';

import '../core/network/api_exception.dart';
import '../core/storage/sync_operation.dart';

class SyncBatchResult {
  const SyncBatchResult({required this.acknowledged, this.rawResponse});

  final bool acknowledged;
  final Object? rawResponse;
}

abstract interface class SyncRemoteDataSource {
  Future<SyncBatchResult> sync(List<SyncOperation> operations);
}

class DioSyncRemoteDataSource implements SyncRemoteDataSource {
  const DioSyncRemoteDataSource(this._dio);

  final Dio _dio;

  @override
  Future<SyncBatchResult> sync(List<SyncOperation> operations) async {
    try {
      final response = await _dio.post<Object?>(
        '/sync/',
        data: operations.map((operation) => operation.payload).toList(),
      );
      // The OpenAPI response is {}, so it contains no acknowledgement evidence.
      return SyncBatchResult(acknowledged: false, rawResponse: response.data);
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }
}
