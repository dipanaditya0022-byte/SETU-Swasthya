import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/dashboard.dart';
import '../repositories/dashboard_repository.dart';
import '../services/dashboard_remote_data_source.dart';
import 'api_providers.dart';
import 'prototype_session_provider.dart';

final dashboardConfigurationProvider = Provider<DashboardConfiguration>(
  (ref) => const DashboardConfiguration(
    orgUnitId: String.fromEnvironment('ORG_UNIT_ID'),
  ),
);

final dashboardRemoteDataSourceProvider = Provider<DashboardRemoteDataSource>(
  (ref) => DioDashboardRemoteDataSource(ref.watch(apiClientProvider).dio),
);

final dashboardRepositoryProvider = Provider<DashboardRepository>(
  (ref) =>
      DashboardRepositoryImpl(ref.watch(dashboardRemoteDataSourceProvider)),
);

final dashboardProvider = FutureProvider<DashboardResponse>((ref) {
  if (prototypeDemoMode) return const DashboardResponse({});
  final configuration = ref.watch(dashboardConfigurationProvider);
  if (!configuration.isConfigured) {
    throw const DashboardConfigurationException();
  }
  return ref
      .watch(dashboardRepositoryProvider)
      .getFacilityDashboard(configuration.orgUnitId);
});
