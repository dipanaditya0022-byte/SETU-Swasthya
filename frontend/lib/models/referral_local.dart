import 'package:hive/hive.dart';

part 'referral_local.g.dart';

@HiveType(typeId: 1)
class ReferralLocal extends HiveObject {
  @HiveField(0)
  String id;

  @HiveField(1)
  String patientId;

  @HiveField(2)
  String patientName;

  @HiveField(3)
  String sourceFacility;

  @HiveField(4)
  String destinationFacility;

  @HiveField(5)
  String reason;

  @HiveField(6)
  String urgency;

  @HiveField(7)
  String status;

  @HiveField(8)
  DateTime createdAt;

  ReferralLocal({
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
}
