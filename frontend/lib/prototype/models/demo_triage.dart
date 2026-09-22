import 'triage.dart';

/// Fixed synthetic scenarios for UI demonstration only; not clinical advice.
TriageDecision demoTriageDecision({
  required Map<String, num> vitals,
  required List<String> dangerSigns,
  required List<String> symptoms,
  required DateTime now,
}) {
  final TriageDisposition disposition;
  final TriageUrgency urgency;
  final String reason;
  if (dangerSigns.isNotEmpty) {
    disposition = TriageDisposition.emergency;
    urgency = TriageUrgency.immediate;
    reason = 'Synthetic scenario: a danger sign was entered.';
  } else if ((vitals['temperature'] ?? 0) >= 39) {
    disposition = TriageDisposition.refer;
    urgency = TriageUrgency.within24h;
    reason = 'Synthetic scenario: the entered temperature is 39 or higher.';
  } else if (symptoms.isNotEmpty) {
    disposition = TriageDisposition.teleconsult;
    urgency = TriageUrgency.routine;
    reason = 'Synthetic scenario: symptoms were entered.';
  } else {
    disposition = TriageDisposition.manageHere;
    urgency = TriageUrgency.routine;
    reason = 'Synthetic scenario: no demo trigger was entered.';
  }
  return TriageDecision(
    disposition: disposition,
    urgency: urgency,
    reason: reason,
    redFlags: dangerSigns,
    protocolVersion: 'demo',
    insufficientData: false,
    missingFields: const [],
    engine: TriageEngine.fallback,
    evaluatedAt: now,
  );
}
