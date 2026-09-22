import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/models/demo_triage.dart';
import 'package:setu_swasthya/prototype/models/patient.dart';
import 'package:setu_swasthya/prototype/models/referral.dart';
import 'package:setu_swasthya/prototype/models/triage.dart';
import 'package:setu_swasthya/prototype/providers/prototype_session_provider.dart';
import 'package:setu_swasthya/prototype/screens/dashboard/dashboard_screen.dart';

const patientId = '123e4567-e89b-42d3-a456-426614174000';
const facilityId = '123e4567-e89b-42d3-a456-426614174001';

void main() {
  testWidgets('demo dashboard starts at zero and reacts to session changes', (
    tester,
  ) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: DashboardScreen()),
      ),
    );
    await tester.pump();
    expect(find.textContaining('Demo summary'), findsOneWidget);
    expect(find.text('Loading dashboard...'), findsNothing);

    void count(String label, String value) {
      final card = find.ancestor(
        of: find.text(label),
        matching: find.byType(Card),
      );
      expect(
        find.descendant(of: card, matching: find.text(value)),
        findsOneWidget,
      );
    }

    count('Registered patients', '0');
    count('Triage completed today', '0');
    count('Open referrals', '0');
    count('ARRIVED referrals', '0');
    count('Breached referrals', '0');

    container
        .read(prototypeSessionProvider.notifier)
        .addPatient(
          const Patient(
            id: patientId,
            name: 'Synthetic Asha',
            age: 28,
            village: 'Demo village',
            facilityId: facilityId,
          ),
          demo: true,
        );
    await tester.pump();
    count('Registered patients', '1');

    final now = DateTime.now();
    container
        .read(prototypeSessionProvider.notifier)
        .setTriage(
          TriageEvaluationResponse(
            id: '123e4567-e89b-42d3-a456-426614174005',
            patientId: patientId,
            facilityId: facilityId,
            triageDisposition: 'refer',
            createdAt: now,
            decision: demoTriageDecision(
              vitals: const {'temperature': 39.2},
              dangerSigns: const [],
              symptoms: const [],
              now: now,
            ),
          ),
        );
    await tester.pump();
    count('Triage completed today', '1');

    container
        .read(prototypeSessionProvider.notifier)
        .setReferral(
          const Referral(
            id: '123e4567-e89b-42d3-a456-426614174006',
            patientId: patientId,
            fromFacilityId: facilityId,
            destinationFacilityId: '123e4567-e89b-42d3-a456-426614174002',
            reason: 'Synthetic scenario',
            urgency: 'WITHIN_24H',
          ),
        );
    await tester.pump();
    count('Open referrals', '1');
    count('ARRIVED referrals', '0');

    container
        .read(prototypeSessionProvider.notifier)
        .setReferralStatus(ReferralState.arrived);
    await tester.pump();
    count('Open referrals', '1');
    count('ARRIVED referrals', '1');
    count('Breached referrals', '0');
  }, skip: !prototypeDemoMode);
}
