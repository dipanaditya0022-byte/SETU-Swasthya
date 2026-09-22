// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'referral_local.dart';

// **************************************************************************
// TypeAdapterGenerator
// **************************************************************************

class ReferralLocalAdapter extends TypeAdapter<ReferralLocal> {
  @override
  final int typeId = 1;

  @override
  ReferralLocal read(BinaryReader reader) {
    final numOfFields = reader.readByte();
    final fields = <int, dynamic>{
      for (int i = 0; i < numOfFields; i++) reader.readByte(): reader.read(),
    };
    return ReferralLocal(
      id: fields[0] as String,
      patientId: fields[1] as String,
      patientName: fields[2] as String,
      sourceFacility: fields[3] as String,
      destinationFacility: fields[4] as String,
      reason: fields[5] as String,
      urgency: fields[6] as String,
      status: fields[7] as String,
      createdAt: fields[8] as DateTime,
    );
  }

  @override
  void write(BinaryWriter writer, ReferralLocal obj) {
    writer
      ..writeByte(9)
      ..writeByte(0)
      ..write(obj.id)
      ..writeByte(1)
      ..write(obj.patientId)
      ..writeByte(2)
      ..write(obj.patientName)
      ..writeByte(3)
      ..write(obj.sourceFacility)
      ..writeByte(4)
      ..write(obj.destinationFacility)
      ..writeByte(5)
      ..write(obj.reason)
      ..writeByte(6)
      ..write(obj.urgency)
      ..writeByte(7)
      ..write(obj.status)
      ..writeByte(8)
      ..write(obj.createdAt);
  }

  @override
  int get hashCode => typeId.hashCode;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is ReferralLocalAdapter &&
          runtimeType == other.runtimeType &&
          typeId == other.typeId;
}
