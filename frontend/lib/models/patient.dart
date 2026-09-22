import 'package:hive/hive.dart';

part 'patient.g.dart';

@HiveType(typeId: 0)
class PatientLocal extends HiveObject {
  @HiveField(0)
  String clientUuid;

  @HiveField(1)
  String name;

  @HiveField(2)
  int age;

  @HiveField(3)
  String village;

  @HiveField(4)
  bool synced;

  @HiveField(5)
  String phone;

  @HiveField(6)
  String facilityId;

  @HiveField(7)
  String? backendPatientId;

  PatientLocal({
    required this.clientUuid,
    required this.name,
    required this.age,
    required this.village,
    required this.synced,
    required this.phone,
    required this.facilityId,
    this.backendPatientId,
  });
}
