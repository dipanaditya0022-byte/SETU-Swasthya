enum PatientSex { female, male, other }

enum GuardianRelation { mother, father, guardian }

enum ConsentMode { digitalSelf, spokenWitnessed, thumbImpression }

String _enumValue(Object value) => switch (value) {
  PatientSex.female => 'FEMALE',
  PatientSex.male => 'MALE',
  PatientSex.other => 'OTHER',
  GuardianRelation.mother => 'MOTHER',
  GuardianRelation.father => 'FATHER',
  GuardianRelation.guardian => 'GUARDIAN',
  ConsentMode.digitalSelf => 'DIGITAL_SELF',
  ConsentMode.spokenWitnessed => 'SPOKEN_WITNESSED',
  ConsentMode.thumbImpression => 'THUMB_IMPRESSION',
  _ => throw ArgumentError.value(value, 'value', 'Unsupported contract enum'),
};

PatientSex _patientSex(String value) => PatientSex.values.firstWhere(
  (item) => _enumValue(item) == value,
  orElse: () => throw FormatException('Unknown patient sex: $value'),
);

GuardianRelation _guardianRelation(String value) =>
    GuardianRelation.values.firstWhere(
      (item) => _enumValue(item) == value,
      orElse: () => throw FormatException('Unknown guardian relation: $value'),
    );

ConsentMode _consentMode(String value) => ConsentMode.values.firstWhere(
  (item) => _enumValue(item) == value,
  orElse: () => throw FormatException('Unknown consent mode: $value'),
);

String _dateOnly(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

class Patient {
  const Patient({
    required this.name,
    required this.age,
    required this.village,
    required this.facilityId,
    this.id,
    this.phone,
    this.createdAt,
    this.clientUuid,
    this.createdByUserId,
    this.orgUnitId,
    this.syncedAt,
  });

  final String? id;
  final String name;
  final int age;
  final String village;
  final String? phone;
  final String facilityId;
  final DateTime? createdAt;
  final String? clientUuid;
  final String? createdByUserId;
  final String? orgUnitId;
  final DateTime? syncedAt;

  factory Patient.fromJson(Map<String, dynamic> json) => Patient(
    id: json['id'] as String?,
    name: json['name'] as String,
    age: json['age'] as int,
    village: json['village'] as String,
    phone: json['phone'] as String?,
    facilityId: json['facility_id'] as String,
    createdAt: _parseDateTime(json['created_at']),
    clientUuid: json['client_uuid'] as String?,
    createdByUserId: json['created_by_user_id'] as String?,
    orgUnitId: json['org_unit_id'] as String?,
    syncedAt: _parseDateTime(json['synced_at']),
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'age': age,
    'village': village,
    'phone': phone,
    'facility_id': facilityId,
    'created_at': createdAt?.toIso8601String(),
    'client_uuid': clientUuid,
    'created_by_user_id': createdByUserId,
    'org_unit_id': orgUnitId,
    'synced_at': syncedAt?.toIso8601String(),
  };
}

class PatientRegistrationRequest {
  const PatientRegistrationRequest({
    required this.fullName,
    required this.sex,
    required this.mobile,
    required this.villageLgdCode,
    required this.preferredLanguage,
    required this.consentKeepRecord,
    required this.consentShareSpecialist,
    required this.consentShareFacility,
    required this.consentAnonymisedPlanning,
    required this.consentMode,
    required this.otpToken,
    this.fullNameLocal,
    this.dateOfBirth,
    this.ageYears,
    this.isSharedPhone = false,
    this.abhaNumber,
    this.abhaAddress,
    this.hamlet,
    this.houseNumber,
    this.householdId,
    this.guardianName,
    this.guardianRelation,
    this.guardianMobile,
    this.emergencyContactName,
    this.emergencyContactMobile,
  });

  final String fullName;
  final String? fullNameLocal;
  final DateTime? dateOfBirth;
  final int? ageYears;
  final PatientSex sex;
  final String mobile;
  final bool isSharedPhone;
  final String? abhaNumber;
  final String? abhaAddress;
  final String villageLgdCode;
  final String? hamlet;
  final String? houseNumber;
  final String? householdId;
  final String preferredLanguage;
  final String? guardianName;
  final GuardianRelation? guardianRelation;
  final String? guardianMobile;
  final String? emergencyContactName;
  final String? emergencyContactMobile;
  final bool consentKeepRecord;
  final bool consentShareSpecialist;
  final bool consentShareFacility;
  final bool consentAnonymisedPlanning;
  final ConsentMode consentMode;
  final String otpToken;

  Map<String, dynamic> toJson() => {
    'full_name': fullName,
    'full_name_local': fullNameLocal,
    'date_of_birth': dateOfBirth == null ? null : _dateOnly(dateOfBirth!),
    'age_years': ageYears,
    'sex': _enumValue(sex),
    'mobile': mobile,
    'is_shared_phone': isSharedPhone,
    'abha_number': abhaNumber,
    'abha_address': abhaAddress,
    'village_lgd_code': villageLgdCode,
    'hamlet': hamlet,
    'house_number': houseNumber,
    'household_id': householdId,
    'preferred_language': preferredLanguage,
    'guardian_name': guardianName,
    'guardian_relation': guardianRelation == null
        ? null
        : _enumValue(guardianRelation!),
    'guardian_mobile': guardianMobile,
    'emergency_contact_name': emergencyContactName,
    'emergency_contact_mobile': emergencyContactMobile,
    'consent_keep_record': consentKeepRecord,
    'consent_share_specialist': consentShareSpecialist,
    'consent_share_facility': consentShareFacility,
    'consent_anonymised_planning': consentAnonymisedPlanning,
    'consent_mode': _enumValue(consentMode),
    'otp_token': otpToken,
  };

  factory PatientRegistrationRequest.fromJson(Map<String, dynamic> json) =>
      PatientRegistrationRequest(
        fullName: json['full_name'] as String,
        fullNameLocal: json['full_name_local'] as String?,
        dateOfBirth: json['date_of_birth'] == null
            ? null
            : DateTime.parse(json['date_of_birth'] as String),
        ageYears: json['age_years'] as int?,
        sex: _patientSex(json['sex'] as String),
        mobile: json['mobile'] as String,
        isSharedPhone: json['is_shared_phone'] as bool? ?? false,
        abhaNumber: json['abha_number'] as String?,
        abhaAddress: json['abha_address'] as String?,
        villageLgdCode: json['village_lgd_code'] as String,
        hamlet: json['hamlet'] as String?,
        houseNumber: json['house_number'] as String?,
        householdId: json['household_id'] as String?,
        preferredLanguage: json['preferred_language'] as String,
        guardianName: json['guardian_name'] as String?,
        guardianRelation: json['guardian_relation'] == null
            ? null
            : _guardianRelation(json['guardian_relation'] as String),
        guardianMobile: json['guardian_mobile'] as String?,
        emergencyContactName: json['emergency_contact_name'] as String?,
        emergencyContactMobile: json['emergency_contact_mobile'] as String?,
        consentKeepRecord: json['consent_keep_record'] as bool,
        consentShareSpecialist: json['consent_share_specialist'] as bool,
        consentShareFacility: json['consent_share_facility'] as bool,
        consentAnonymisedPlanning: json['consent_anonymised_planning'] as bool,
        consentMode: _consentMode(json['consent_mode'] as String),
        otpToken: json['otp_token'] as String,
      );
}

DateTime? _parseDateTime(Object? value) =>
    value == null ? null : DateTime.parse(value as String);
