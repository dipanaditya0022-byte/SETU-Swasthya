import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../providers/prototype_session_provider.dart';

class AuthenticatedShell extends StatelessWidget {
  const AuthenticatedShell({required this.child, super.key});

  final Widget child;

  static const _destinations = [
    ('/home', 'Home', Icons.home_outlined),
    ('/registry', 'Registry', Icons.people_outline),
    ('/dashboard', 'Dashboard', Icons.dashboard_outlined),
  ];

  @override
  Widget build(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;
    var selectedIndex = _destinations.indexWhere(
      (destination) =>
          location == destination.$1 ||
          location.startsWith('${destination.$1}/'),
    );
    final isPatientProfile = location.startsWith('/patient/');
    if (isPatientProfile) {
      selectedIndex = 1;
    }

    return Scaffold(
      appBar: AppBar(
        leading: isPatientProfile
            ? IconButton(
                key: const ValueKey('patient-profile-back'),
                onPressed: () => context.go('/registry'),
                tooltip: 'Back',
                icon: const Icon(Icons.arrow_back),
              )
            : null,
        title: Text(isPatientProfile ? 'Patient Profile' : 'SETU-Swasthya'),
        actions: prototypeDemoMode
            ? [
                Center(
                  child: Padding(
                    padding: const EdgeInsets.only(right: 12),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: Colors.deepOrange,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Padding(
                        padding: EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 4,
                        ),
                        child: Text(
                          'DEMO MODE',
                          style: TextStyle(color: Colors.white, fontSize: 11),
                        ),
                      ),
                    ),
                  ),
                ),
              ]
            : null,
      ),
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex < 0 ? 0 : selectedIndex,
        onDestinationSelected: (index) => context.go(_destinations[index].$1),
        destinations: [
          for (final destination in _destinations)
            NavigationDestination(
              icon: Icon(destination.$3),
              label: destination.$2,
            ),
        ],
      ),
    );
  }
}
