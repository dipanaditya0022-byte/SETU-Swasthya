import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/referral.dart';
import 'package:setu_swasthya/prototype/models/patient.dart';
import 'package:setu_swasthya/prototype/models/demo_triage.dart';
import 'package:setu_swasthya/prototype/models/triage.dart';
import 'package:setu_swasthya/prototype/providers/referral_providers.dart';
import 'package:setu_swasthya/prototype/providers/prototype_session_provider.dart';
import 'package:setu_swasthya/prototype/repositories/referral_repository.dart';
import 'package:setu_swasthya/prototype/screens/referral/referral_screen.dart';
import 'package:setu_swasthya/prototype/services/referral_remote_data_source.dart';

const patientId = '123e4567-e89b-12d3-a456-426614174000';
const fromFacilityId = '123e4567-e89b-12d3-a456-426614174001';
const destinationFacilityId = '123e4567-e89b-12d3-a456-426614174002';
const referralId = '123e4567-e89b-12d3-a456-426614174003';

void main() {
  test('Referral serializes and deserializes nullable fields and state', () {
    final referral = Referral(
      id: referralId,
      patientId: patientId,
      fromFacilityId: fromFacilityId,
      destinationFacilityId: destinationFacilityId,
      reason: 'Specialist review',
      urgency: 'URGENT',
      status: ReferralState.slotBooked,
      receivingUnit: null,
      dueDate: DateTime.parse('2026-09-20T10:00:00Z'),
    );

    final decoded = Referral.fromJson(referral.toJson());

    expect(decoded.id, referralId);
    expect(decoded.status, ReferralState.slotBooked);
    expect(decoded.receivingUnit, isNull);
    expect(decoded.dueDate, DateTime.parse('2026-09-20T10:00:00Z'));
    expect(
      referralStateValue(ReferralState.transportArranged),
      'TRANSPORT_ARRANGED',
    );
  });

  test('status update body serializes refusal enum and nullable fields', () {
    const body = ReferralStatusUpdateBody(
      refusalReason: RefusalReason.distance,
    );

    expect(body.toJson()['refusal_reason'], 'DISTANCE');
    expect(body.toJson()['slot_datetime'], isNull);
    expect(referralStateFromValue('CANCELLED'), ReferralState.cancelled);
  });

  test(
    'datasource uses exact referral POST and status PATCH contracts',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final requests = <RequestOptions>[];
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            requests.add(options);
            handler.resolve(
              Response<Map<String, dynamic>>(
                requestOptions: options,
                statusCode: 200,
                data: _referralJson(),
              ),
            );
          },
        ),
      );
      final source = DioReferralRemoteDataSource(dio);

      await source.createReferral(_referral());
      await source.updateReferralStatus(
        referralId,
        ReferralState.arrived,
        const ReferralStatusUpdateBody(reason: 'Arrived at facility'),
      );

      expect(requests[0].method, 'POST');
      expect(requests[0].path, '/referrals/');
      expect(requests[1].method, 'PATCH');
      expect(requests[1].path, '/referrals/$referralId/status');
      expect(requests[1].queryParameters['status'], 'ARRIVED');
      expect(requests[1].data['reason'], 'Arrived at facility');
    },
  );

  test('repository delegates create and status update', () async {
    final source = _FakeReferralDataSource()..response = _referral();
    final repository = ReferralRepositoryImpl(source);

    expect(await repository.createReferral(_referral()), same(source.response));
    await repository.updateReferralStatus(
      referralId,
      ReferralState.closed,
      null,
    );
    expect(source.updatedStatus, ReferralState.closed);
  });

  test(
    'controller handles loading, success, error, and duplicate create',
    () async {
      final repository = _FakeReferralRepository()..response = _referral();
      final container = ProviderContainer(
        overrides: [referralRepositoryProvider.overrideWithValue(repository)],
      );
      addTearDown(container.dispose);
      final controller = container.read(referralControllerProvider.notifier);

      final first = controller.create(_referral());
      expect(
        container.read(referralControllerProvider).status,
        ReferralStatus.creating,
      );
      final second = controller.create(_referral());
      await Future.wait([first, second]);
      expect(repository.createCalls, 1);
      expect(
        container.read(referralControllerProvider).status,
        ReferralStatus.success,
      );

      repository.error = const ServerApiException(statusCode: 500);
      await controller.updateStatus(referralId, ReferralState.closed, null);
      expect(
        container.read(referralControllerProvider).status,
        ReferralStatus.error,
      );
      expect(
        container.read(referralControllerProvider).errorMessage,
        contains('server'),
      );
    },
  );

  testWidgets(
    'referral validates fields and displays successful backend response',
    (tester) async {
      final repository = _FakeReferralRepository()..response = _referral();
      final container = ProviderContainer(
        overrides: [referralRepositoryProvider.overrideWithValue(repository)],
      );
      addTearDown(container.dispose);
      container
          .read(prototypeSessionProvider.notifier)
          .addPatient(
            const Patient(
              id: patientId,
              name: 'Asha',
              age: 28,
              village: 'Village',
              facilityId: fromFacilityId,
            ),
            demo: false,
          );
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: ReferralScreen()),
        ),
      );

      final createButton = find.byKey(const ValueKey('referral-create-button'));
      await tester.ensureVisible(createButton);
      await tester.tap(createButton);
      await tester.pump();
      expect(find.text('Choose a destination facility'), findsOneWidget);
      final destination = find.byKey(
        const ValueKey('referral-destination-facility-id'),
      );
      await tester.ensureVisible(destination);
      await tester.tap(destination);
      await tester.pumpAndSettle();
      await tester.tap(find.text('District Hospital').last);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('referral-reason')),
        'Specialist review',
      );
      await tester.enterText(
        find.byKey(const ValueKey('referral-urgency')),
        'URGENT',
      );
      await tester.ensureVisible(createButton);
      await tester.tap(createButton);
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('referral-result')), findsOneWidget);
      expect(find.text('Referral created'), findsOneWidget);
    },
  );

  testWidgets('emergency referral preselects District Hospital', (
    tester,
  ) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container
        .read(prototypeSessionProvider.notifier)
        .addPatient(
          const Patient(
            id: patientId,
            name: 'Synthetic Asha',
            age: 28,
            village: 'Demo village',
            facilityId: fromFacilityId,
          ),
          demo: true,
        );
    final now = DateTime.now();
    container
        .read(prototypeSessionProvider.notifier)
        .setTriage(
          TriageEvaluationResponse(
            id: referralId,
            patientId: patientId,
            facilityId: fromFacilityId,
            triageDisposition: 'emergency',
            createdAt: now,
            decision: demoTriageDecision(
              vitals: const {},
              dangerSigns: const ['synthetic danger sign'],
              symptoms: const [],
              now: now,
            ),
          ),
        );
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: ReferralScreen()),
      ),
    );
    final destination = find.byKey(
      const ValueKey('referral-destination-facility-id'),
    );
    expect(
      tester.state<FormFieldState<String>>(destination).value,
      '123e4567-e89b-42d3-a456-426614174002',
    );
    expect(find.text('District Hospital'), findsOneWidget);
  });
}

