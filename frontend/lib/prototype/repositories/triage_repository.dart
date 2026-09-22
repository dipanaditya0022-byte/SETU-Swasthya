import '../models/triage.dart';
import '../services/triage_remote_data_source.dart';

abstract interface class TriageRepository {
  Future<TriageEvaluationResponse> createTriage(
    TriageEvaluationRequest request,
  );
}

class TriageRepositoryImpl implements TriageRepository {
  const TriageRepositoryImpl(this._remoteDataSource);

  final TriageRemoteDataSource _remoteDataSource;

  @override
  Future<TriageEvaluationResponse> createTriage(
    TriageEvaluationRequest request,
  ) => _remoteDataSource.createTriage(request);
}
