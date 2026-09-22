enum ReferralState {
  initiated,
  slotBooked,
  transportArranged,
  arrived,
  consulted,
  backReferred,
  closed,
  cancelled,
  notArrived,
  traced,
  rescheduled,
  refused,
  lost,
}

enum RefusalReason {
  cost,
  distance,
  familyDecidedAgainst,
  alreadyRecovered,
  wentPrivate,
  couldNotBeContacted,
  other,
}

const _referralStateValues = {
  ReferralState.initiated: 'INITIATED',
  ReferralState.slotBooked: 'SLOT_BOOKED',
  ReferralState.transportArranged: 'TRANSPORT_ARRANGED',
  ReferralState.arrived: 'ARRIVED',
  ReferralState.consulted: 'CONSULTED',
  ReferralState.backReferred: 'BACK_REFERRED',
  ReferralState.closed: 'CLOSED',
  ReferralState.cancelled: 'CANCELLED',
  ReferralState.notArrived: 'NOT_ARRIVED',
  ReferralState.traced: 'TRACED',
  ReferralState.rescheduled: 'RESCHEDULED',
  ReferralState.refused: 'REFUSED',
  ReferralState.lost: 'LOST',
};

const _refusalReasonValues = {
  RefusalReason.cost: 'COST',
  RefusalReason.distance: 'DISTANCE',
  RefusalReason.familyDecidedAgainst: 'FAMILY_DECIDED_AGAINST',
  RefusalReason.alreadyRecovered: 'ALREADY_RECOVERED',
  RefusalReason.wentPrivate: 'WENT_PRIVATE',
  RefusalReason.couldNotBeContacted: 'COULD_NOT_BE_CONTACTED',
  RefusalReason.other: 'OTHER',
};

String referralStateValue(ReferralState value) => _referralStateValues[value]!;

ReferralState referralStateFromValue(String value) => _referralStateValues
    .entries
    .firstWhere(
      (entry) => entry.value == value,
      orElse: () => throw FormatException('Unknown referral state: $value'),
    )
    .key;

String refusalReasonValue(RefusalReason value) => _refusalReasonValues[value]!;

class Referral {
  const Referral({
    required this.patientId,
    required this.fromFacilityId,
    required this.destinationFacilityId,
    required this.reason,
    required this.urgency,
    this.id,
    this.status = ReferralState.initiated,
    this.receivingUnit,
    this.owner,
    this.dueDate,
    this.createdAt,
    this.createdByUserId,
    this.orgUnitId,
    this.initiatedAt,
    this.dueAt,
    this.breachedAt,
    this.breachDetectedBy,
    this.escalationStage = 0,
    this.escalationNotifiedAt,
    this.ownerUserId,
    this.arrivedAt,
    this.backReferredAt,
    this.closedAt,
    this.slotDatetime,
    this.transportMode,
    this.arrivalConfirmedBy,
    this.arrivalScanRef,
    this.refusalReason,
    this.lossReason,
    this.cancellationReason,
    this.backReferralNote,
    this.syncedAt,
  });

  final String? id;
  final String patientId;
  final String fromFacilityId;
  final String destinationFacilityId;
  final String reason;
  final String urgency;
  final ReferralState status;
  final String? receivingUnit;
  final String? owner;
  final DateTime? dueDate;
  final DateTime? createdAt;
  final String? createdByUserId;
  final String? orgUnitId;
  final DateTime? initiatedAt;
  final DateTime? dueAt;
  final DateTime? breachedAt;
  final String? breachDetectedBy;
  final int escalationStage;
  final DateTime? escalationNotifiedAt;
  final String? ownerUserId;
  final DateTime? arrivedAt;
  final DateTime? backReferredAt;
  final DateTime? closedAt;
  final DateTime? slotDatetime;
  final String? transportMode;
  final String? arrivalConfirmedBy;
  final String? arrivalScanRef;
  final String? refusalReason;
  final String? lossReason;
  final String? cancellationReason;
  final String? backReferralNote;
  final DateTime? syncedAt;

