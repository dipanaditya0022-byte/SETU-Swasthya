import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../models/triage.dart';
import '../../models/demo_triage.dart';
import '../../providers/prototype_session_provider.dart';
import '../../providers/triage_providers.dart';

class TriageScreen extends ConsumerStatefulWidget {
  const TriageScreen({super.key});

  @override
  ConsumerState<TriageScreen> createState() => _TriageScreenState();
}

class _TriageScreenState extends ConsumerState<TriageScreen> {
  final _formKey = GlobalKey<FormState>();
  final _patientIdController = TextEditingController();
  final _facilityIdController = TextEditingController();
  final _dispositionController = TextEditingController();
  final _urgencyController = TextEditingController();
  final _protocolController = TextEditingController();
  final _symptomsController = TextEditingController();
  final _dangerSignsController = TextEditingController();
  final _temperatureController = TextEditingController();
  final _pulseController = TextEditingController();
  final _spo2Controller = TextEditingController();
  final _respiratoryRateController = TextEditingController();
  final _systolicController = TextEditingController();
  final _diastolicController = TextEditingController();
  final _gestationalWeeksController = TextEditingController();
  final _historyController = TextEditingController();
  TriageSex? _sex;
  bool _isPregnant = false;
  TriageEvaluationResponse? _demoResponse;
  String? _demoError;

  @override
  void initState() {
    super.initState();
    final patient = ref.read(prototypeSessionProvider).selectedPatient;
    if (patient != null) {
      _patientIdController.text = patient.id ?? '';
      _facilityIdController.text = patient.facilityId;
    }
  }

