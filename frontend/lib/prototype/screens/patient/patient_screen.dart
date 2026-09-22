import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/network/api_exception.dart';
import '../../models/patient.dart';
import '../../providers/patient_provider.dart';
import '../../providers/prototype_session_provider.dart';

class PatientScreen extends ConsumerWidget {
  const PatientScreen({required this.patientId, super.key});

  final String patientId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(prototypeSessionProvider);
    if (session.selectedPatient?.id == patientId) {
      return _PatientProfile(
        patient: session.selectedPatient!,
        demo: session.isDemo,
      );
    }
    final patient = ref.watch(patientProvider(patientId));
    return patient.when(
      loading: () => const _ProfileState(
        message: 'Loading patient...',
        showProgress: true,
      ),
      data: (value) => _PatientProfile(patient: value),
      error: (error, _) => _ProfileError(error: error),
    );
  }
}

class _PatientProfile extends StatelessWidget {
  const _PatientProfile({required this.patient, this.demo = false});

  final Patient patient;
  final bool demo;

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
              children: [
                if (demo) const Text('Synthetic prototype patient'),
                _IdentityCard(patient: patient),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: () => context.push('/triage'),
                  icon: const Icon(Icons.health_and_safety_outlined),
                  label: const Text('Start triage'),
                ),
                const SizedBox(height: 24),
                const _SectionHeading(title: 'Basic information'),
                const SizedBox(height: 12),
                _BasicInformationCard(patient: patient),
                if (_hasMetadata) ...[
                  const SizedBox(height: 24),
                  const _SectionHeading(title: 'Record metadata'),
                  const SizedBox(height: 12),
                  _MetadataCard(patient: patient),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  bool get _hasMetadata =>
      patient.createdAt != null ||
      patient.clientUuid != null ||
      patient.createdByUserId != null ||
      patient.orgUnitId != null ||
      patient.syncedAt != null;
}

class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.patient});

  final Patient patient;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            CircleAvatar(
              radius: 30,
              backgroundColor: theme.colorScheme.primaryContainer,
              child: Icon(
                Icons.person_outline,
                size: 34,
                color: theme.colorScheme.onPrimaryContainer,
                semanticLabel: 'Patient profile',
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(patient.name, style: theme.textTheme.titleLarge),
                  const SizedBox(height: 6),
                  if (patient.id != null)
                    SelectableText(
                      'Patient ID: ${patient.id}',
                      style: theme.textTheme.bodyLarge,
                    ),
                  Text('Patient profile', style: theme.textTheme.bodySmall),
                ],
              ),
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
  Widget build(BuildContext context) =>
      Text(title, style: Theme.of(context).textTheme.titleLarge);
}

class _BasicInformationCard extends StatelessWidget {
  const _BasicInformationCard({required this.patient});

  final Patient patient;

  @override
  Widget build(BuildContext context) {
    final fields = <({String label, String value, IconData icon})>[
      (label: 'Full name', value: patient.name, icon: Icons.person_outline),
      (label: 'Age', value: patient.age.toString(), icon: Icons.cake_outlined),
      (
        label: 'Village',
        value: patient.village,
        icon: Icons.location_on_outlined,
      ),
      if (patient.phone != null)
        (label: 'Phone', value: patient.phone!, icon: Icons.phone_outlined),
      (
        label: 'Facility ID',
        value: patient.facilityId,
        icon: Icons.local_hospital_outlined,
      ),
    ];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            for (var index = 0; index < fields.length; index++) ...[
              _DetailRow(
                label: fields[index].label,
                value: fields[index].value,
                icon: fields[index].icon,
              ),
              if (index < fields.length - 1) const Divider(height: 24),
            ],
          ],
        ),
      ),
    );
  }
}

class _MetadataCard extends StatelessWidget {
  const _MetadataCard({required this.patient});

  final Patient patient;

  @override
  Widget build(BuildContext context) {
    final fields = <({String label, String value})>[
      if (patient.createdAt != null)
        (label: 'Created at', value: patient.createdAt!.toIso8601String()),
      if (patient.clientUuid != null)
        (label: 'Client UUID', value: patient.clientUuid!),
      if (patient.createdByUserId != null)
        (label: 'Created by user ID', value: patient.createdByUserId!),
      if (patient.orgUnitId != null)
        (label: 'Org unit ID', value: patient.orgUnitId!),
      if (patient.syncedAt != null)
        (label: 'Synced at', value: patient.syncedAt!.toIso8601String()),
    ];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            for (var index = 0; index < fields.length; index++) ...[
              _DetailRow(
                label: fields[index].label,
                value: fields[index].value,
              ),
              if (index < fields.length - 1) const Divider(height: 24),
            ],
          ],
        ),
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value, this.icon});

  final String label;
  final String value;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        if (icon != null) ...[
          Icon(icon, size: 22, color: theme.colorScheme.primary),
          const SizedBox(width: 14),
        ],
        Expanded(child: Text(label, style: theme.textTheme.bodyMedium)),
        const SizedBox(width: 12),
        Flexible(child: SelectableText(value, textAlign: TextAlign.end)),
      ],
    );
  }
}

class _ProfileState extends StatelessWidget {
  const _ProfileState({required this.message, this.showProgress = false});

  final String message;
  final bool showProgress;

  @override
  Widget build(BuildContext context) => SafeArea(
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (showProgress) const CircularProgressIndicator(),
          if (showProgress) const SizedBox(height: 16),
          Text(message),
        ],
      ),
    ),
  );
}

class _ProfileError extends StatelessWidget {
  const _ProfileError({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    final message = switch (error) {
      InvalidPatientIdException() => 'Patient ID is invalid.',
      ClientApiException(statusCode: 404) => 'Patient not found.',
      ClientApiException(statusCode: 401) ||
      ClientApiException(
        statusCode: 403,
      ) => 'Authentication is required to view this patient.',
      NoInternetException() =>
        'Unable to connect. Check your internet connection and try again.',
      ApiTimeoutException() => 'The request timed out. Please try again.',
      ServerApiException() =>
        'Something went wrong on the server. Please try again.',
      _ => 'Unable to load patient. Please try again.',
    };
    return _ProfileState(message: message);
  }
}
