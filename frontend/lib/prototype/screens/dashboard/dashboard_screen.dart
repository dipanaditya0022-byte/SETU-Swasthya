import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_exception.dart';
import '../../models/dashboard.dart';
import '../../models/referral.dart';
import '../../providers/dashboard_providers.dart';
import '../../providers/prototype_session_provider.dart';
import '../../providers/sync_providers.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(prototypeSessionProvider);
    if (prototypeDemoMode) {
      return _DashboardContent(data: _DashboardViewData.demo(session));
    }

    final dashboard = ref.watch(dashboardProvider);
    return dashboard.when(
      loading: () => const _DashboardLoading(),
      data: (response) {
        final connectivity = ref.watch(connectivityStateProvider);
        final online = connectivity.when(
          data: (value) => value,
          loading: () => true,
          error: (_, _) => false,
        );
        final sync = ref.watch(syncControllerProvider);
        return _DashboardContent(
          data: _DashboardViewData.live(
            response,
            online: online,
            lastSynchronizedAt: sync.lastSynchronizedAt,
          ),
        );
      },
      error: (error, _) => _DashboardError(
        error: error,
        onRetry: () => ref.invalidate(dashboardProvider),
      ),
    );
  }
}

class _DashboardViewData {
  const _DashboardViewData({
    required this.facilityName,
    required this.status,
    required this.statusColor,
    required this.summaryLabel,
    required this.registeredPatients,
    required this.triageCompleted,
    required this.openReferrals,
    required this.arrivedReferrals,
    required this.breachedReferrals,
    required this.triageDispositions,
    required this.referralStatuses,
    required this.recentActivity,
    required this.lastSynchronized,
    required this.backendSnapshot,
    required this.hasRecords,
    required this.isDemo,
    this.emergencyReferrals,
  });

  factory _DashboardViewData.demo(PrototypeSession session) {
    final disposition = _canonicalDisposition(
      session.triage?.triageDisposition ??
          session.triage?.decision.disposition.name,
    );
    final triageCounts = <String, int?>{
      'Manage Here': disposition == 'MANAGE_HERE' ? 1 : 0,
      'Teleconsult': disposition == 'TELECONSULT' ? 1 : 0,
      'Refer': disposition == 'REFER' ? 1 : 0,
      'Emergency': disposition == 'EMERGENCY' ? 1 : 0,
    };
    final currentReferralStatus = session.referralStatus;
    final referralStatuses = <String, int?>{
      'Initiated': currentReferralStatus == ReferralState.initiated ? 1 : 0,
      'Arrived': currentReferralStatus == ReferralState.arrived ? 1 : 0,
      'Closed': currentReferralStatus == ReferralState.closed ? 1 : 0,
      'Cancelled': currentReferralStatus == ReferralState.cancelled ? 1 : 0,
    };
    final activity = <String>[
      if (session.referral != null)
        'Referral ${session.referral!.id ?? ''} is ${currentReferralStatus == null ? 'created' : referralStateValue(currentReferralStatus)}.',
      if (session.triage != null)
        'Triage completed with ${disposition.replaceAll('_', ' ').toLowerCase()} disposition.',
      if (session.patients.isNotEmpty)
        '${session.patients.last.name} registered in this demo session.',
    ];

    return _DashboardViewData(
      facilityName: session.selectedPatient?.facilityId ?? 'Demo facility',
      status: 'Demo',
      statusColor: const Color(0xFFEF6C00),
      summaryLabel: 'Demo summary — synthetic session data',
      registeredPatients: session.registeredPatients,
      triageCompleted: session.triageCompletedToday,
      openReferrals: session.openReferrals,
      arrivedReferrals: session.arrivedReferrals,
      breachedReferrals: session.breachedReferrals,
      emergencyReferrals: triageCounts['Emergency'],
      triageDispositions: triageCounts,
      referralStatuses: referralStatuses,
      recentActivity: activity,
      lastSynchronized: 'Not applicable in demo mode',
      backendSnapshot: null,
      hasRecords:
          session.registeredPatients > 0 ||
          session.triage != null ||
          session.referral != null,
      isDemo: true,
    );
  }

