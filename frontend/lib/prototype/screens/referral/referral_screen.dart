import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../models/referral.dart';
import '../../models/triage.dart';
import '../../providers/prototype_session_provider.dart';
import '../../providers/referral_providers.dart';

const _facilities = <({String name, String id})>[
  (name: 'District Hospital', id: '123e4567-e89b-42d3-a456-426614174002'),
  (name: 'Community Health Centre', id: '123e4567-e89b-42d3-a456-426614174003'),
  (name: 'Regional Medical Centre', id: '123e4567-e89b-42d3-a456-426614174004'),
];

String _facilityName(String id) {
  for (final facility in _facilities) {
    if (facility.id == id) return facility.name;
  }
  return 'Receiving facility';
}

String _referralCode(Referral referral) =>
    'REF-${(referral.createdAt ?? DateTime.now()).year}-0001';

class ReferralScreen extends ConsumerStatefulWidget {
  const ReferralScreen({super.key});

  @override
  ConsumerState<ReferralScreen> createState() => _ReferralScreenState();
}

class _ReferralScreenState extends ConsumerState<ReferralScreen> {
  final _formKey = GlobalKey<FormState>();
  final _patientIdController = TextEditingController();
  final _fromFacilityController = TextEditingController();
  String? _destinationFacilityId;
  final _reasonController = TextEditingController();
  final _urgencyController = TextEditingController();
  final _receivingUnitController = TextEditingController();
  final _ownerController = TextEditingController();
  final _referralIdController = TextEditingController();
  ReferralState? _selectedStatus;
  String? _statusValidationMessage;

  @override
  void initState() {
    super.initState();
    final session = ref.read(prototypeSessionProvider);
    _patientIdController.text = session.selectedPatientId ?? '';
    _fromFacilityController.text = session.selectedPatient?.facilityId ?? '';
    final triage = session.triage;
    if (triage != null) {
      if (triage.decision.disposition == TriageDisposition.emergency) {
        _destinationFacilityId = _facilities.first.id;
      }
      _urgencyController.text = switch (triage.decision.urgency) {
        TriageUrgency.immediate => 'IMMEDIATE',
        TriageUrgency.within2h => 'WITHIN_2H',
        TriageUrgency.within24h => 'WITHIN_24H',
        TriageUrgency.within72h => 'WITHIN_72H',
        TriageUrgency.within7d => 'WITHIN_7D',
        TriageUrgency.routine => 'ROUTINE',
      };
      _reasonController.text = triage.decision.reason;
    }
    _referralIdController.text = session.referral?.id ?? '';
  }

