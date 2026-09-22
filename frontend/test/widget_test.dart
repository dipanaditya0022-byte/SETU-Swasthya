import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:setu_swasthya/prototype/app.dart';
import 'package:setu_swasthya/prototype/core/router/app_router.dart';

Future<void> pumpLoginScreen(WidgetTester tester) async {
  await tester.pumpWidget(const SetuSwasthyaApp());
  AppRouter.router.go('/login');
  await tester.pumpAndSettle();
}

Future<void> pumpHomeScreen(WidgetTester tester) async {
  await tester.pumpWidget(const SetuSwasthyaApp());
  AppRouter.router.go('/home');
  await tester.pumpAndSettle();
}

Future<void> pumpRegistryScreen(WidgetTester tester) async {
  await tester.pumpWidget(const SetuSwasthyaApp());
  AppRouter.router.go('/registry');
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('live mode starts with mobile authentication only', (
    WidgetTester tester,
  ) async {
    await pumpLoginScreen(tester);

    expect(find.text('Welcome to SETU-Swasthya'), findsOneWidget);
    expect(find.text('Mobile Number'), findsOneWidget);
    expect(find.text('Send OTP'), findsOneWidget);
    expect(find.byKey(const ValueKey('email-field')), findsNothing);
    expect(find.text('STAFF SIGN UP'), findsNothing);
    expect(find.text('Six-digit OTP'), findsNothing);
  });

  testWidgets('live login rejects a mobile without international format', (
    WidgetTester tester,
  ) async {
    await pumpLoginScreen(tester);
    await tester.enterText(find.byType(TextFormField), '9000000106');
    await tester.tap(find.text('Send OTP'));
    await tester.pump();
    expect(
      find.text('Use international format, for example +919000000106'),
      findsOneWidget,
    );
  });

  testWidgets('live login shows validation feedback for empty mobile', (
    WidgetTester tester,
  ) async {
    await pumpLoginScreen(tester);
    await tester.tap(find.text('Send OTP'));
    await tester.pump();
    expect(find.text('Please enter your mobile number'), findsOneWidget);
  });

  testWidgets('live login does not expose password or email inputs', (
    WidgetTester tester,
  ) async {
    await pumpLoginScreen(tester);

    expect(find.text('Password'), findsNothing);
    expect(find.text('Email address'), findsNothing);
    expect(find.byKey(const ValueKey('email-field')), findsNothing);
  });

  testWidgets('renders Home content and empty activity state', (
    WidgetTester tester,
  ) async {
    await pumpHomeScreen(tester);

    expect(find.text('Good morning'), findsOneWidget);
    expect(find.text('Workspace ready'), findsOneWidget);
    expect(find.text('READY'), findsOneWidget);
    expect(find.text("Today's overview"), findsOneWidget);
    expect(find.text('Quick actions'), findsOneWidget);
    expect(find.text('No recent activity'), findsOneWidget);
  });

  testWidgets('shows all Home quick actions', (WidgetTester tester) async {
    await pumpHomeScreen(tester);

    expect(find.text('Register Patient'), findsAtLeastNWidgets(1));
    expect(find.text('Start Triage'), findsOneWidget);
    expect(find.text('Create Referral'), findsOneWidget);
  });

  testWidgets('Register Patient action navigates to Registry', (
    WidgetTester tester,
  ) async {
    await pumpHomeScreen(tester);

    final action = find.byKey(const ValueKey('home-action-/registry'));
    await tester.ensureVisible(action);
    await tester.tap(action);
    await tester.pumpAndSettle();

    expect(find.text('Patient Registry'), findsOneWidget);
  });

  testWidgets('Start Triage action navigates to Triage', (
    WidgetTester tester,
  ) async {
    await pumpHomeScreen(tester);

    final action = find.byKey(const ValueKey('home-action-/triage'));
    await tester.ensureVisible(action);
    await tester.tap(action);
    await tester.pumpAndSettle();

    expect(find.text('Triage'), findsOneWidget);
  });

  testWidgets('Create Referral action navigates to Referral', (
    WidgetTester tester,
  ) async {
    await pumpHomeScreen(tester);

    final action = find.byKey(const ValueKey('home-action-/referral'));
    await tester.ensureVisible(action);
    await tester.tap(action);
    await tester.pumpAndSettle();

    expect(find.text('Referral'), findsOneWidget);
  });

  testWidgets('renders the Registry empty state and controls', (
    WidgetTester tester,
  ) async {
    await pumpRegistryScreen(tester);

    expect(find.text('Patient Registry'), findsOneWidget);
    expect(find.byKey(const ValueKey('registry-search-field')), findsOneWidget);
    expect(find.text('All'), findsOneWidget);
    expect(find.text('Recent'), findsOneWidget);
    expect(find.text('Needs Triage'), findsOneWidget);
    expect(find.text('No patients yet'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('registry-register-button')),
      findsOneWidget,
    );
  });

  testWidgets('Registry Register Patient navigates to registration form', (
    WidgetTester tester,
  ) async {
    await pumpRegistryScreen(tester);

    final action = find.byKey(const ValueKey('registry-register-button'));
    await tester.ensureVisible(action);
    await tester.tap(action);
    await tester.pumpAndSettle();

    expect(find.text('Register Patient'), findsAtLeastNWidgets(1));
    expect(
      find.byKey(const ValueKey('registration-full-name')),
      findsOneWidget,
    );
    expect(
      tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
      1,
    );
  });

  testWidgets('registration form has required fields and validates', (
    WidgetTester tester,
  ) async {
    await pumpRegistryScreen(tester);
    final action = find.byKey(const ValueKey('registry-register-button'));
    await tester.ensureVisible(action);
    await tester.tap(action);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('registration-full-name')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('registration-date-of-birth')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('registration-gender')), findsOneWidget);
    expect(find.byKey(const ValueKey('registration-phone')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('registration-village-code')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('registration-language')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('registration-consent-mode')),
      findsOneWidget,
    );
    expect(find.textContaining('Live registration'), findsOneWidget);

    await tester.ensureVisible(
      find.byKey(const ValueKey('registration-save-button')),
    );
    await tester.tap(find.byKey(const ValueKey('registration-save-button')));
    await tester.pump();

    expect(find.text('Please enter Full name'), findsOneWidget);
    expect(find.text('Please select sex'), findsOneWidget);
    expect(find.text('Please enter mobile number'), findsOneWidget);
    expect(find.text('Please enter Village LGD code'), findsOneWidget);
    expect(find.text('Please select consent mode'), findsOneWidget);
  });

  testWidgets('dynamic patient route remains available', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SetuSwasthyaApp());
    AppRouter.router.go('/patient/test-id');
    await tester.pumpAndSettle();

    expect(find.text('Patient Profile'), findsOneWidget);
    expect(find.text('Patient ID is invalid.'), findsOneWidget);
  });

  testWidgets('Patient Profile renders neutral sections and actions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SetuSwasthyaApp());
    AppRouter.router.go('/patient/abc123');
    await tester.pumpAndSettle();

    expect(find.text('Patient Profile'), findsOneWidget);
    expect(find.text('Patient ID is invalid.'), findsOneWidget);
    expect(
      tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
      1,
    );
  });

  testWidgets('Patient Profile back navigation returns to Registry', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SetuSwasthyaApp());
    AppRouter.router.go('/registry');
    await tester.pumpAndSettle();
    AppRouter.router.go('/patient/abc123');
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('patient-profile-back')));
    await tester.pumpAndSettle();

    expect(find.text('Patient Registry'), findsOneWidget);
  });

  testWidgets('navigates through every foundation route', (
    WidgetTester tester,
  ) async {
    await pumpLoginScreen(tester);

    const routes = {
      '/home': 'Home',
      '/registry': 'Patient Registry',
      '/patient/abc123': 'Patient ID is invalid.',
      '/triage': 'Triage',
      '/referral': 'Referral',
      '/dashboard': 'Dashboard',
      '/reports': 'Reports',
      '/settings': 'Settings',
    };

    for (final route in routes.entries) {
      AppRouter.router.go(route.key);
      await tester.pumpAndSettle();
      expect(
        find.text(route.value),
        findsAtLeastNWidgets(1),
        reason: route.key,
      );
    }
  });
}
