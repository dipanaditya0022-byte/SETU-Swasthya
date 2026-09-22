import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/patient.dart';
import 'package:setu_swasthya/prototype/providers/api_providers.dart';
import 'package:setu_swasthya/prototype/providers/patient_registration_provider.dart';
import 'package:setu_swasthya/prototype/repositories/patient_repository.dart';

void main() {
  test('registration controller submits only after OTP verification', () async {
    final repository = _FakePatientRepository();
    final container = ProviderContainer(
      overrides: [patientRepositoryProvider.overrideWithValue(repository)],
    );
    addTearDown(container.dispose);
    final controller = container.read(patientRegistrationProvider.notifier);

    await controller.submit(_request());
    expect(
      container.read(patientRegistrationProvider).errorMessage,
      contains('Verify the OTP'),
    );
    expect(repository.registered, isFalse);

    await controller.verifyOtp('9999999999', '123456');
    expect(container.read(patientRegistrationProvider).otpToken, 'otp-token');

    await controller.submit(_request());
    expect(
      container.read(patientRegistrationProvider).status,
      RegistrationStatus.success,
    );
    expect(repository.registeredRequest?.otpToken, 'otp-token');
  });

  test(
    'registration controller exposes loading and typed failure state',
    () async {
      final repository = _FakePatientRepository()
        ..registrationError = const NoInternetException();
      final container = ProviderContainer(
        overrides: [patientRepositoryProvider.overrideWithValue(repository)],
      );
      addTearDown(container.dispose);
      final controller = container.read(patientRegistrationProvider.notifier);
      await controller.verifyOtp('9999999999', '123456');
      expect(
        container.read(patientRegistrationProvider).status,
        RegistrationStatus.failure,
      );
      expect(
        container.read(patientRegistrationProvider).errorMessage,
        'No internet connection is available.',
      );
    },
  );

  test('requestOtp exposes diagnostic details for concrete Dio failure and redacts secrets', () async {
    final dioError = DioException(
      requestOptions: RequestOptions(path: '/auth/otp/request'),
      type: DioExceptionType.unknown,
      error: 'Invalid argument(s): No host specified in URI /auth/otp/request',
      response: Response(
        requestOptions: RequestOptions(path: '/auth/otp/request'),
        statusCode: 422,
        data: {
          'detail': 'Invalid mobile format',
          'otp_token': 'secret-token-12345',
        },
      ),
    );
    final repository = _FakePatientRepository()
      ..otpRequestError = ApiException.fromDio(dioError);
    final container = ProviderContainer(
      overrides: [patientRepositoryProvider.overrideWithValue(repository)],
    );
    addTearDown(container.dispose);
    final controller = container.read(patientRegistrationProvider.notifier);

    await controller.requestOtp('9999999999');

    final state = container.read(patientRegistrationProvider);
    expect(state.status, RegistrationStatus.failure);
    expect(state.errorMessage, contains('status: 422'));
    expect(state.errorMessage, contains('Invalid mobile format'));
    expect(state.errorMessage, contains('[REDACTED]'));
    expect(state.errorMessage, isNot(contains('secret-token-12345')));
  });
}

PatientRegistrationRequest _request() => const PatientRegistrationRequest(
  fullName: 'Asha Devi',
  sex: PatientSex.female,
  mobile: '9999999999',
  villageLgdCode: 'V-1',
  preferredLanguage: 'hi',
  consentKeepRecord: true,
  consentShareSpecialist: false,
  consentShareFacility: true,
  consentAnonymisedPlanning: false,
  consentMode: ConsentMode.digitalSelf,
  otpToken: 'otp-token',
);

class _FakePatientRepository implements PatientRepository {
  bool registered = false;
  PatientRegistrationRequest? registeredRequest;
  ApiException? registrationError;
  ApiException? otpRequestError;

  @override
  Future<Patient> createPatient(Patient patient) => throw UnimplementedError();

  @override
  Future<Patient> getPatient(String patientId) => throw UnimplementedError();

  @override
  Future<void> requestRegistrationOtp(String mobile) async {
    if (otpRequestError != null) throw otpRequestError!;
  }

  @override
  Future<String> verifyRegistrationOtp(String mobile, String otp) async {
    if (registrationError != null) throw registrationError!;
    return 'otp-token';
  }

  @override
  Future<void> registerPatient(PatientRegistrationRequest request) async {
    if (registrationError != null) throw registrationError!;
    registered = true;
    registeredRequest = request;
  }
}
