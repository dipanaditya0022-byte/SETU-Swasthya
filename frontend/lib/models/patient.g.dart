// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'patient.dart';

// **************************************************************************
// TypeAdapterGenerator
// **************************************************************************

class PatientLocalAdapter extends TypeAdapter<PatientLocal> {
  @override
  final int typeId = 0;

  @override
  PatientLocal read(BinaryReader reader) {
    final numOfFields = reader.readByte();
    final fields = <int, dynamic>{
      for (int i = 0; i < numOfFields; i++) reader.readByte(): reader.read(),
    };
    return PatientLocal(
      clientUuid: fields[0] as String,
      name: fields[1] as String,
      age: fields[2] as int,
      village: fields[3] as String,
      synced: fields[4] as bool,
      phone: fields[5] as String? ?? '',
      facilityId: fields[6] as String? ?? '',
      backendPatientId: fields[7] as String?,
    );
  }

  @override
  void write(BinaryWriter writer, PatientLocal obj) {
    writer
      ..writeByte(8)
      ..writeByte(0)
      ..write(obj.clientUuid)
      ..writeByte(1)
      ..write(obj.name)
      ..writeByte(2)
      ..write(obj.age)
      ..writeByte(3)
      ..write(obj.village)
      ..writeByte(4)
      ..write(obj.synced)
      ..writeByte(5)
      ..write(obj.phone)
      ..writeByte(6)
      ..write(obj.facilityId)
      ..writeByte(7)
      ..write(obj.backendPatientId);
  }

  @override
  int get hashCode => typeId.hashCode;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is PatientLocalAdapter &&
          runtimeType == other.runtimeType &&
          typeId == other.typeId;
}
