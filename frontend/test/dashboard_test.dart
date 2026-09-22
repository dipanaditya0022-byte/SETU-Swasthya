import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/core/network/api_client.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/dashboard.dart';
import 'package:setu_swasthya/prototype/providers/dashboard_providers.dart';
import 'package:setu_swasthya/prototype/providers/sync_providers.dart';
import 'package:setu_swasthya/prototype/repositories/dashboard_repository.dart';
import 'package:setu_swasthya/prototype/screens/dashboard/dashboard_screen.dart';
import 'package:setu_swasthya/prototype/services/dashboard_remote_data_source.dart';

const orgUnitId = '123e4567-e89b-12d3-a456-426614174000';

const populatedDashboard = DashboardResponse({
  'facility': {'id': orgUnitId, 'name': 'PHC Testville', 'type': 'PHC'},
  'date': '2026-09-23',
  'metrics': {
    'open_referrals': {'count': 4},
    'triage_today': {'count': 7},
    'breached': {'numerator': 2, 'denominator': 4, 'rate_pct': 50.0},
    'synced_today': {'numerator': 8, 'denominator': 9, 'rate_pct': 88.9},
  },
  'generated_at': '2026-09-23T05:00:00Z',
});

const zeroDashboard = DashboardResponse({
  'facility': {'id': orgUnitId, 'name': 'PHC Testville', 'type': 'PHC'},
  'date': '2026-09-23',
  'metrics': {
    'open_referrals': {'count': 0},
    'triage_today': {'count': 0},
    'breached': {'numerator': 0, 'denominator': 0, 'rate_pct': 0.0},
    'synced_today': {'numerator': 0, 'denominator': 0, 'rate_pct': 0.0},
  },
  'generated_at': '2026-09-23T05:00:00Z',
});

