import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: const [
                _HomeHeader(),
                SizedBox(height: 24),
                _ReadinessCard(),
                SizedBox(height: 28),
                _SectionHeading(title: "Today's overview"),
                SizedBox(height: 12),
                _OverviewGrid(),
                SizedBox(height: 28),
                _SectionHeading(title: 'Quick actions'),
                SizedBox(height: 12),
                _QuickActions(),
                SizedBox(height: 28),
                _SectionHeading(title: 'Recent activity'),
                SizedBox(height: 12),
                _EmptyActivityCard(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _HomeHeader extends StatelessWidget {
  const _HomeHeader();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: theme.colorScheme.primaryContainer,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Icon(
            Icons.medical_services_outlined,
            color: theme.colorScheme.onPrimaryContainer,
            size: 28,
            semanticLabel: 'SETU Swasthya',
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('SETU / Swasthya', style: theme.textTheme.titleMedium),
              const SizedBox(height: 8),
              Text('Good morning', style: theme.textTheme.headlineSmall),
              const SizedBox(height: 4),
              Text(
                'Ready to support your community today.',
                style: theme.textTheme.bodyMedium,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ReadinessCard extends StatelessWidget {
  const _ReadinessCard();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            Icon(Icons.cloud_done_outlined, color: theme.colorScheme.primary),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Workspace ready', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 4),
                  Text(
                    'Ready for use. Live connectivity and sync status will appear here later.',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text('READY', style: theme.textTheme.labelSmall),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Text(title, style: Theme.of(context).textTheme.titleLarge);
  }
}

class _OverviewGrid extends StatelessWidget {
  const _OverviewGrid();

  @override
  Widget build(BuildContext context) {
    const overviewItems = [
      (label: 'Patients today', icon: Icons.people_outline),
      (label: 'Triage pending', icon: Icons.fact_check_outlined),
      (label: 'Referrals', icon: Icons.assignment_outlined),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        final itemWidth = (constraints.maxWidth - 24) / 3;
        return Row(
          children: [
            for (var index = 0; index < overviewItems.length; index++) ...[
              SizedBox(
                width: itemWidth,
                child: _OverviewCard(
                  label: overviewItems[index].label,
                  icon: overviewItems[index].icon,
                ),
              ),
              if (index < overviewItems.length - 1) const SizedBox(width: 12),
            ],
          ],
        );
      },
    );
  }
}

class _OverviewCard extends StatelessWidget {
  const _OverviewCard({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: theme.colorScheme.primary),
            const SizedBox(height: 16),
            Text('0', style: theme.textTheme.headlineMedium),
            const SizedBox(height: 4),
            Text(label, style: theme.textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context) {
    const actions = [
      (
        label: 'Register Patient',
        route: '/registry',
        icon: Icons.person_add_alt_1_outlined,
      ),
      (
        label: 'Start Triage',
        route: '/triage',
        icon: Icons.health_and_safety_outlined,
      ),
      (
        label: 'Create Referral',
        route: '/referral',
        icon: Icons.assignment_outlined,
      ),
      (
        label: 'Team workspace',
        route: '/team',
        icon: Icons.space_dashboard_outlined,
      ),
    ];

    return Column(
      children: [
        for (final action in actions)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Card(
              child: ListTile(
                key: ValueKey('home-action-${action.route}'),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 18,
                  vertical: 6,
                ),
                leading: Icon(
                  action.icon,
                  color: Theme.of(context).colorScheme.primary,
                ),
                title: Text(action.label),
                trailing: const Icon(Icons.arrow_forward_ios, size: 16),
                onTap: () => context.go(action.route),
              ),
            ),
          ),
      ],
    );
  }
}

class _EmptyActivityCard extends StatelessWidget {
  const _EmptyActivityCard();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
        child: Column(
          children: [
            Icon(
              Icons.inbox_outlined,
              size: 36,
              color: theme.colorScheme.primary,
            ),
            const SizedBox(height: 12),
            Text('No recent activity', style: theme.textTheme.titleMedium),
            const SizedBox(height: 6),
            Text(
              'Your latest work will appear here.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
          ],
        ),
      ),
    );
  }
}
