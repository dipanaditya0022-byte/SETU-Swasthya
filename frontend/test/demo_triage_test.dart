import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/models/demo_triage.dart';
import 'package:setu_swasthya/prototype/models/triage.dart';

void main() {
  test('synthetic triage rule has four deterministic outcomes', () {
    final now = DateTime(2026, 9, 22);
    TriageDecision decide({
      Map<String, num> vitals = const {},
      List<String> dangerSigns = const [],
      List<String> symptoms = const [],
    }) => demoTriageDecision(
      vitals: vitals,
      dangerSigns: dangerSigns,
      symptoms: symptoms,
      now: now,
    );

    expect(decide().disposition, TriageDisposition.manageHere);
    expect(
      decide(symptoms: ['cough']).disposition,
      TriageDisposition.teleconsult,
    );
    expect(
      decide(vitals: {'temperature': 39}).disposition,
      TriageDisposition.refer,
    );
    final emergency = decide(dangerSigns: ['synthetic sign']);
    expect(emergency.disposition, TriageDisposition.emergency);
    expect(emergency.urgency, TriageUrgency.immediate);
    expect(emergency.reason, contains('Synthetic'));
  });
}
