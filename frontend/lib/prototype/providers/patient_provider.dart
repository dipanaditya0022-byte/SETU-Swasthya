import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/patient.dart';
import 'api_providers.dart';

final patientProvider = FutureProvider.family<Patient, String>((
  ref,
  patientId,
) async {
  final uuid = _parseUuid(patientId);
  if (uuid == null) {
    throw const InvalidPatientIdException();
  }
  return ref.read(patientRepositoryProvider).getPatient(uuid);
});

String? _parseUuid(String value) {
  final normalized = value.trim();
  final uuidPattern = RegExp(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
  );
  return uuidPattern.hasMatch(normalized) ? normalized : null;
}