  @override
  void dispose() {
    for (final controller in [
      _patientIdController,
      _facilityIdController,
      _dispositionController,
      _urgencyController,
      _protocolController,
      _symptomsController,
      _dangerSignsController,
      _temperatureController,
      _pulseController,
      _spo2Controller,
      _respiratoryRateController,
      _systolicController,
      _diastolicController,
      _gestationalWeeksController,
      _historyController,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (ref.read(triageControllerProvider).isSubmitting ||
        (ref.read(prototypeSessionProvider).isDemo &&
            ref.read(prototypeSessionProvider).triage != null)) {
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final session = ref.read(prototypeSessionProvider);
    if (session.isDemo) {
      final now = DateTime.now();
      final decision = demoTriageDecision(
        vitals: _parseVitals(),
        dangerSigns: _csv(_dangerSignsController.text),
        symptoms: _csv(_symptomsController.text),
        now: now,
      );
      final response = TriageEvaluationResponse(
        id: const Uuid().v4(),
        patientId: _patientIdController.text.trim(),
        facilityId: _facilityIdController.text.trim(),
        triageDisposition: decision.disposition.name,
        createdAt: now,
        decision: decision,
      );
      ref.read(prototypeSessionProvider.notifier).setTriage(response);
      setState(() {
        _demoResponse = response;
        _demoError = null;
      });
      return;
    }
    final vitals = _parseVitals();

    await ref
        .read(triageControllerProvider.notifier)
        .submit(
          TriageEvaluationRequest(
            patientId: _patientIdController.text.trim(),
            facilityId: _facilityIdController.text.trim(),
            triageDisposition: _dispositionController.text.trim(),
            referralUrgency: _optionalText(_urgencyController.text),
            protocol: _optionalText(_protocolController.text),
            vitals: vitals,
            symptoms: _csv(_symptomsController.text),
            dangerSigns: _csv(_dangerSignsController.text),
            sex: _sex,
            isPregnant: _isPregnant,
            gestationalWeeks: _optionalNum(_gestationalWeeksController.text),
            clinicalHistory: _optionalText(_historyController.text),
          ),
        );
    final response = ref.read(triageControllerProvider).response;
    if (response != null) {
      ref.read(prototypeSessionProvider.notifier).setTriage(response);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(triageControllerProvider);
    final session = ref.watch(prototypeSessionProvider);
    final response =
        _demoResponse ??
        (session.isDemo ? session.triage : null) ??
        state.response;
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
                    'Triage',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    session.isDemo
                        ? 'Synthetic demonstration only, not clinical advice. Enter symptoms, danger signs or a temperature to see the fixed demo decision.'
                        : 'Submit encounter observations for backend evaluation.',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 24),
                  _section('Context', [
                    _field(
                      _patientIdController,
                      'Patient UUID',
                      'triage-patient-id',
                      required: true,
                      validator: (value) => _uuidError(value, 'Patient UUID'),
                    ),
                    _field(
                      _facilityIdController,
                      'Facility UUID',
                      'triage-facility-id',
                      required: true,
                      validator: (value) => _uuidError(value, 'Facility UUID'),
                    ),
                    if (!session.isDemo) ...[
                      _field(
                        _dispositionController,
                        'Triage disposition',
                        'triage-disposition',
                        required: true,
                      ),
                      _field(
                        _urgencyController,
                        'Referral urgency (optional)',
                        'triage-urgency',
                      ),
                      _field(
                        _protocolController,
                        'Protocol (optional)',
                        'triage-protocol',
                      ),
                    ],
                  ]),
                  _section('Observations', [
                    _field(
                      _symptomsController,
                      'Symptoms (comma-separated)',
                      'triage-symptoms',
                    ),
                    _field(
                      _dangerSignsController,
                      'Danger signs (comma-separated)',
                      'triage-danger-signs',
                    ),
                    _vitalField(
                      _temperatureController,
                      'Temperature (°C)',
                      'triage-temperature',
                      25,
                      45,
                    ),
                    _vitalField(
                      _pulseController,
                      'Pulse (beats/min)',
                      'triage-pulse',
                      20,
                      250,
                    ),
                    _vitalField(
                      _spo2Controller,
                      'SpO2 (%)',
                      'triage-spo2',
                      0,
                      100,
                    ),
                    _vitalField(
                      _respiratoryRateController,
                      'Respiratory rate (/min)',
                      'triage-respiratory-rate',
                      5,
                      80,
                    ),
                    _vitalField(
                      _systolicController,
                      'Systolic BP (mmHg)',
                      'triage-systolic-bp',
                      50,
                      300,
                    ),
                    _vitalField(
                      _diastolicController,
                      'Diastolic BP (mmHg)',
                      'triage-diastolic-bp',
                      20,
                      200,
                    ),
                    _dropdown<TriageSex>(
                      key: const ValueKey('triage-sex'),
                      label: 'Sex (optional)',
                      value: _sex,
                      items: TriageSex.values,
                      labelFor: (value) => value.name.toUpperCase(),
                      onChanged: (value) => setState(() => _sex = value),
                    ),
                    SwitchListTile(
                      key: const ValueKey('triage-pregnancy'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Is pregnant'),
                      value: _isPregnant,
                      onChanged: state.isSubmitting
                          ? null
                          : (value) => setState(() => _isPregnant = value),
                    ),
                    _field(
                      _gestationalWeeksController,
                      'Gestational weeks (optional)',
                      'triage-gestational-weeks',
                      keyboard: TextInputType.number,
                      validator: _numberError,
                    ),
                    TextFormField(
                      key: const ValueKey('triage-clinical-history'),
                      controller: _historyController,
                      maxLines: 3,
                      decoration: const InputDecoration(
                        labelText: 'Clinical history (optional)',
                        hintText: 'Enter relevant history in plain language',
                      ),
                    ),
                  ]),
                  FilledButton.icon(
                    key: const ValueKey('triage-submit-button'),
                    onPressed:
                        state.isSubmitting ||
                            (session.isDemo && response != null)
                        ? null
                        : _submit,
                    icon: state.isSubmitting
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.health_and_safety_outlined),
                    label: Text(
                      state.isSubmitting ? 'Submitting...' : 'Evaluate triage',
                    ),
                  ),
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
                  if (_demoError != null)
                    Text(
                      _demoError!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  if (response != null) ...[
                    const SizedBox(height: 24),
                    _TriageResult(
                      response: response,
                      demo: session.isDemo,
                      onCreateReferral:
                          response.decision.disposition ==
                                  TriageDisposition.refer ||
                              response.decision.disposition ==
                                  TriageDisposition.emergency
                          ? () => context.push('/referral')
                          : null,
                    ),
                  ],
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
    String? hint,
    TextInputType? keyboard,
    String? Function(String?)? validator,
  }) => TextFormField(
    key: ValueKey(keyValue),
    controller: controller,
    keyboardType: keyboard,
    decoration: InputDecoration(labelText: label, hintText: hint),
    validator:
        validator ?? (required ? (value) => _required(value, label) : null),
  );

  Widget _vitalField(
    TextEditingController controller,
    String label,
    String keyValue,
    num minimum,
    num maximum,
  ) => _field(
    controller,
    label,
    keyValue,
    keyboard: const TextInputType.numberWithOptions(decimal: true),
    validator: (value) {
      if (value == null || value.trim().isEmpty) return null;
      final parsed = num.tryParse(value.trim());
      if (parsed == null || parsed < minimum || parsed > maximum) {
        return 'Enter a number from $minimum to $maximum';
      }
      return null;
    },
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
    if (_required(value, label) != null) {
      return _required(value, label);
    }
    final pattern = RegExp(
      r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
    );
    return pattern.hasMatch(value!.trim()) ? null : 'Enter a valid UUID';
  }

  String? _numberError(String? value) {
    if (value == null || value.trim().isEmpty) return null;
    return num.tryParse(value.trim()) == null ? 'Enter a valid number' : null;
  }

  Map<String, num> _parseVitals() {
    final vitals = <String, num>{};
    for (final item in <(String, TextEditingController)>[
      ('temperature', _temperatureController),
      ('pulse', _pulseController),
      ('spo2', _spo2Controller),
      ('respiratory_rate', _respiratoryRateController),
      ('systolic_bp', _systolicController),
      ('diastolic_bp', _diastolicController),
    ]) {
      final value = item.$2.text.trim();
      if (value.isNotEmpty) vitals[item.$1] = num.parse(value);
    }
    return vitals;
  }

  List<String> _csv(String value) => value
      .split(',')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();

  String? _optionalText(String value) =>
      value.trim().isEmpty ? null : value.trim();

  num? _optionalNum(String value) =>
      value.trim().isEmpty ? null : num.tryParse(value.trim());
}

class _TriageResult extends StatelessWidget {
  const _TriageResult({
    required this.response,
    this.demo = false,
    this.onCreateReferral,
  });

  final TriageEvaluationResponse response;
  final bool demo;
  final VoidCallback? onCreateReferral;

  @override
  Widget build(BuildContext context) {
    final decision = response.decision;
    final color = switch (decision.disposition) {
      TriageDisposition.manageHere => Colors.green,
      TriageDisposition.teleconsult => Colors.amber,
      TriageDisposition.refer => Colors.orange,
      TriageDisposition.emergency => Colors.red,
    };
    return Card(
      key: const ValueKey('triage-result'),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              demo ? 'Demo triage decision' : 'Backend triage decision',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            Text(
              'Disposition: ${switch (decision.disposition) {
                TriageDisposition.manageHere => 'Manage Here',
                TriageDisposition.teleconsult => 'Teleconsult',
                TriageDisposition.refer => 'Refer',
                TriageDisposition.emergency => 'Emergency',
              }}',
              style: TextStyle(color: color, fontWeight: FontWeight.bold),
            ),
            Text('Urgency: ${decision.urgency.name}'),
            Text('Reason: ${decision.reason}'),
            Text('Engine: ${decision.engine.name}'),
            Text('Protocol version: ${decision.protocolVersion}'),
            Text('Insufficient data: ${decision.insufficientData}'),
            if (decision.redFlags.isNotEmpty)
              Text('Red flags: ${decision.redFlags.join(', ')}'),
            if (decision.missingFields.isNotEmpty)
              Text('Missing fields: ${decision.missingFields.join(', ')}'),
            Text('Evaluation ID: ${response.id}'),
            if (onCreateReferral != null)
              FilledButton.icon(
                onPressed: onCreateReferral,
                icon: const Icon(Icons.assignment_outlined),
                label: const Text('Create Referral'),
              ),
          ],
        ),
      ),
    );
  }
}
