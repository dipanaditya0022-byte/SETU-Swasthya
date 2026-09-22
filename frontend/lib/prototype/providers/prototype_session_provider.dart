import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/patient.dart';
import '../models/referral.dart';
import '../models/triage.dart';

const prototypeDemoMode = bool.fromEnvironment(
  'DEMO_MODE',
  defaultValue: false,
);
const prototypeApiBaseUrl = String.fromEnvironment('API_BASE_URL');

class PrototypeSession {
  const PrototypeSession({
    this.patients = const [],
    this.selectedPatientId,
    this.triage,
    this.referral,
    this.referralStatus,
    this.isDemo = prototypeDemoMode,
  });

  final List<Patient> patients;
  final String? selectedPatientId;
  final TriageEvaluationResponse? triage;
  final Referral? referral;
  final ReferralState? referralStatus;
  final bool isDemo;

  Patient? get selectedPatient {
    for (final patient in patients) {
      if (patient.id == selectedPatientId) return patient;
    }
    return null;
  }

  int get registeredPatients => patients.length;
  int get triageCompletedToday =>
      triage != null &&
          triage!.createdAt.year == DateTime.now().year &&
          triage!.createdAt.month == DateTime.now().month &&
          triage!.createdAt.day == DateTime.now().day
      ? 1
      : 0;
  int get openReferrals =>
      referral != null &&
          referralStatus != ReferralState.closed &&
          referralStatus != ReferralState.cancelled
      ? 1
      : 0;
  int get arrivedReferrals => referralStatus == ReferralState.arrived ? 1 : 0;
  int get breachedReferrals => 0;
}

final prototypeSessionProvider =
    NotifierProvider<PrototypeSessionController, PrototypeSession>(
      PrototypeSessionController.new,
    );

class PrototypeSessionController extends Notifier<PrototypeSession> {
  @override
  PrototypeSession build() => const PrototypeSession();

  void addPatient(Patient patient, {required bool demo}) {
    state = PrototypeSession(
      patients: [...state.patients, patient],
      selectedPatientId: patient.id,
      isDemo: demo,
    );
  }

  void selectPatient(String patientId) {
    state = PrototypeSession(
      patients: state.patients,
      selectedPatientId: patientId,
      isDemo: state.isDemo,
    );
  }

  void setTriage(TriageEvaluationResponse response) {
    state = PrototypeSession(
      patients: state.patients,
      selectedPatientId: response.patientId,
      triage: response,
      isDemo: state.isDemo,
    );
  }

  void setReferral(Referral referral) {
    state = PrototypeSession(
      patients: state.patients,
      selectedPatientId: referral.patientId,
      triage: state.triage,
      referral: referral,
      referralStatus: referral.status,
      isDemo: state.isDemo,
    );
  }

  void setReferralStatus(ReferralState status) {
    state = PrototypeSession(
      patients: state.patients,
      selectedPatientId: state.selectedPatientId,
      triage: state.triage,
      referral: state.referral,
      referralStatus: status,
      isDemo: state.isDemo,
    );
  }
}
