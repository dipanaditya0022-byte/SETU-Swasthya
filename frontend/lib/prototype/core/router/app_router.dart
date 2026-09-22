import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../screens/dashboard/dashboard_screen.dart';
import '../../screens/home/home_screen.dart';
import '../../screens/login/login_screen.dart';
import '../../screens/patient/patient_screen.dart';
import '../../screens/referral/referral_screen.dart';
import '../../screens/registry/registry_screen.dart';
import '../../screens/registry/register_patient_screen.dart';
import '../../screens/reports/reports_screen.dart';
import '../../screens/settings/settings_screen.dart';
import '../../screens/triage/triage_screen.dart';
import '../widgets/authenticated_shell.dart';
import '../../../screens/home_screen.dart' as team;
import '../../../screens/login_screen.dart' as team_auth;

abstract final class AppRouter {
  static final router = GoRouter(
    initialLocation: '/login',
    routes: [
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(
        path: '/team',
        builder: (context, state) => const team.HomeScreen(),
      ),
      GoRoute(
        path: '/team/login',
        builder: (context, state) => const team_auth.LoginScreen(),
      ),
      ShellRoute(
        builder: (context, state, child) => AuthenticatedShell(child: child),
        routes: [
          GoRoute(
            path: '/home',
            builder: (context, state) => const HomeScreen(),
          ),
          GoRoute(
            path: '/registry',
            builder: (context, state) => const RegistryScreen(),
          ),
          GoRoute(
            path: '/registry/register',
            builder: (context, state) => const RegisterPatientScreen(),
          ),
          GoRoute(
            path: '/patient/:id',
            builder: (context, state) =>
                PatientScreen(patientId: state.pathParameters['id']!),
          ),
          GoRoute(
            path: '/triage',
            builder: (context, state) => const TriageScreen(),
          ),
          GoRoute(
            path: '/referral',
            builder: (context, state) => const ReferralScreen(),
          ),
          GoRoute(
            path: '/dashboard',
            builder: (context, state) => const DashboardScreen(),
          ),
          GoRoute(
            path: '/reports',
            builder: (context, state) => const ReportsScreen(),
          ),
          GoRoute(
            path: '/settings',
            builder: (context, state) => const SettingsScreen(),
          ),
        ],
      ),
    ],
    errorBuilder: (context, state) => Scaffold(
      body: Center(child: Text('Page not found: ${state.uri.path}')),
    ),
  );
}
