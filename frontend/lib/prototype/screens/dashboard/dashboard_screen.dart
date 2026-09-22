import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_exception.dart';
import '../../models/dashboard.dart';
import '../../providers/dashboard_providers.dart';
import '../../providers/prototype_session_provider.dart';
import '../../providers/sync_providers.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(prototypeSessionProvider);
    if (prototypeDemoMode) return _DemoSummary(session: session);
    final dashboard = ref.watch(dashboardProvider);
    return dashboard.when(
      loading: () => const _DashboardState(
        title: 'Dashboard',
        message: 'Loading dashboard...',
        showProgress: true,
      ),
      data: (response) => _DashboardContent(response: response),
      error: (error, _) => _DashboardError(
        error: error,
        onRetry: () => ref.invalidate(dashboardProvider),
      ),
    );
  }
}

class _DemoSummary extends StatelessWidget {
  const _DemoSummary({required this.session});

  final PrototypeSession session;

  @override
  Widget build(BuildContext context) => SafeArea(
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Dashboard', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          const Text('Demo summary - Synthetic data from this session only'),
          const SizedBox(height: 20),
          _summaryCard('Registered patients', '${session.registeredPatients}'),
          _summaryCard(
            'Triage completed today',
            '${session.triageCompletedToday}',
          ),
          _summaryCard('Open referrals', '${session.openReferrals}'),
          _summaryCard('ARRIVED referrals', '${session.arrivedReferrals}'),
          _summaryCard('Breached referrals', '${session.breachedReferrals}'),
        ],
      ),
    ),
  );

  Widget _summaryCard(String label, String value) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
        ],
      ),
    ),
  );
}

class _DashboardContent extends StatelessWidget {
  const _DashboardContent({required this.response});

  final DashboardResponse response;

  @override
  Widget build(BuildContext context) {
    final isEmpty = response.raw.isEmpty;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Dashboard',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 6),
                Text(
                  'Facility dashboard data from the backend.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                const _SyncPanel(),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      children: [
                        Icon(
                          isEmpty
                              ? Icons.dashboard_outlined
                              : Icons.check_circle_outline,
                          size: 44,
                          color: Theme.of(context).colorScheme.primary,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          isEmpty
                              ? 'No dashboard fields are defined by the current API contract.'
                              : 'Dashboard response received.',
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        if (!isEmpty) ...[
                          const SizedBox(height: 8),
                          Text(
                            'The backend returned fields that are not documented in openapi.json, so they are not displayed.',
                            textAlign: TextAlign.center,
                            style: Theme.of(context).textTheme.bodyMedium,
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SyncPanel extends ConsumerWidget {
  const _SyncPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(syncControllerProvider);
    final message = state.message;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Local sync',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    state.isSyncing
                        ? 'Syncing pending records...'
                        : '${state.pendingCount} pending record${state.pendingCount == 1 ? '' : 's'}',
                  ),
                  if (message != null) Text(message),
                ],
              ),
            ),
            FilledButton.tonalIcon(
              key: const ValueKey('sync-now-button'),
              onPressed: state.isSyncing
                  ? null
                  : () => ref.read(syncControllerProvider.notifier).syncNow(),
              icon: const Icon(Icons.sync),
              label: const Text('Sync now'),
            ),
          ],
        ),
      ),
    );
  }
}

class _DashboardState extends StatelessWidget {
  const _DashboardState({
    required this.title,
    required this.message,
    this.showProgress = false,
  });

  final String title;
  final String message;
  final bool showProgress;

  @override
  Widget build(BuildContext context) => SafeArea(
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          if (showProgress) const CircularProgressIndicator(),
          if (showProgress) const SizedBox(height: 16),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(message, textAlign: TextAlign.center),
          ),
        ],
      ),
    ),
  );
}

class _DashboardError extends StatelessWidget {
  const _DashboardError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final message = switch (error) {
      DashboardConfigurationException() =>
        'Dashboard org unit ID is not configured.',
      ClientApiException(statusCode: 401) ||
      ClientApiException(
        statusCode: 403,
      ) => 'Authentication is required to view the dashboard.',
      ClientApiException(statusCode: 404) =>
        'Dashboard not found for this org unit.',
      ClientApiException() => 'The dashboard request was not accepted.',
      NoInternetException() =>
        'Unable to connect. Check your internet connection and try again.',
      ApiTimeoutException() =>
        'The dashboard request timed out. Please try again.',
      ServerApiException() =>
        'Something went wrong on the server. Please try again.',
      _ => 'Unable to load the dashboard. Please try again.',
    };
    return _DashboardStateWithRetry(message: message, onRetry: onRetry);
  }
}

class _DashboardStateWithRetry extends StatelessWidget {
  const _DashboardStateWithRetry({
    required this.message,
    required this.onRetry,
  });

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => SafeArea(
    child: Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Dashboard', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 16),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              key: const ValueKey('dashboard-retry-button'),
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    ),
  );
}
