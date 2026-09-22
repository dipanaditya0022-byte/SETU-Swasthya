import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/dashboard.dart';
import 'package:setu_swasthya/prototype/providers/dashboard_providers.dart';
import 'package:setu_swasthya/prototype/repositories/dashboard_repository.dart';
import 'package:setu_swasthya/prototype/screens/dashboard/dashboard_screen.dart';
import 'package:setu_swasthya/prototype/services/dashboard_remote_data_source.dart';

const orgUnitId = '123e4567-e89b-12d3-a456-426614174000';

void main() {
  test('dashboard response preserves the contract empty object', () {
    const response = DashboardResponse({});

    expect(response.raw, isEmpty);
    expect(dashboardDateValue(DateTime(2026, 9, 16)), '2026-09-16');
  });

  test(
    'datasource uses exact dashboard path and optional date query',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      RequestOptions? request;
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            request = options;
            handler.resolve(
              Response<Map<String, dynamic>>(
                requestOptions: options,
                statusCode: 200,
                data: const {},
              ),
            );
          },
        ),
      );

      final response = await DioDashboardRemoteDataSource(dio)
          .getFacilityDashboard(orgUnitId, date: DateTime(2026, 9, 16));

      expect(response.raw, isEmpty);
      expect(request?.method, 'GET');
      expect(request?.path, '/dashboard/facility/$orgUnitId');
      expect(request?.queryParameters['date'], '2026-09-16');
    },
  );

  test('repository delegates dashboard success and errors', () async {
    final source = _FakeDashboardDataSource()
      ..response = const DashboardResponse({});
    final repository = DashboardRepositoryImpl(source);

    expect(
      await repository.getFacilityDashboard(orgUnitId),
      same(source.response),
    );

    source.error = const ServerApiException(statusCode: 500);
    await expectLater(
      repository.getFacilityDashboard(orgUnitId),
      throwsA(isA<ServerApiException>()),
    );
  });

  test(
    'dashboard provider exposes configuration and repository errors',
    () async {
      final repository = _FakeDashboardRepository();
      final container = ProviderContainer(
        overrides: [
          dashboardConfigurationProvider.overrideWithValue(
            const DashboardConfiguration(orgUnitId: orgUnitId),
          ),
          dashboardRepositoryProvider.overrideWithValue(repository),
        ],
      );
      addTearDown(container.dispose);

      expect(
        await container.read(dashboardProvider.future),
        isA<DashboardResponse>(),
      );
      repository.error = const NoInternetException();
      final failingContainer = ProviderContainer(
        overrides: [
          dashboardConfigurationProvider.overrideWithValue(
            const DashboardConfiguration(orgUnitId: orgUnitId),
          ),
          dashboardRepositoryProvider.overrideWithValue(repository),
        ],
      );
      addTearDown(failingContainer.dispose);
      final errorState = Completer<AsyncValue<DashboardResponse>>();
      final subscription = failingContainer.listen(dashboardProvider, (
        _,
        next,
      ) {
        if (next.hasError && !errorState.isCompleted) {
          errorState.complete(next);
        }
      }, fireImmediately: true);
      expect((await errorState.future).error, isA<NoInternetException>());
      subscription.close();
    },
  );

  testWidgets(
    'dashboard renders loading, success empty, error, and missing configuration',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          key: UniqueKey(),
          overrides: [
            dashboardProvider.overrideWithValue(
              const AsyncValue<DashboardResponse>.loading(),
            ),
          ],
          child: const MaterialApp(home: DashboardScreen()),
        ),
      );
      expect(find.text('Loading dashboard...'), findsOneWidget);

      await tester.pumpWidget(
        ProviderScope(
          key: UniqueKey(),
          overrides: [
            dashboardProvider.overrideWithValue(
              const AsyncValue.data(DashboardResponse({})),
            ),
          ],
          child: const MaterialApp(home: DashboardScreen()),
        ),
      );
      await tester.pump();
      expect(
        find.text(
          'No dashboard fields are defined by the current API contract.',
        ),
        findsOneWidget,
      );

      await tester.pumpWidget(
        ProviderScope(
          key: UniqueKey(),
          overrides: [
            dashboardProvider.overrideWithValue(
              AsyncValue.error(
                const ServerApiException(statusCode: 500),
                StackTrace.current,
              ),
            ),
          ],
          child: const MaterialApp(home: DashboardScreen()),
        ),
      );
      await tester.pump();
      expect(
        find.text('Something went wrong on the server. Please try again.'),
        findsOneWidget,
      );

      await tester.pumpWidget(
        ProviderScope(
          key: UniqueKey(),
          overrides: [
            dashboardProvider.overrideWithValue(
              AsyncValue.error(
                const DashboardConfigurationException(),
                StackTrace.current,
              ),
            ),
          ],
          child: const MaterialApp(home: DashboardScreen()),
        ),
      );
      await tester.pump();
      expect(
        find.text('Dashboard org unit ID is not configured.'),
        findsOneWidget,
      );
    },
  );
}

class _FakeDashboardDataSource implements DashboardRemoteDataSource {
  DashboardResponse? response;
  ApiException? error;

  @override
  Future<DashboardResponse> getFacilityDashboard(
    String id, {
    DateTime? date,
  }) async {
    if (error != null) throw error!;
    return response!;
  }
}

class _FakeDashboardRepository implements DashboardRepository {
  ApiException? error;

  @override
  Future<DashboardResponse> getFacilityDashboard(
    String id, {
    DateTime? date,
  }) async {
    if (error != null) throw error!;
    return const DashboardResponse({});
  }
}
