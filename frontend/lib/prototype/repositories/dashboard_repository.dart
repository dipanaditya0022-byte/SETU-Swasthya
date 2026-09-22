import '../models/dashboard.dart';
import '../services/dashboard_remote_data_source.dart';

abstract interface class DashboardRepository {
  Future<DashboardResponse> getFacilityDashboard(
    String orgUnitId, {
    DateTime? date,
  });
}

class DashboardRepositoryImpl implements DashboardRepository {
  const DashboardRepositoryImpl(this._remoteDataSource);

  final DashboardRemoteDataSource _remoteDataSource;

  @override
  Future<DashboardResponse> getFacilityDashboard(
    String orgUnitId, {
    DateTime? date,
  }) => _remoteDataSource.getFacilityDashboard(orgUnitId, date: date);
}
