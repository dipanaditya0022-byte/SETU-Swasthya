enum TriageSex { female, male, other }

enum TriageDisposition { manageHere, teleconsult, refer, emergency }

enum TriageUrgency {
  immediate,
  within2h,
  within24h,
  within72h,
  within7d,
  routine,
}

enum TriageEngine { rule, fallback }

String _sexValue(TriageSex value) => switch (value) {
  TriageSex.female => 'FEMALE',
  TriageSex.male => 'MALE',
  TriageSex.other => 'OTHER',
};

String _dispositionValue(TriageDisposition value) => switch (value) {
  TriageDisposition.manageHere => 'MANAGE_HERE',
  TriageDisposition.teleconsult => 'TELECONSULT',
  TriageDisposition.refer => 'REFER',
  TriageDisposition.emergency => 'EMERGENCY',
};

String _urgencyValue(TriageUrgency value) => switch (value) {
  TriageUrgency.immediate => 'IMMEDIATE',
  TriageUrgency.within2h => 'WITHIN_2H',
  TriageUrgency.within24h => 'WITHIN_24H',
  TriageUrgency.within72h => 'WITHIN_72H',
  TriageUrgency.within7d => 'WITHIN_7D',
  TriageUrgency.routine => 'ROUTINE',
};

TriageDisposition _dispositionFromValue(String value) =>
    TriageDisposition.values.firstWhere(
      (item) => _dispositionValue(item) == value,
      orElse: () => throw FormatException('Unknown triage disposition: $value'),
    );

TriageUrgency _urgencyFromValue(String value) =>
    TriageUrgency.values.firstWhere(
      (item) => _urgencyValue(item) == value,
      orElse: () => throw FormatException('Unknown triage urgency: $value'),
    );

TriageEngine _engineFromValue(String value) => TriageEngine.values.firstWhere(
  (item) => item.name == value,
  orElse: () => throw FormatException('Unknown triage engine: $value'),
);

class TriageEvaluationRequest {
  const TriageEvaluationRequest({
    required this.patientId,
    required this.facilityId,
    required this.triageDisposition,
    this.referralUrgency,
    this.protocol,
    this.vitals = const <String, num>{},
    this.symptoms = const <String>[],
    this.dangerSigns = const <String>[],
    this.sex,
    this.isPregnant = false,
    this.gestationalWeeks,
    this.history = const <String, bool>{},
    this.clinicalHistory,
  });

  final String patientId;
  final String facilityId;
  final String triageDisposition;
  final String? referralUrgency;
  final String? protocol;
  final Map<String, num> vitals;
  final List<String> symptoms;
  final List<String> dangerSigns;
  final TriageSex? sex;
  final bool isPregnant;
  final num? gestationalWeeks;
  final Map<String, bool> history;
  final String? clinicalHistory;

  Map<String, dynamic> toJson() => {
    'patient_id': patientId,
    'facility_id': facilityId,
    'triage_disposition': triageDisposition,
    'referral_urgency': referralUrgency,
    'protocol': protocol,
    'vitals': vitals,
    'symptoms': symptoms,
    'danger_signs': dangerSigns,
    'sex': sex == null ? null : _sexValue(sex!),
    'is_pregnant': isPregnant,
    'gestational_weeks': gestationalWeeks,
    'history': history,
    if (clinicalHistory != null) 'clinical_history': clinicalHistory,
  };
}

class TriageDecision {
  const TriageDecision({
    required this.disposition,
    required this.urgency,
    required this.reason,
    required this.redFlags,
    required this.protocolVersion,
    required this.insufficientData,
    required this.missingFields,
    required this.engine,
    required this.evaluatedAt,
  });

  final TriageDisposition disposition;
  final TriageUrgency urgency;
  final String reason;
  final List<String> redFlags;
  final String protocolVersion;
  final bool insufficientData;
  final List<String> missingFields;
  final TriageEngine engine;
  final DateTime evaluatedAt;

  factory TriageDecision.fromJson(Map<String, dynamic> json) => TriageDecision(
    disposition: _dispositionFromValue(json['disposition'] as String),
    urgency: _urgencyFromValue(json['urgency'] as String),
    reason: json['reason'] as String,
    redFlags: (json['red_flags'] as List<dynamic>).cast<String>(),
    protocolVersion: json['protocol_version'] as String,
    insufficientData: json['insufficient_data'] as bool,
    missingFields: (json['missing_fields'] as List<dynamic>).cast<String>(),
    engine: _engineFromValue(json['engine'] as String),
    evaluatedAt: DateTime.parse(json['evaluated_at'] as String),
  );
}

class TriageEvaluationResponse {
  const TriageEvaluationResponse({
    required this.id,
    required this.patientId,
    required this.facilityId,
    required this.triageDisposition,
    required this.createdAt,
    required this.decision,
    this.referralUrgency,
    this.createdByUserId,
    this.orgUnitId,
  });

  final String id;
  final String patientId;
  final String facilityId;
  final String triageDisposition;
  final String? referralUrgency;
  final DateTime createdAt;
  final String? createdByUserId;
  final String? orgUnitId;
  final TriageDecision decision;

  factory TriageEvaluationResponse.fromJson(Map<String, dynamic> json) =>
      TriageEvaluationResponse(
        id: json['id'] as String,
        patientId: json['patient_id'] as String,
        facilityId: json['facility_id'] as String,
        triageDisposition: json['triage_disposition'] as String,
        referralUrgency: json['referral_urgency'] as String?,
        createdAt: DateTime.parse(json['created_at'] as String),
        createdByUserId: json['created_by_user_id'] as String?,
        orgUnitId: json['org_unit_id'] as String?,
        decision: TriageDecision.fromJson(
          json['decision'] as Map<String, dynamic>,
        ),
      );
}
