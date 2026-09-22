enum ReferralUrgency {
  emergency,
  priority,
}

enum ReferralStatus {
  pending,
  accepted,
  inTransit,
  completed,
  cancelled,
}

class Referral {
  final String id;
  final String patientId;
  final String patientName;
  final String sourceFacility;
  final String destinationFacility;
  final String reason;
  final ReferralUrgency urgency;
  final ReferralStatus status;
  final DateTime createdAt;

  const Referral({
    required this.id,
    required this.patientId,
    required this.patientName,
    required this.sourceFacility,
    required this.destinationFacility,
    required this.reason,
    required this.urgency,
    required this.status,
    required this.createdAt,
  });

  Referral copyWith({
    ReferralStatus? status,
  }) {
    return Referral(
      id: id,
      patientId: patientId,
      patientName: patientName,
      sourceFacility: sourceFacility,
      destinationFacility: destinationFacility,
      reason: reason,
      urgency: urgency,
      status: status ?? this.status,
      createdAt: createdAt,
    );
  }
}