  factory _DashboardViewData.live(
    DashboardResponse response, {
    required bool online,
    required DateTime? lastSynchronizedAt,
  }) => _DashboardViewData(
    facilityName: response.facilityName,
    status: online ? 'Live' : 'Offline',
    statusColor: online ? const Color(0xFF21643D) : const Color(0xFFB3261E),
    summaryLabel: 'Facility dashboard — live backend data',
    registeredPatients: response.registeredPatients,
    triageCompleted: response.triageCompleted,
    openReferrals: response.openReferrals,
    arrivedReferrals: response.arrivedReferrals,
    breachedReferrals: response.breachedReferrals,
    triageDispositions: const {
      'Manage Here': null,
      'Teleconsult': null,
      'Refer': null,
      'Emergency': null,
    },
    referralStatuses: {
      'Open': response.openReferrals,
      'Arrived': response.arrivedReferrals,
      'Breached': response.breachedReferrals,
    },
    recentActivity: const [],
    lastSynchronized: lastSynchronizedAt == null
        ? 'Not yet synchronized'
        : _dateTimeLabel(lastSynchronizedAt),
    backendSnapshot: response.generatedAt == null
        ? null
        : _dateTimeLabel(response.generatedAt!),
    hasRecords: response.hasRecords,
    isDemo: false,
  );

  final String facilityName;
  final String status;
  final Color statusColor;
  final String summaryLabel;
  final int? registeredPatients;
  final int? triageCompleted;
  final int? openReferrals;
  final int? arrivedReferrals;
  final int? breachedReferrals;
  final int? emergencyReferrals;
  final Map<String, int?> triageDispositions;
  final Map<String, int?> referralStatuses;
  final List<String> recentActivity;
  final String lastSynchronized;
  final String? backendSnapshot;
  final bool hasRecords;
  final bool isDemo;

  bool get hasWarning =>
      (breachedReferrals ?? 0) > 0 || (emergencyReferrals ?? 0) > 0;
}

class _DashboardContent extends StatelessWidget {
  const _DashboardContent({required this.data});

  final _DashboardViewData data;

  @override
  Widget build(BuildContext context) => SafeArea(
    child: SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 20, 16, 32),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 920),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _DashboardHeader(data: data),
              if (data.hasWarning) ...[
                const SizedBox(height: 16),
                _WarningCard(data: data),
              ],
              const SizedBox(height: 20),
              _SummaryGrid(data: data),
              if (!data.hasRecords) ...[
                const SizedBox(height: 16),
                const _EmptyState(),
              ],
              const SizedBox(height: 20),
              _DispositionSection(values: data.triageDispositions),
              const SizedBox(height: 16),
              _ReferralStatusSection(values: data.referralStatuses),
              const SizedBox(height: 16),
              _RecentActivitySection(
                activity: data.recentActivity,
                liveData: !data.isDemo,
              ),
              if (!data.isDemo) ...[
                const SizedBox(height: 16),
                const _SyncPanel(),
              ],
            ],
          ),
        ),
      ),
    ),
  );
}

class _DashboardHeader extends StatelessWidget {
  const _DashboardHeader({required this.data});

  final _DashboardViewData data;

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(
                Icons.local_hospital_outlined,
                color: Color(0xFF075965),
                size: 30,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      data.facilityName,
                      key: const ValueKey('dashboard-facility-name'),
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 4),
                    Text(data.summaryLabel),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              _StatusBadge(label: data.status, color: data.statusColor),
            ],
          ),
          const SizedBox(height: 16),
          Text('Last synchronized: ${data.lastSynchronized}'),
          if (data.backendSnapshot != null)
            Text('Backend snapshot: ${data.backendSnapshot}'),
        ],
      ),
    ),
  );
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: color.withValues(alpha: 0.35)),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.circle, color: color, size: 9),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(color: color, fontWeight: FontWeight.w700),
        ),
      ],
    ),
  );
}

class _WarningCard extends StatelessWidget {
  const _WarningCard({required this.data});

  final _DashboardViewData data;