  @override
  void dispose() {
    for (final controller in [
      _patientIdController,
      _fromFacilityController,
      _reasonController,
      _urgencyController,
      _receivingUnitController,
      _ownerController,
      _referralIdController,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _createReferral() async {
    if (ref.read(prototypeSessionProvider).referral != null ||
        ref.read(referralControllerProvider).isBusy) {
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_uuidError(_patientIdController.text, 'Patient ID') != null ||
        _uuidError(_fromFacilityController.text, 'Source facility ID') !=
            null) {
      setState(
        () => _statusValidationMessage =
            'Select a patient in Registry before creating a referral.',
      );
      return;
    }
    final referral = Referral(
      id: ref.read(prototypeSessionProvider).isDemo ? const Uuid().v4() : null,
      createdAt: ref.read(prototypeSessionProvider).isDemo
          ? DateTime.now()
          : null,
      patientId: _patientIdController.text.trim(),
      fromFacilityId: _fromFacilityController.text.trim(),
      destinationFacilityId: _destinationFacilityId!,
      reason: _reasonController.text.trim(),
      urgency: _urgencyController.text.trim(),
      receivingUnit: _optional(_receivingUnitController.text),
      owner: _optional(_ownerController.text),
    );
    if (ref.read(prototypeSessionProvider).isDemo) {
      ref.read(prototypeSessionProvider.notifier).setReferral(referral);
      _referralIdController.text = referral.id!;
      return;
    }
    await ref.read(referralControllerProvider.notifier).create(referral);
    final created = ref.read(referralControllerProvider).referral;
    if (created != null) {
      ref.read(prototypeSessionProvider.notifier).setReferral(created);
      _referralIdController.text = created.id ?? '';
    }
  }

  Future<void> _updateStatus() async {
    final referralId = _referralIdController.text.trim();
    final idError = _uuidError(referralId, 'Referral ID');
    if (idError != null || _selectedStatus == null) {
      _statusValidationMessage = idError ?? 'Please select a new status';
      setState(() {});
      return;
    }
    _statusValidationMessage = null;
    if (ref.read(prototypeSessionProvider).isDemo) {
      final session = ref.read(prototypeSessionProvider);
      if (session.referral == null ||
          session.referralStatus != ReferralState.initiated ||
          _selectedStatus != ReferralState.arrived) {
        setState(
          () => _statusValidationMessage =
              'For this demo, update an initiated referral to ARRIVED.',
        );
        return;
      }
      ref
          .read(prototypeSessionProvider.notifier)
          .setReferralStatus(ReferralState.arrived);
      return;
    }
    await ref
        .read(referralControllerProvider.notifier)
        .updateStatus(referralId, _selectedStatus!, null);
    if (ref.read(referralControllerProvider).status == ReferralStatus.success) {
      ref
          .read(prototypeSessionProvider.notifier)
          .setReferralStatus(_selectedStatus!);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(referralControllerProvider);
    final session = ref.watch(prototypeSessionProvider);
    final referral = session.isDemo ? session.referral : state.referral;
    final currentStatus = session.isDemo
        ? session.referralStatus
        : state.currentStatus;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Referral',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    session.isDemo
                        ? 'Synthetic referral for this prototype session.'
                        : 'Create and update referrals using the backend workflow.',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 24),
                  _section('Create referral', [
                    TextFormField(
                      key: const ValueKey('referral-patient-id'),
                      initialValue:
                          session.selectedPatient?.name ??
                          'Select a patient in Registry',
                      readOnly: true,
                      decoration: const InputDecoration(labelText: 'Patient'),
                    ),
                    TextFormField(
                      key: const ValueKey('referral-from-facility-id'),
                      initialValue: _fromFacilityController.text.isEmpty
                          ? 'Select a patient in Registry'
                          : 'Current facility',
                      readOnly: true,
                      decoration: const InputDecoration(
                        labelText: 'Source facility',
                      ),
                    ),
                    DropdownButtonFormField<String>(
                      key: const ValueKey('referral-destination-facility-id'),
                      initialValue: _destinationFacilityId,
                      decoration: const InputDecoration(
                        labelText: 'Destination facility',
                      ),
                      items: [
                        for (final facility in _facilities)
                          DropdownMenuItem(
                            value: facility.id,
                            child: Text(facility.name),
                          ),
                      ],
                      onChanged: state.isBusy || referral != null
                          ? null
                          : (value) =>
                                setState(() => _destinationFacilityId = value),
                      validator: (value) => value == null
                          ? 'Choose a destination facility'
                          : null,
                    ),
                    _field(
                      _reasonController,
                      'Reason',
                      'referral-reason',
                      required: true,
                    ),
                    _field(
                      _urgencyController,
                      'Urgency',
                      'referral-urgency',
                      required: true,
                    ),
                    _field(
                      _receivingUnitController,
                      'Receiving unit (optional)',
                      'referral-receiving-unit',
                    ),
                    _field(
                      _ownerController,
                      'Owner (optional)',
                      'referral-owner',
                    ),
                    FilledButton.icon(
                      key: const ValueKey('referral-create-button'),
                      onPressed: state.isBusy || referral != null
                          ? null
                          : _createReferral,
                      icon: state.status == ReferralStatus.creating
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.assignment_outlined),
                      label: Text(
                        state.status == ReferralStatus.creating
                            ? 'Creating...'
                            : 'Create referral',
                      ),
                    ),
                  ]),
                  _section('Update referral status', [
                    if (referral != null)
                      Text('Referral ${_referralCode(referral)}'),
                    _dropdown<ReferralState>(
                      key: const ValueKey('referral-status-dropdown'),
                      label: 'New status',
                      value: _selectedStatus,
                      items: session.isDemo
                          ? const [ReferralState.arrived]
                          : ReferralState.values,
                      labelFor: referralStateValue,
                      onChanged: (value) {
                        if (!state.isBusy) {
                          setState(() {
                            _selectedStatus = value;
                            _statusValidationMessage = null;
                          });
                        }
                      },
                    ),
                    FilledButton.tonalIcon(
                      key: const ValueKey('referral-update-status-button'),
                      onPressed:
                          state.isBusy ||
                              (session.isDemo &&
                                  currentStatus == ReferralState.arrived)
                          ? null
                          : _updateStatus,
                      icon: state.status == ReferralStatus.updating
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.sync_alt_outlined),
                      label: Text(
                        state.status == ReferralStatus.updating
                            ? 'Updating...'
                            : 'Update status',
                      ),
                    ),
                    if (currentStatus != null)
                      Text(
                        'Current ${session.isDemo ? 'demo' : 'backend'} status: ${referralStateValue(currentStatus)}',
                      ),
                    if (_statusValidationMessage != null)
                      Text(
                        _statusValidationMessage!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                  ]),
                  if (state.errorMessage != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(
                        state.errorMessage!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  if (referral != null) ...[
                    const SizedBox(height: 16),
                    _ReferralResult(
                      referral: referral,
                      status: currentStatus ?? referral.status,
                      patientName:
                          session.selectedPatient?.name ?? 'Selected patient',
                    ),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Status timeline'),
                            const Text('INITIATED'),
                            if (currentStatus != null &&
                                currentStatus != ReferralState.initiated)
                              Text(referralStateValue(currentStatus)),
                          ],
                        ),
                      ),
                    ),
                    FilledButton.tonal(
                      onPressed: () => context.push('/dashboard'),
                      child: const Text('Open Dashboard'),
                    ),
                  ],
                  if (state.pendingOffline)
                    const Padding(
                      padding: EdgeInsets.only(top: 12),
                      child: Text(
                        'Saved on this device. It will sync when connectivity returns.',
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _section(String title, List<Widget> children) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 16),
            for (var index = 0; index < children.length; index++) ...[
              children[index],
              if (index < children.length - 1) const SizedBox(height: 12),
            ],
          ],
        ),
      ),
    ),
  );

  Widget _field(
    TextEditingController controller,
    String label,
    String keyValue, {
    bool required = false,
    String? Function(String?)? validator,
  }) => TextFormField(
    key: ValueKey(keyValue),
    controller: controller,
    decoration: InputDecoration(labelText: label),
    validator:
        validator ?? (required ? (value) => _required(value, label) : null),
  );

  Widget _dropdown<T>({
    required Key key,
    required String label,
    required T? value,
    required List<T> items,
    required String Function(T) labelFor,
    required ValueChanged<T?> onChanged,
  }) => DropdownButtonFormField<T>(
    key: key,
    initialValue: value,
    decoration: InputDecoration(labelText: label),
    items: items
        .map(
          (item) => DropdownMenuItem(value: item, child: Text(labelFor(item))),
        )
        .toList(),
    onChanged: onChanged,
  );

  String? _required(String? value, String label) =>
      value == null || value.trim().isEmpty ? 'Please enter $label' : null;

  String? _uuidError(String? value, String label) {
    if (_required(value, label) != null) return _required(value, label);
    final pattern = RegExp(
      r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
    );
    return pattern.hasMatch(value!.trim()) ? null : 'Enter a valid UUID';
  }

  String? _optional(String value) => value.trim().isEmpty ? null : value.trim();
}

class _ReferralResult extends StatelessWidget {
  const _ReferralResult({
    required this.referral,
    required this.status,
    required this.patientName,
  });

  final Referral referral;
  final ReferralState status;
  final String patientName;

  @override
  Widget build(BuildContext context) => Card(
    key: const ValueKey('referral-result'),
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Referral created',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          Text('Referral code: ${_referralCode(referral)}'),
          Text('Status: ${referralStateValue(status)}'),
          Text('Patient: $patientName'),
          const Text('Source: Current facility'),
          Text('Destination: ${_facilityName(referral.destinationFacilityId)}'),
          Text('Reason: ${referral.reason}'),
          Text('Urgency: ${referral.urgency}'),
        ],
      ),
    ),
  );
}
