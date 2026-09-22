import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers/prototype_session_provider.dart';

class RegistryScreen extends ConsumerStatefulWidget {
  const RegistryScreen({super.key});

  @override
  ConsumerState<RegistryScreen> createState() => _RegistryScreenState();
}

class _RegistryScreenState extends ConsumerState<RegistryScreen> {
  final _searchController = TextEditingController();
  String _selectedFilter = 'All';

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(prototypeSessionProvider);
    final query = _searchController.text.trim().toLowerCase();
    final patients = session.patients
        .where(
          (patient) =>
              patient.name.toLowerCase().contains(query) ||
              (patient.id?.toLowerCase().contains(query) ?? false),
        )
        .toList();
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _RegistryHeader(
                  onRegister: () => context.push('/registry/register'),
                ),
                if (session.isDemo)
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Text('Synthetic patients in this demo session'),
                  ),
                const SizedBox(height: 24),
                TextField(
                  key: const ValueKey('registry-search-field'),
                  controller: _searchController,
                  onChanged: (_) => setState(() {}),
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    labelText: 'Search patients',
                    hintText: 'Search patients',
                    prefixIcon: const Icon(Icons.search),
                    suffixIcon: _searchController.text.isEmpty
                        ? null
                        : IconButton(
                            onPressed: () {
                              _searchController.clear();
                              setState(() {});
                            },
                            tooltip: 'Clear search',
                            icon: const Icon(Icons.clear),
                          ),
                  ),
                ),
                const SizedBox(height: 16),
                _FilterChips(
                  selectedFilter: _selectedFilter,
                  onSelected: (filter) =>
                      setState(() => _selectedFilter = filter),
                ),
                const SizedBox(height: 32),
                if (patients.isEmpty) const _EmptyRegistryState(),
                for (final patient in patients)
                  Card(
                    child: ListTile(
                      title: Text(patient.name),
                      subtitle: Text('${patient.village} • ${patient.id}'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () {
                        ref
                            .read(prototypeSessionProvider.notifier)
                            .selectPatient(patient.id!);
                        context.push('/patient/${patient.id}');
                      },
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

class _RegistryHeader extends StatelessWidget {
  const _RegistryHeader({required this.onRegister});

  final VoidCallback onRegister;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          Icons.people_alt_outlined,
          size: 36,
          color: theme.colorScheme.primary,
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Patient Registry', style: theme.textTheme.headlineSmall),
              const SizedBox(height: 6),
              Text(
                'Keep your community care records organized in one place.',
                style: theme.textTheme.bodyMedium,
              ),
            ],
          ),
        ),
        IconButton(
          onPressed: onRegister,
          tooltip: 'Register patient',
          icon: const Icon(Icons.person_add_alt_1),
        ),
      ],
    );
  }
}

class _FilterChips extends StatelessWidget {
  const _FilterChips({required this.selectedFilter, required this.onSelected});

  final String selectedFilter;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    const filters = ['All', 'Recent', 'Needs Triage'];

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final filter in filters)
          FilterChip(
            key: ValueKey('registry-filter-$filter'),
            label: Text(filter),
            selected: selectedFilter == filter,
            onSelected: (_) => onSelected(filter),
          ),
      ],
    );
  }
}

class _EmptyRegistryState extends StatelessWidget {
  const _EmptyRegistryState();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
        child: Column(
          children: [
            Icon(
              Icons.person_search_outlined,
              size: 48,
              color: theme.colorScheme.primary,
            ),
            const SizedBox(height: 16),
            Text('No patients yet', style: theme.textTheme.titleLarge),
            const SizedBox(height: 8),
            Text(
              'Register your first patient to begin building the local registry.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              key: const ValueKey('registry-register-button'),
              onPressed: () => context.push('/registry/register'),
              icon: const Icon(Icons.person_add_alt_1),
              label: const Text('Register Patient'),
            ),
          ],
        ),
      ),
    );
  }
}