  @override
  Widget build(BuildContext context) {
    final parts = <String>[
      if ((data.breachedReferrals ?? 0) > 0)
        '${data.breachedReferrals} breached referral${data.breachedReferrals == 1 ? '' : 's'}',
      if ((data.emergencyReferrals ?? 0) > 0)
        '${data.emergencyReferrals} emergency referral${data.emergencyReferrals == 1 ? '' : 's'}',
    ];
    return Card(
      margin: EdgeInsets.zero,
      color: const Color(0xFFFFEDEA),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.warning_amber_rounded, color: Color(0xFFB3261E)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Attention required',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      color: const Color(0xFF8C1D18),
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text('${parts.join(' and ')} need follow-up.'),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SummaryGrid extends StatelessWidget {
  const _SummaryGrid({required this.data});

  final _DashboardViewData data;

  @override
  Widget build(BuildContext context) {
    final cards = [
      ('Registered patients', data.registeredPatients, Icons.people_outline),
      (
        'Triage completed today',
        data.triageCompleted,
        Icons.health_and_safety_outlined,
      ),
      ('Open referrals', data.openReferrals, Icons.call_made_outlined),
      ('ARRIVED referrals', data.arrivedReferrals, Icons.login_outlined),
      (
        'Breached referrals',
        data.breachedReferrals,
        Icons.warning_amber_outlined,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 760
            ? 3
            : constraints.maxWidth >= 480
            ? 2
            : 1;
        final width = (constraints.maxWidth - ((columns - 1) * 12)) / columns;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final card in cards)
              SizedBox(
                width: width,
                child: _MetricCard(
                  label: card.$1,
                  value: card.$2,
                  icon: card.$3,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final int? value;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: const Color(0xFFEAF4F5),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(icon, color: const Color(0xFF075965)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _metricValue(value),
                  style: Theme.of(context).textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 2),
                Text(label, maxLines: 2, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class _DispositionSection extends StatelessWidget {
  const _DispositionSection({required this.values});

  final Map<String, int?> values;

  static const _colors = {
    'Manage Here': Color(0xFF2E7D32),
    'Teleconsult': Color(0xFFF9A825),
    'Refer': Color(0xFFEF6C00),
    'Emergency': Color(0xFFC62828),
  };

  @override
  Widget build(BuildContext context) => _SectionCard(
    title: 'Triage disposition',
    child: LayoutBuilder(
      builder: (context, constraints) => Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          for (final entry in values.entries)
            SizedBox(
              width: constraints.maxWidth >= 620
                  ? (constraints.maxWidth - 30) / 4
                  : constraints.maxWidth >= 360
                  ? (constraints.maxWidth - 10) / 2
                  : constraints.maxWidth,
              child: _ColoredMetric(
                label: entry.key,
                value: entry.value,
                color: _colors[entry.key]!,
              ),
            ),
        ],
      ),
    ),
  );
}

class _ColoredMetric extends StatelessWidget {
  const _ColoredMetric({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final int? value;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.08),
      borderRadius: BorderRadius.circular(9),
      border: Border(left: BorderSide(color: color, width: 4)),
    ),
    child: Row(
      children: [
        Expanded(child: Text(label, overflow: TextOverflow.ellipsis)),
        const SizedBox(width: 6),
        Text(
          _metricValue(value),
          style: TextStyle(
            color: color,
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
      ],
    ),
  );
}

class _ReferralStatusSection extends StatelessWidget {
  const _ReferralStatusSection({required this.values});

  final Map<String, int?> values;

  @override
  Widget build(BuildContext context) => _SectionCard(
    title: 'Referral status summary',
    child: Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final entry in values.entries)
          Chip(
            avatar: CircleAvatar(
              backgroundColor: const Color(0xFF075965),
              foregroundColor: Colors.white,
              child: Text(_metricValue(entry.value)),
            ),
            label: Text(entry.key),
          ),
      ],
    ),
  );
}

class _RecentActivitySection extends StatelessWidget {
  const _RecentActivitySection({
    required this.activity,
    required this.liveData,
  });

  final List<String> activity;
  final bool liveData;

  @override
  Widget build(BuildContext context) => _SectionCard(
    title: 'Recent activity',
    child: activity.isEmpty
        ? Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.history, color: Color(0xFF687477)),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  liveData
                      ? 'Recent activity is not included in the current facility dashboard response.'
                      : 'No recent activity in this synthetic session.',
                ),
              ),
            ],
          )
        : Column(
            children: [
              for (var index = 0; index < activity.length; index++) ...[
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(
                    Icons.check_circle_outline,
                    color: Color(0xFF21643D),
                  ),
                  title: Text(activity[index]),
                ),
                if (index < activity.length - 1) const Divider(height: 1),
              ],
            ],
          ),
  );
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 14),
          child,
        ],
      ),
    ),
  );
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: const Padding(
      padding: EdgeInsets.all(24),
      child: Column(
        children: [
          Icon(Icons.inbox_outlined, size: 42, color: Color(0xFF687477)),
          SizedBox(height: 10),
          Text(
            'No records for this dashboard period.',
            textAlign: TextAlign.center,
          ),
        ],
      ),
    ),
  );
}

