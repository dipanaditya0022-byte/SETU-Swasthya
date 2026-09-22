import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/triage.dart';
import 'package:setu_swasthya/prototype/providers/triage_providers.dart';
import 'package:setu_swasthya/prototype/repositories/triage_repository.dart';
import 'package:setu_swasthya/prototype/screens/triage/triage_screen.dart';
import 'package:setu_swasthya/prototype/services/triage_remote_data_source.dart';

const patientId = '123e4567-e89b-12d3-a456-426614174000';
const facilityId = '123e4567-e89b-12d3-a456-426614174001';

void main() {
  test('TriageEvaluationRequest serializes exact fields and enum values', () {
    const request = TriageEvaluationRequest(
      patientId: patientId,
      facilityId: facilityId,
      triageDisposition: 'INITIAL_ASSESSMENT',
      referralUrgency: 'WITHIN_24H',
      protocol: 'protocol-v1',
      vitals: {'temperature': 37.2},
      symptoms: ['cough'],
      dangerSigns: ['breathing difficulty'],
      sex: TriageSex.female,
      isPregnant: true,
      gestationalWeeks: 20.5,
      history: {'diabetes': true},
    );

    expect(request.toJson(), {
      'patient_id': patientId,
      'facility_id': facilityId,
      'triage_disposition': 'INITIAL_ASSESSMENT',
      'referral_urgency': 'WITHIN_24H',
      'protocol': 'protocol-v1',
      'vitals': {'temperature': 37.2},
      'symptoms': ['cough'],
      'danger_signs': ['breathing difficulty'],
      'sex': 'FEMALE',
      'is_pregnant': true,
      'gestational_weeks': 20.5,
      'history': {'diabetes': true},
    });
  });

  test('clinical history is sent as additive plain text', () {
    const request = TriageEvaluationRequest(
      patientId: patientId,
      facilityId: facilityId,
      triageDisposition: 'ASSESS',
      clinicalHistory: 'Synthetic prior condition',
    );
    expect(request.toJson()['clinical_history'], 'Synthetic prior condition');
    expect(request.toJson()['history'], isEmpty);
  });

  test('TriageEvaluationResponse deserializes the authoritative decision', () {
    final response = TriageEvaluationResponse.fromJson(_responseJson());

    expect(response.id, '123e4567-e89b-12d3-a456-426614174002');
    expect(response.referralUrgency, isNull);
    expect(response.decision.disposition, TriageDisposition.refer);
    expect(response.decision.urgency, TriageUrgency.within24h);
    expect(response.decision.redFlags, ['red_flag']);
    expect(response.decision.engine, TriageEngine.rule);
    expect(response.decision.insufficientData, isFalse);
  });

  test('remote datasource uses POST /triage/ exactly', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    RequestOptions? captured;
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          captured = options;
          handler.resolve(
            Response<Map<String, dynamic>>(
              requestOptions: options,
              statusCode: 200,
              data: _responseJson(),
            ),
          );
        },
      ),
    );

    await DioTriageRemoteDataSource(dio).createTriage(_request());

    expect(captured?.method, 'POST');
    expect(captured?.path, '/triage/');
    expect(captured?.data['patient_id'], patientId);
  });

  test(
    'repository delegates successful submission and propagates API errors',
    () async {
      final source = _FakeTriageDataSource()..response = _response();
      final repository = TriageRepositoryImpl(source);

      expect(await repository.createTriage(_request()), same(source.response));

      source.error = const ServerApiException(statusCode: 500);
      await expectLater(
        repository.createTriage(_request()),
        throwsA(isA<ServerApiException>()),
      );
    },
  );

  test('controller exposes initial, loading, success, error, and duplicate protection', () async {
    final source = _FakeTriageRepository()..response = _response();
    final container = ProviderContainer(
      overrides: [triageRepositoryProvider.overrideWithValue(source)],
    );
    addTearDown(container.dispose);
    final controller = container.read(triageControllerProvider.notifier);

    expect(container.read(triageControllerProvider).status, TriageStatus.idle);
    final first = controller.submit(_request());
    expect(
      container.read(triageControllerProvider).status,
      TriageStatus.submitting,
    );
    final second = controller.submit(_request());
    await Future.wait([first, second]);
    expect(source.calls, 1);
    expect(
      container.read(triageControllerProvider).status,
      TriageStatus.success,
    );

    source.error = const NoInternetException();
    await controller.submit(_request());
    expect(container.read(triageControllerProvider).status, TriageStatus.error);
    expect(
      container.read(triageControllerProvider).errorMessage,
      contains('Unable to connect'),
    );
  });

  testWidgets('triage validates required fields and renders backend result', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(800, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final repository = _FakeTriageRepository()..response = _response();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [triageRepositoryProvider.overrideWithValue(repository)],
        child: const MaterialApp(home: TriageScreen()),
      ),
    );

    final submit = find.byKey(const ValueKey('triage-submit-button'));
    await Scrollable.ensureVisible(tester.element(submit), alignment: 0.5);
    await tester.pump();
    await tester.tap(submit);
    await tester.pump();
    expect(find.text('Please enter Patient UUID'), findsOneWidget);
    expect(find.text('Please enter Facility UUID'), findsOneWidget);
    expect(find.text('Please enter Triage disposition'), findsOneWidget);

    await tester.enterText(
      find.byKey(const ValueKey('triage-patient-id')),
      patientId,
    );
    await tester.enterText(
      find.byKey(const ValueKey('triage-facility-id')),
      facilityId,
    );
    await tester.enterText(
      find.byKey(const ValueKey('triage-disposition')),
      'ASSESS',
    );
    await tester.enterText(
      find.byKey(const ValueKey('triage-temperature')),
      'invalid',
    );
    await Scrollable.ensureVisible(tester.element(submit), alignment: 0.5);
    await tester.pump();
    await tester.tap(submit);
    await tester.pump();
    expect(find.text('Enter a number from 25 to 45'), findsOneWidget);
    expect(repository.calls, 0);
    await tester.enterText(
      find.byKey(const ValueKey('triage-temperature')),
      '39.2',
    );
    await tester.enterText(find.byKey(const ValueKey('triage-pulse')), '96');
    await tester.enterText(find.byKey(const ValueKey('triage-spo2')), '97');
    await tester.enterText(
      find.byKey(const ValueKey('triage-respiratory-rate')),
      '20',
    );
    await tester.enterText(
      find.byKey(const ValueKey('triage-systolic-bp')),
      '120',
    );
    await tester.enterText(
      find.byKey(const ValueKey('triage-diastolic-bp')),
      '80',
    );
    await tester.enterText(
      find.byKey(const ValueKey('triage-clinical-history')),
      'Synthetic history',
    );
    await Scrollable.ensureVisible(tester.element(submit), alignment: 0.5);
    await tester.pump();
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('triage-result')), findsOneWidget);
    expect(find.text('Backend triage decision'), findsOneWidget);
    expect(repository.lastRequest?.vitals, {
      'temperature': 39.2,
      'pulse': 96,
      'spo2': 97,
      'respiratory_rate': 20,
      'systolic_bp': 120,
      'diastolic_bp': 80,
    });
    expect(repository.lastRequest?.clinicalHistory, 'Synthetic history');
  });
}

