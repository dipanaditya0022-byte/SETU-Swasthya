import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/core/network/api_client.dart';
import 'package:setu_swasthya/prototype/core/network/api_exception.dart';
import 'package:setu_swasthya/prototype/models/auth_requests.dart';
import 'package:setu_swasthya/prototype/models/patient.dart';
import 'package:setu_swasthya/prototype/repositories/patient_repository.dart';
import 'package:setu_swasthya/prototype/services/patient_remote_data_source.dart';

void main() {
  group('Patient JSON', () {
    test('round-trips required, nullable, enum, date, and datetime fields', () {
      final patient = PatientRegistrationRequest(
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
        dateOfBirth: DateTime(1990, 2, 3),
        guardianRelation: GuardianRelation.mother,
      );

      final decoded = PatientRegistrationRequest.fromJson(patient.toJson());

      expect(decoded.fullName, 'Asha Devi');
      expect(decoded.sex, PatientSex.female);
      expect(decoded.dateOfBirth, DateTime(1990, 2, 3));
      expect(decoded.guardianRelation, GuardianRelation.mother);
      expect(decoded.abhaNumber, isNull);
      expect(patient.toJson()['date_of_birth'], '1990-02-03');
      expect(patient.toJson()['consent_mode'], 'DIGITAL_SELF');
    });

    test('serializes Patient date-time fields using contract names', () {
      final patient = Patient(
        id: 'patient-id',
        name: 'Asha Devi',
        age: 36,
        village: 'Rampur',
        facilityId: 'facility-id',
        phone: null,
        createdAt: DateTime.parse('2026-01-02T03:04:05Z'),
      );

      final decoded = Patient.fromJson(patient.toJson());

      expect(decoded.id, 'patient-id');
      expect(decoded.phone, isNull);
      expect(decoded.createdAt, DateTime.parse('2026-01-02T03:04:05Z'));
      expect(patient.toJson().containsKey('facility_id'), isTrue);
    });
  });

  test('auth request models use exact contract field names', () {
    expect(
      const OtpRequestBody(
        mobile: '9999999999',
        purpose: OtpPurpose.login,
      ).toJson(),
      {'mobile': '9999999999', 'purpose': 'LOGIN'},
    );
    expect(const LoginRequest(otpToken: 'otp').toJson()['otp_token'], 'otp');
  });

  group('API exception mapping', () {
    test('maps connectivity, timeout, validation, client, server, and unexpected errors', () {
      ApiException map(DioExceptionType type, {int? statusCode}) =>
          ApiException.fromDio(
            DioException(
              requestOptions: RequestOptions(path: '/patients/'),
              type: type,
              response: statusCode == null
                  ? null
                  : Response(
                      requestOptions: RequestOptions(path: '/patients/'),
                      statusCode: statusCode,
                    ),
            ),
          );

      expect(map(DioExceptionType.connectionError), isA<NoInternetException>());
      expect(
        map(DioExceptionType.connectionTimeout),
        isA<ApiTimeoutException>(),
      );
      expect(map(DioExceptionType.receiveTimeout), isA<ApiTimeoutException>());
      expect(
        map(DioExceptionType.badResponse, statusCode: 422),
        isA<ValidationApiException>(),
      );
      expect(
        map(DioExceptionType.badResponse, statusCode: 404),
        isA<ClientApiException>(),
      );
      expect(
        map(DioExceptionType.badResponse, statusCode: 503),
        isA<ServerApiException>(),
      );
      expect(map(DioExceptionType.unknown), isA<UnexpectedApiException>());
    });
  });

  test(
    'repository delegates patient operations to the remote source',
    () async {
      final source = _FakePatientRemoteDataSource();
      final repository = PatientRepositoryImpl(source);
      const patient = Patient(
        name: 'Asha',
        age: 30,
        village: 'Rampur',
        facilityId: 'facility',
      );

      expect(await repository.createPatient(patient), same(source.patient));
      expect(await repository.getPatient('patient-id'), same(source.patient));
      expect(source.createdPatient, same(patient));
      expect(source.fetchedPatientId, 'patient-id');
    },
  );

  test(
    'API client uses injected base URL and leaves auth header extensible',
    () async {
      final client = ApiClient(
        baseUrl: 'https://example.test',
        accessTokenProvider: () => 'Bearer test',
      );

      expect(client.dio.options.baseUrl, 'https://example.test');
      expect(client.dio.options.connectTimeout, const Duration(seconds: 10));
      expect(client.dio.interceptors, isNotEmpty);
    },
  );

  test('patient remote data source uses the contract endpoints', () async {
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
              data: const {
                'name': 'Asha',
                'age': 30,
                'village': 'Rampur',
                'facility_id': 'facility-id',
              },
            ),
          );
        },
      ),
    );
    final source = DioPatientRemoteDataSource(dio);
    const patient = Patient(
      name: 'Asha',
      age: 30,
      village: 'Rampur',
      facilityId: 'facility-id',
    );

    await source.createPatient(patient);
    await source.getPatient('patient-id');

    expect(requests[0].method, 'POST');
    expect(requests[0].path, '/patients/');
    expect(requests[1].method, 'GET');
    expect(requests[1].path, '/patients/patient-id');
  });

  test(
    'registration remote data source uses the exact auth endpoints',
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
                statusCode: options.path == '/auth/patient/register'
                    ? 201
                    : 200,
                data: options.path == '/auth/otp/verify'
                    ? const {'otp_token': 'token'}
                    : const <String, dynamic>{},
              ),
            );
          },
        ),
      );
      final source = DioPatientRemoteDataSource(dio);

      await source.requestRegistrationOtp(
        const OtpRequestBody(
          mobile: '9999999999',
          purpose: OtpPurpose.patientRegistration,
        ),
      );
      final verified = await source.verifyRegistrationOtp(
        const OtpVerifyBody(mobile: '9999999999', otp: '123456'),
      );
      await source.registerPatient(
        const PatientRegistrationRequest(
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
          otpToken: 'token',
        ),
      );

      expect(verified['otp_token'], 'token');
      expect(requests.map((request) => '${request.method} ${request.path}'), [
        'POST /auth/otp/request',
        'POST /auth/otp/verify',
        'POST /auth/patient/register',
      ]);
    },
  );
}

class _FakePatientRemoteDataSource implements PatientRemoteDataSource {
  final patient = const Patient(
    name: 'Remote',
    age: 31,
    village: 'Remote village',
    facilityId: 'facility',
  );
  Patient? createdPatient;
  String? fetchedPatientId;

  @override
  Future<Patient> createPatient(Patient patient) async {
    createdPatient = patient;
    return this.patient;
  }

  @override
  Future<Patient> getPatient(String patientId) async {
    fetchedPatientId = patientId;
    return patient;
  }

  @override
  Future<void> requestRegistrationOtp(OtpRequestBody request) async {}

  @override
  Future<Map<String, dynamic>> verifyRegistrationOtp(
    OtpVerifyBody request,
  ) async => {'otp_token': 'test-token'};

  @override
  Future<void> registerPatient(PatientRegistrationRequest request) async {}
}