Referral _referral() => const Referral(
  id: referralId,
  patientId: patientId,
  fromFacilityId: fromFacilityId,
  destinationFacilityId: destinationFacilityId,
  reason: 'Specialist review',
  urgency: 'URGENT',
);

Map<String, dynamic> _referralJson() => {
  ..._referral().toJson(),
  'created_at': '2026-09-16T10:00:00Z',
  'initiated_at': '2026-09-16T10:00:00Z',
};

class _FakeReferralDataSource implements ReferralRemoteDataSource {
  Referral? response;
  ReferralState? updatedStatus;
  ApiException? error;

  @override
  Future<Referral> createReferral(Referral referral) async {
    if (error != null) throw error!;
    return response!;
  }

  @override
  Future<void> updateReferralStatus(
    String id,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  ) async {
    if (error != null) throw error!;
    updatedStatus = status;
  }
}

class _FakeReferralRepository implements ReferralRepository {
  Referral? response;
  ApiException? error;
  int createCalls = 0;
  final Completer<void> _delay = Completer<void>();

  @override
  Future<Referral> createReferral(Referral referral) async {
    createCalls++;
    if (createCalls == 1 && !_delay.isCompleted) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    if (error != null) throw error!;
    return response!;
  }

  @override
  Future<void> updateReferralStatus(
    String id,
    ReferralState status,
    ReferralStatusUpdateBody? body,
  ) async {
    if (error != null) throw error!;
  }
}