TriageEvaluationRequest _request() => const TriageEvaluationRequest(
  patientId: patientId,
  facilityId: facilityId,
  triageDisposition: 'ASSESS',
);

TriageEvaluationResponse _response() =>
    TriageEvaluationResponse.fromJson(_responseJson());

Map<String, dynamic> _responseJson() => {
  'id': '123e4567-e89b-12d3-a456-426614174002',
  'patient_id': patientId,
  'facility_id': facilityId,
  'triage_disposition': 'ASSESS',
  'referral_urgency': null,
  'created_at': '2026-09-16T10:00:00Z',
  'created_by_user_id': null,
  'org_unit_id': null,
  'decision': {
    'disposition': 'REFER',
    'urgency': 'WITHIN_24H',
    'reason': 'Needs clinical review',
    'red_flags': ['red_flag'],
    'protocol_version': 'v1',
    'insufficient_data': false,
    'missing_fields': <String>[],
    'engine': 'rule',
    'evaluated_at': '2026-09-16T10:00:00Z',
  },
};

class _FakeTriageDataSource implements TriageRemoteDataSource {
  TriageEvaluationResponse? response;
  ApiException? error;

  @override
  Future<TriageEvaluationResponse> createTriage(
    TriageEvaluationRequest request,
  ) async {
    if (error != null) throw error!;
    return response!;
  }
}

class _FakeTriageRepository implements TriageRepository {
  TriageEvaluationResponse? response;
  ApiException? error;
  int calls = 0;
  TriageEvaluationRequest? lastRequest;
  final Completer<void> _gate = Completer<void>();

  @override
  Future<TriageEvaluationResponse> createTriage(
    TriageEvaluationRequest request,
  ) async {
    calls++;
    lastRequest = request;
    if (calls == 1 && !_gate.isCompleted) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    if (error != null) throw error!;
    return response!;
  }
}
