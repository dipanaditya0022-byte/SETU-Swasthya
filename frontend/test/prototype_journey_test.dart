import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:setu_swasthya/prototype/app.dart';
import 'package:setu_swasthya/prototype/core/router/app_router.dart';
import 'package:setu_swasthya/prototype/providers/prototype_session_provider.dart';

Future<void> tapCentered(WidgetTester tester, Finder finder) async {
  await Scrollable.ensureVisible(
    tester.element(finder),
    alignment: 0.5,
    duration: Duration.zero,
  );
  await tester.pumpAndSettle();
  await tester.tap(finder);
}

void main() {
  testWidgets('synthetic email OTP to dashboard journey', (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(const SetuSwasthyaApp());
    AppRouter.router.go('/login');
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const ValueKey('email-field')),
      'demo@gmail.com',
    );
    await tester.tap(find.byKey(const ValueKey('send-otp-button')));
    await tester.pump();
    expect(find.textContaining('Synthetic OTP: 123456'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('otp-field')), '111111');
    await tapCentered(tester, find.byKey(const ValueKey('verify-otp-button')));
    await tester.pump();
    expect(find.textContaining('Wrong demo OTP'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('otp-field')), '123456');
    await tapCentered(tester, find.byKey(const ValueKey('verify-otp-button')));
    await tester.pumpAndSettle();
    expect(find.text('Home'), findsAtLeastNWidgets(1));
    expect(find.text('DEMO MODE'), findsOneWidget);

    await tapCentered(
      tester,
      find.byKey(const ValueKey('home-action-/registry')),
    );
    await tester.pumpAndSettle();
    expect(find.text('Patient Registry'), findsOneWidget);
    await tapCentered(
      tester,
      find.byKey(const ValueKey('registry-register-button')),
    );
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('registration-full-name')),
      'Synthetic Asha',
    );
    await tester.enterText(
      find.byKey(const ValueKey('registration-age')),
      '28',
    );
    expect(
      find.byKey(const ValueKey('registration-request-otp')),
      findsNothing,
    );
    await tester.enterText(
      find.byKey(const ValueKey('registration-village-code')),
      'DEMO-1',
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('registration-gender')),
    );
    await tester.tap(find.byKey(const ValueKey('registration-gender')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('FEMALE').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('registration-consent-mode')),
    );
    await tester.tap(find.byKey(const ValueKey('registration-consent-mode')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('digitalSelf').last);
    await tester.pumpAndSettle();
    final register = find.byKey(const ValueKey('registration-save-button'));
    await tapCentered(tester, register);
    await tester.pumpAndSettle();
    expect(find.text('Synthetic prototype patient'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('patient-profile-back')));
    await tester.pumpAndSettle();
    expect(find.text('Patient Registry'), findsOneWidget);
    expect(find.text('Synthetic Asha'), findsOneWidget);
    await tapCentered(tester, find.text('Synthetic Asha'));
    await tester.pumpAndSettle();
    expect(find.text('Synthetic prototype patient'), findsOneWidget);

    await tester.tap(find.text('Start triage'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('triage-temperature')),
      '39.2',
    );
    final evaluate = find.byKey(const ValueKey('triage-submit-button'));
    await tapCentered(tester, evaluate);
    await tester.pumpAndSettle();
    expect(find.text('Demo triage decision'), findsOneWidget);
    expect(find.text('Disposition: Refer'), findsOneWidget);
    await tapCentered(tester, find.text('Create Referral'));
    await tester.pumpAndSettle();

    final destination = find.byKey(
      const ValueKey('referral-destination-facility-id'),
    );
    await tapCentered(tester, destination);
    await tester.pumpAndSettle();
    await tester.tap(find.text('District Hospital').last);
    await tester.pumpAndSettle();
    final create = find.byKey(const ValueKey('referral-create-button'));
    await tapCentered(tester, create);
    await tester.pumpAndSettle();
    expect(find.text('Referral created'), findsOneWidget);
    expect(find.textContaining('REF-'), findsAtLeastNWidgets(1));
    expect(tester.widget<FilledButton>(create).onPressed, isNull);
    final status = find.byKey(const ValueKey('referral-status-dropdown'));
    await tapCentered(tester, status);
    await tester.pumpAndSettle();
    await tester.tap(find.text('ARRIVED').last);
    await tester.pumpAndSettle();
    final update = find.byKey(const ValueKey('referral-update-status-button'));
    await tapCentered(tester, update);
    await tester.pumpAndSettle();
    expect(find.textContaining('Current demo status: ARRIVED'), findsOneWidget);
    await tapCentered(tester, find.text('Open Dashboard'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Demo summary'), findsOneWidget);
    expect(find.text('Registered patients'), findsOneWidget);
    expect(find.text('Triage completed today'), findsOneWidget);
    expect(find.text('Open referrals'), findsOneWidget);
    expect(find.text('ARRIVED referrals'), findsOneWidget);
    expect(find.text('Breached referrals'), findsOneWidget);
  }, skip: !prototypeDemoMode);
}