  factory Referral.fromJson(Map<String, dynamic> json) => Referral(
    id: json['id'] as String?,
    patientId: json['patient_id'] as String,
    fromFacilityId: json['from_facility_id'] as String,
    destinationFacilityId: json['destination_facility_id'] as String,
    reason: json['reason'] as String,
    urgency: json['urgency'] as String,
    status: json['status'] == null
        ? ReferralState.initiated
        : referralStateFromValue(json['status'] as String),
    receivingUnit: json['receiving_unit'] as String?,
    owner: json['owner'] as String?,
    dueDate: _date(json['due_date']),
    createdAt: _date(json['created_at']),
    createdByUserId: json['created_by_user_id'] as String?,
    orgUnitId: json['org_unit_id'] as String?,
    initiatedAt: _date(json['initiated_at']),
    dueAt: _date(json['due_at']),
    breachedAt: _date(json['breached_at']),
    breachDetectedBy: json['breach_detected_by'] as String?,
    escalationStage: json['escalation_stage'] as int? ?? 0,
    escalationNotifiedAt: _date(json['escalation_notified_at']),
    ownerUserId: json['owner_user_id'] as String?,
    arrivedAt: _date(json['arrived_at']),
    backReferredAt: _date(json['back_referred_at']),
    closedAt: _date(json['closed_at']),
    slotDatetime: _date(json['slot_datetime']),
    transportMode: json['transport_mode'] as String?,
    arrivalConfirmedBy: json['arrival_confirmed_by'] as String?,
    arrivalScanRef: json['arrival_scan_ref'] as String?,
    refusalReason: json['refusal_reason'] as String?,
    lossReason: json['loss_reason'] as String?,
    cancellationReason: json['cancellation_reason'] as String?,
    backReferralNote: json['back_referral_note'] as String?,
    syncedAt: _date(json['synced_at']),
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'patient_id': patientId,
    'from_facility_id': fromFacilityId,
    'destination_facility_id': destinationFacilityId,
    'reason': reason,
    'urgency': urgency,
    'status': referralStateValue(status),
    'receiving_unit': receivingUnit,
    'owner': owner,
    'due_date': dueDate?.toIso8601String(),
    'created_at': createdAt?.toIso8601String(),
    'created_by_user_id': createdByUserId,
    'org_unit_id': orgUnitId,
    'initiated_at': initiatedAt?.toIso8601String(),
    'due_at': dueAt?.toIso8601String(),
    'breached_at': breachedAt?.toIso8601String(),
    'breach_detected_by': breachDetectedBy,
    'escalation_stage': escalationStage,
    'escalation_notified_at': escalationNotifiedAt?.toIso8601String(),
    'owner_user_id': ownerUserId,
    'arrived_at': arrivedAt?.toIso8601String(),
    'back_referred_at': backReferredAt?.toIso8601String(),
    'closed_at': closedAt?.toIso8601String(),
    'slot_datetime': slotDatetime?.toIso8601String(),
    'transport_mode': transportMode,
    'arrival_confirmed_by': arrivalConfirmedBy,
    'arrival_scan_ref': arrivalScanRef,
    'refusal_reason': refusalReason,
    'loss_reason': lossReason,
    'cancellation_reason': cancellationReason,
    'back_referral_note': backReferralNote,
    'synced_at': syncedAt?.toIso8601String(),
  };
}

class ReferralStatusUpdateBody {
  const ReferralStatusUpdateBody({
    this.reason,
    this.slotDatetime,
    this.destinationOrgUnitId,
    this.transportMode,
    this.arrivalConfirmedBy,
    this.arrivalScanRef,
    this.consultedByUserId,
    this.backReferralNote,
    this.tracedByUserId,
    this.refusalReason,
    this.lossReason,
    this.cancellationReason,
  });

  final String? reason;
  final DateTime? slotDatetime;
  final String? destinationOrgUnitId;
  final String? transportMode;
  final String? arrivalConfirmedBy;
  final String? arrivalScanRef;
  final String? consultedByUserId;
  final String? backReferralNote;
  final String? tracedByUserId;
  final RefusalReason? refusalReason;
  final String? lossReason;
  final String? cancellationReason;

  Map<String, dynamic> toJson() => {
    'reason': reason,
    'slot_datetime': slotDatetime?.toIso8601String(),
    'destination_org_unit_id': destinationOrgUnitId,
    'transport_mode': transportMode,
    'arrival_confirmed_by': arrivalConfirmedBy,
    'arrival_scan_ref': arrivalScanRef,
    'consulted_by_user_id': consultedByUserId,
    'back_referral_note': backReferralNote,
    'traced_by_user_id': tracedByUserId,
    'refusal_reason': refusalReason == null
        ? null
        : refusalReasonValue(refusalReason!),
    'loss_reason': lossReason,
    'cancellation_reason': cancellationReason,
  };
}

DateTime? _date(Object? value) =>
    value == null ? null : DateTime.parse(value as String);