class _SyncPanel extends ConsumerWidget {
  const _SyncPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(syncControllerProvider);
    return _SectionCard(
      title: 'Local synchronization',
      child: LayoutBuilder(
        builder: (context, constraints) {
          final details = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                state.isSyncing
                    ? 'Syncing pending records...'
                    : '${state.pendingCount} pending record${state.pendingCount == 1 ? '' : 's'}',
              ),
              if (state.message != null) Text(state.message!),
            ],
          );
          final button = FilledButton.tonalIcon(
            key: const ValueKey('sync-now-button'),
            onPressed: state.isSyncing
                ? null
                : () => ref.read(syncControllerProvider.notifier).syncNow(),
            icon: const Icon(Icons.sync),
            label: const Text('Sync now'),
          );
          if (constraints.maxWidth < 420) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [details, const SizedBox(height: 12), button],
            );
          }
          return Row(
            children: [
              Expanded(child: details),
              const SizedBox(width: 12),
              button,
            ],
          );
        },
      ),
    );
  }
}

class _DashboardLoading extends StatelessWidget {
  const _DashboardLoading();

  @override
  Widget build(BuildContext context) => SafeArea(
    child: ListView(
      padding: const EdgeInsets.all(20),
      children: const [
        Text(
          'Loading dashboard...',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
        ),
        SizedBox(height: 12),
        LinearProgressIndicator(),
        SizedBox(height: 20),
        _SkeletonBox(height: 110),
        SizedBox(height: 12),
        _SkeletonBox(height: 92),
        SizedBox(height: 12),
        _SkeletonBox(height: 160),
      ],
    ),
  );
}

class _SkeletonBox extends StatelessWidget {
  const _SkeletonBox({required this.height});

  final double height;

  @override
  Widget build(BuildContext context) => Container(
    height: height,
    decoration: BoxDecoration(
      color: const Color(0xFFE9EEF0),
      borderRadius: BorderRadius.circular(10),
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
      ) => 'Your session is not authorized to view this facility dashboard.',
      ClientApiException(statusCode: 404) =>
        'Dashboard not found for this org unit.',
      ClientApiException() => 'The dashboard request was not accepted.',
      NoInternetException() =>
        'You are offline. Reconnect and retry the dashboard request.',
      ApiTimeoutException() =>
        'The dashboard request timed out. Please try again.',
      ServerApiException() =>
        'Something went wrong on the server. Please try again.',
      _ => 'Unable to load the dashboard. Please try again.',
    };
    return SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Card(
              color: const Color(0xFFFFF4F2),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'Dashboard',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 16),
                    const Icon(
                      Icons.error_outline,
                      size: 44,
                      color: Color(0xFFB3261E),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Dashboard unavailable',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 8),
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
          ),
        ),
      ),
    );
  }
}

String _metricValue(int? value) => value?.toString() ?? '—';

String _canonicalDisposition(String? value) {
  final normalized = value
      ?.trim()
      .replaceAll(RegExp(r'([a-z])([A-Z])'), r'$1_$2')
      .replaceAll(' ', '_')
      .toUpperCase();
  return switch (normalized) {
    'MANAGEHERE' => 'MANAGE_HERE',
    'MANAGE_HERE' => 'MANAGE_HERE',
    'TELECONSULT' => 'TELECONSULT',
    'REFER' => 'REFER',
    'EMERGENCY' => 'EMERGENCY',
    _ => '',
  };
}

String _dateTimeLabel(DateTime value) {
  final local = value.toLocal();
  String two(int number) => number.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)}/${local.year} '
      '${two(local.hour)}:${two(local.minute)}';
}
