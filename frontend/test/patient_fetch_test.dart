import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/patient.dart';
import 'package:setu_swasthya/prototype/providers/api_providers.dart';
import 'package:setu_swasthya/prototype/providers/patient_provider.dart';
import 'package:setu_swasthya/prototype/repositories/patient_repository.dart';
import 'package:setu_swasthya/prototype/screens/patient/patient_screen.dart';

const patientId = '123e4567-e89b-12d3-a456-426614174000';

void main() {
  test(
    'provider rejects invalid patient IDs without a repository request',
    () async {
      final repository = _FakePatientRepository();
      final container = ProviderContainer(
        overrides: [patientRepositoryProvider.overrideWithValue(repository)],
      );
      addTearDown(container.dispose);

      final errorState = Completer<AsyncValue<Patient>>();
      final subscription = container.listen(patientProvider('test-id'), (
        _,
        next,
      ) {
        if (next.hasError && !errorState.isCompleted) errorState.complete(next);
      }, fireImmediately: true);
      final state = await errorState.future;
      expect(state.error, isA<InvalidPatientIdException>());
      subscription.close();
      expect(repository.fetchedId, isNull);
    },
  );

  test('provider returns a fetched patient successfully', () async {
    final patient = _patient();
    final repository = _FakePatientRepository()..patient = patient;
    final container = ProviderContainer(
      overrides: [patientRepositoryProvider.overrideWithValue(repository)],
    );
    addTearDown(container.dispose);

    final result = await container.read(patientProvider(patientId).future);

    expect(result, same(patient));
    expect(repository.fetchedId, patientId);
  });

  test('provider preserves not-found, unauthorized, network, timeout, and server errors', () async {
    final errors = <ApiException>[
      const ClientApiException(statusCode: 404),
      const ClientApiException(statusCode: 401),
      const NoInternetException(),
      const ApiTimeoutException(),
      const ServerApiException(statusCode: 500),
    ];

    for (final error in errors) {
      final repository = _FakePatientRepository()..error = error;
      final container = ProviderContainer(
        overrides: [patientRepositoryProvider.overrideWithValue(repository)],
      );
      addTearDown(container.dispose);

      final errorState = Completer<AsyncValue<Patient>>();
      final subscription = container.listen(patientProvider(patientId), (
        _,
        next,
      ) {
        if (next.hasError && !errorState.isCompleted) errorState.complete(next);
      }, fireImmediately: true);
      final state = await errorState.future;
      expect(state.error, same(error));
      subscription.close();
    }
  });

  testWidgets('profile displays only contract-backed patient fields', (
    tester,
  ) async {
    final patient = _patient();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          patientRepositoryProvider.overrideWithValue(
            _FakePatientRepository()..patient = patient,
          ),
        ],
        child: const MaterialApp(home: PatientScreen(patientId: patientId)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Asha Devi'), findsAtLeastNWidgets(1));
    expect(find.text('36'), findsOneWidget);
    expect(find.text('Rampur'), findsOneWidget);
    expect(find.text('No encounters yet'), findsNothing);
    expect(find.text('Vitals'), findsNothing);
  });

  testWidgets('profile displays loading and not-found states', (tester) async {
    final repository = _FakePatientRepository()
      ..error = const ClientApiException(statusCode: 404);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [patientRepositoryProvider.overrideWithValue(repository)],
        child: const MaterialApp(home: PatientScreen(patientId: patientId)),
      ),
    );

    expect(find.text('Loading patient...'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.text('Patient not found.'), findsOneWidget);
  });
}

Patient _patient() => Patient(
  id: patientId,
  name: 'Asha Devi',
  age: 36,
  village: 'Rampur',
  phone: '9999999999',
  facilityId: 'facility-id',
  createdAt: DateTime.parse('2026-09-16T10:00:00Z'),
);

class _FakePatientRepository implements PatientRepository {
  Patient? patient;
  ApiException? error;
  String? fetchedId;

  @override
  Future<Patient> getPatient(String id) async {
    fetchedId = id;
    if (error != null) throw error!;
    if (patient == null) throw const UnexpectedApiException();
    return patient!;
  }

  @override
  Future<Patient> createPatient(Patient patient) => throw UnimplementedError();

  @override
  Future<void> requestRegistrationOtp(String mobile) =>
      throw UnimplementedError();

  @override
  Future<String> verifyRegistrationOtp(String mobile, String otp) =>
      throw UnimplementedError();

  @override
  Future<void> registerPatient(PatientRegistrationRequest request) =>
      throw UnimplementedError();
}