void main() {
  test('dashboard response parses the exact backend metric shape', () {
    expect(populatedDashboard.facilityName, 'PHC Testville');
    expect(populatedDashboard.openReferrals, 4);
    expect(populatedDashboard.triageCompleted, 7);
    expect(populatedDashboard.breachedReferrals, 2);
    expect(populatedDashboard.syncedRecords, 8);
    expect(populatedDashboard.recordsCreatedToday, 9);
    expect(populatedDashboard.syncRate, 88.9);
    expect(populatedDashboard.registeredPatients, isNull);
    expect(populatedDashboard.arrivedReferrals, isNull);
    expect(populatedDashboard.hasRecords, isTrue);
    expect(zeroDashboard.hasRecords, isFalse);
    expect(dashboardDateValue(DateTime(2026, 9, 16)), '2026-09-16');
  });

  test('dashboard request uses exact path, date, and Bearer token', () async {
    final client = ApiClient(
      baseUrl: 'https://example.test',
      accessTokenProvider: () => 'dashboard-token',
    );
    RequestOptions? request;
    client.dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          request = options;
          handler.resolve(
            Response<Map<String, dynamic>>(
              requestOptions: options,
              statusCode: 200,
              data: populatedDashboard.raw,
            ),
          );
        },
      ),
    );

    final response = await DioDashboardRemoteDataSource(client.dio)
        .getFacilityDashboard(orgUnitId, date: DateTime(2026, 9, 16));

    expect(response.openReferrals, 4);
    expect(request?.method, 'GET');
    expect(request?.path, '/dashboard/facility/$orgUnitId');
    expect(request?.queryParameters['date'], '2026-09-16');
    expect(request?.headers['Authorization'], 'Bearer dashboard-token');
  });

  test('repository delegates dashboard success and errors', () async {
    final source = _FakeDashboardDataSource()..response = populatedDashboard;
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

  test('dashboard provider reaches a terminal timeout error', () async {
    final repository = _FakeDashboardRepository()..neverComplete = true;
    final container = ProviderContainer(
      overrides: [
        dashboardConfigurationProvider.overrideWithValue(
          const DashboardConfiguration(orgUnitId: orgUnitId),
        ),
        dashboardRepositoryProvider.overrideWithValue(repository),
        dashboardRequestTimeoutProvider.overrideWithValue(
          const Duration(milliseconds: 5),
        ),
      ],
    );
    addTearDown(container.dispose);
    final subscription = container.listen(dashboardProvider, (_, _) {});
    addTearDown(subscription.close);

    await expectLater(
      container.read(dashboardProvider.future),
      throwsA(isA<ApiTimeoutException>()),
    );
  });

  testWidgets('live dashboard displays a finite loading skeleton', (
    tester,
  ) async {
    await _pumpDashboard(tester, const AsyncValue<DashboardResponse>.loading());

    expect(find.text('Loading dashboard...'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.byKey(const ValueKey('dashboard-retry-button')), findsNothing);
  });

  testWidgets('backend authentication error shows Retry and can recover', (
    tester,
  ) async {
    final repository = _FakeDashboardRepository()
      ..error = const ClientApiException(statusCode: 403);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          dashboardConfigurationProvider.overrideWithValue(
            const DashboardConfiguration(orgUnitId: orgUnitId),
          ),
          dashboardRepositoryProvider.overrideWithValue(repository),
          connectivityStateProvider.overrideWithValue(
            const AsyncValue.data(true),
          ),
        ],
        child: const MaterialApp(home: DashboardScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.text(
        'Your session is not authorized to view this facility dashboard.',
      ),
      findsOneWidget,
    );
    expect(find.text('Loading dashboard...'), findsNothing);

    repository
      ..error = null
      ..response = populatedDashboard;
    await tester.tap(find.byKey(const ValueKey('dashboard-retry-button')));
    await tester.pumpAndSettle();

    expect(repository.calls, 2);
    expect(find.text('PHC Testville'), findsOneWidget);
    expect(find.text('Dashboard unavailable'), findsNothing);
  });

  testWidgets('populated live dashboard renders backend-supported values', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await _pumpDashboard(tester, const AsyncValue.data(populatedDashboard));

    expect(find.text('PHC Testville'), findsOneWidget);
    expect(find.text('Live'), findsOneWidget);
    expect(find.text('Facility dashboard — live backend data'), findsOneWidget);
    _expectMetric(tester, 'Triage completed today', '7');
    _expectMetric(tester, 'Open referrals', '4');
    _expectMetric(tester, 'Breached referrals', '2');
    _expectMetric(tester, 'Registered patients', '—');
    _expectMetric(tester, 'ARRIVED referrals', '—');
    expect(find.text('Attention required'), findsOneWidget);
    expect(find.text('Triage disposition'), findsOneWidget);
    expect(find.text('Referral status summary'), findsOneWidget);
    expect(
      find.text(
        'Recent activity is not included in the current facility dashboard response.',
      ),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('zero-data live dashboard renders an honest empty state', (
    tester,
  ) async {
    await _pumpDashboard(tester, const AsyncValue.data(zeroDashboard));

    _expectMetric(tester, 'Triage completed today', '0');
    _expectMetric(tester, 'Open referrals', '0');
    _expectMetric(tester, 'Breached referrals', '0');
    expect(find.text('No records for this dashboard period.'), findsOneWidget);
    expect(find.text('Attention required'), findsNothing);
  });
}

Future<void> _pumpDashboard(
  WidgetTester tester,
  AsyncValue<DashboardResponse> dashboard,
) async {
  await tester.pumpWidget(
    ProviderScope(
      key: UniqueKey(),
      overrides: [
        dashboardProvider.overrideWithValue(dashboard),
        connectivityStateProvider.overrideWithValue(
          const AsyncValue.data(true),
        ),
      ],
      child: const MaterialApp(home: DashboardScreen()),
    ),
  );
  await tester.pump();
}

void _expectMetric(WidgetTester tester, String label, String value) {
  final card = find.ancestor(of: find.text(label), matching: find.byType(Card));
  expect(find.descendant(of: card, matching: find.text(value)), findsOneWidget);
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
  DashboardResponse response = zeroDashboard;
  ApiException? error;
  bool neverComplete = false;
  int calls = 0;

  @override
  Future<DashboardResponse> getFacilityDashboard(
    String id, {
    DateTime? date,
  }) async {
    calls++;
    if (neverComplete) return Completer<DashboardResponse>().future;
    if (error != null) throw error!;
    return response;
  }
}
