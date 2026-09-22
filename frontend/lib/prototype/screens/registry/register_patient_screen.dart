import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../core/network/api_exception.dart';
import '../../models/patient.dart';
import '../../providers/api_providers.dart';
import '../../providers/prototype_session_provider.dart';

class RegisterPatientScreen extends ConsumerStatefulWidget {
  const RegisterPatientScreen({super.key});

  @override
  ConsumerState<RegisterPatientScreen> createState() =>
      _RegisterPatientScreenState();
}

class _RegisterPatientScreenState extends ConsumerState<RegisterPatientScreen> {
  final _formKey = GlobalKey<FormState>();
  final _fullNameController = TextEditingController();
  final _dateOfBirthController = TextEditingController();
  final _ageController = TextEditingController();
  final _phoneController = TextEditingController();
  final _villageCodeController = TextEditingController();
  final _languageController = TextEditingController(text: 'hi');
  final _abhaNumberController = TextEditingController();
  final _abhaAddressController = TextEditingController();
  final _hamletController = TextEditingController();
  final _houseNumberController = TextEditingController();
  final _guardianNameController = TextEditingController();
  final _guardianMobileController = TextEditingController();
  final _emergencyNameController = TextEditingController();
  final _emergencyMobileController = TextEditingController();
  PatientSex? _sex;
  GuardianRelation? _guardianRelation;
  ConsentMode? _consentMode;
  bool _isSharedPhone = false;
  bool _consentKeepRecord = false;
  bool _consentShareSpecialist = false;
  bool _consentShareFacility = false;
  bool _consentAnonymisedPlanning = false;
  bool _creating = false;
  String? _createError;
  String? _createdPatientId;
  bool get _demoMode => prototypeDemoMode;

  @override
  void dispose() {
    for (final controller in [
      _fullNameController,
      _dateOfBirthController,
      _ageController,
      _phoneController,
      _villageCodeController,
      _languageController,
      _abhaNumberController,
      _abhaAddressController,
      _hamletController,
      _houseNumberController,
      _guardianNameController,
      _guardianMobileController,
      _emergencyNameController,
      _emergencyMobileController,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _chooseDateOfBirth() async {
    final selectedDate = await showDatePicker(
      context: context,
      firstDate: DateTime(1900),
      lastDate: DateTime.now(),
      initialDate: DateTime(2000),
    );
    if (selectedDate != null) {
      _dateOfBirthController.text =
          '${selectedDate.day.toString().padLeft(2, '0')}/'
          '${selectedDate.month.toString().padLeft(2, '0')}/'
          '${selectedDate.year}';
      setState(() {});
    }
  }

  Future<void> _submit() async {
    if (_creating || _createdPatientId != null) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_demoMode || const String.fromEnvironment('FACILITY_ID').isNotEmpty) {
      final age =
          _optionalInt(_ageController.text) ??
          (_parseDateOfBirth() == null
              ? null
              : DateTime.now().year - _parseDateOfBirth()!.year);
      if (age == null || age < 0 || age > 130) {
        setState(() => _createError = 'Enter a valid age or date of birth.');
        return;
      }
      setState(() {
        _creating = true;
        _createError = null;
      });
      try {
        final patient = Patient(
          id: _demoMode ? const Uuid().v4() : null,
          name: _fullNameController.text.trim(),
          age: age,
          village: _villageCodeController.text.trim(),
          phone: _phoneController.text.trim().isEmpty
              ? null
              : _phoneController.text.trim(),
          facilityId: _demoMode
              ? '123e4567-e89b-42d3-a456-426614174001'
              : const String.fromEnvironment('FACILITY_ID'),
        );
        final created = _demoMode
            ? patient
            : await ref.read(patientRepositoryProvider).createPatient(patient);
        if (created.id == null || created.id!.isEmpty) {
          throw const UnexpectedApiException(
            message: 'The patient response did not include an ID.',
          );
        }
        ref
            .read(prototypeSessionProvider.notifier)
            .addPatient(created, demo: _demoMode);
        if (mounted) {
          setState(() => _createdPatientId = created.id);
          context.go('/patient/${created.id}');
        }
      } on ApiException catch (error) {
        if (mounted) {
          setState(
            () => _createError = error.message ?? 'Could not register patient.',
          );
        }
      } finally {
        if (mounted) setState(() => _creating = false);
      }
      return;
    }
    setState(
      () => _createError = 'FACILITY_ID is required for live registration.',
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
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
                    'Register Patient',
                    style: theme.textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _demoMode
                        ? 'Synthetic prototype record. No patient data leaves this session.'
                        : 'Live registration through the configured backend.',
                    style: theme.textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 24),
                  _section('Basic information', [
                    _textField(
                      _fullNameController,
                      'Full name',
                      'registration-full-name',
                      required: true,
                    ),
                    TextFormField(
                      key: const ValueKey('registration-date-of-birth'),
                      controller: _dateOfBirthController,
                      readOnly: true,
                      onTap: _chooseDateOfBirth,
                      decoration: const InputDecoration(
                        labelText: 'Date of birth (optional)',
                      ),
                    ),
                    _textField(
                      _ageController,
                      'Age in years',
                      'registration-age',
                      keyboard: TextInputType.number,
                    ),
                    _dropdown<PatientSex>(
                      key: const ValueKey('registration-gender'),
                      label: 'Sex',
                      value: _sex,
                      items: PatientSex.values,
                      labelFor: (value) => value.name.toUpperCase(),
                      onChanged: (value) => setState(() => _sex = value),
                      validator: (value) =>
                          value == null ? 'Please select sex' : null,
                    ),
                  ]),
                  _section('Contact and location', [
                    _textField(
                      _phoneController,
                      _demoMode
                          ? 'Mobile number (optional contact)'
                          : 'Mobile number',
                      'registration-phone',
                      keyboard: TextInputType.phone,
                      required: !_demoMode,
                      validator: _demoMode
                          ? (value) => value == null || value.trim().isEmpty
                                ? null
                                : _mobileError(value)
                          : _mobileError,
                    ),
                    CheckboxListTile(
                      key: const ValueKey('registration-shared-phone'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Shared phone'),
                      value: _isSharedPhone,
                      onChanged: _creating
                          ? null
                          : (value) =>
                                setState(() => _isSharedPhone = value ?? false),
                    ),
                    _textField(
                      _villageCodeController,
                      'Village LGD code',
                      'registration-village-code',
                      required: true,
                    ),
                    _textField(
                      _languageController,
                      'Preferred language',
                      'registration-language',
                      required: true,
                    ),
                    _textField(
                      _hamletController,
                      'Hamlet',
                      'registration-hamlet',
                    ),
                    _textField(
                      _houseNumberController,
                      'House number',
                      'registration-house-number',
                    ),
                  ]),
                  _section('ABHA and contacts', [
                    _textField(
                      _abhaNumberController,
                      'ABHA number',
                      'registration-abha-number',
                    ),
                    _textField(
                      _abhaAddressController,
                      'ABHA address',
                      'registration-abha-address',
                    ),
                    _textField(
                      _guardianNameController,
                      'Guardian name',
                      'registration-guardian-name',
                    ),
                    _dropdown<GuardianRelation>(
                      key: const ValueKey('registration-guardian-relation'),
                      label: 'Guardian relation',
                      value: _guardianRelation,
                      items: GuardianRelation.values,
                      labelFor: (value) => value.name.toUpperCase(),
                      onChanged: (value) =>
                          setState(() => _guardianRelation = value),
                    ),
                    _textField(
                      _guardianMobileController,
                      'Guardian mobile',
                      'registration-guardian-mobile',
                      keyboard: TextInputType.phone,
                    ),
                    _textField(
                      _emergencyNameController,
                      'Emergency contact name',
                      'registration-emergency-name',
                    ),
                    _textField(
                      _emergencyMobileController,
                      'Emergency contact mobile',
                      'registration-emergency-mobile',
                      keyboard: TextInputType.phone,
                    ),
                  ]),
                  _section('Consent', [
                    _consent(
                      'Keep record',
                      _consentKeepRecord,
                      (value) => _consentKeepRecord = value,
                    ),
                    _consent(
                      'Share with specialist',
                      _consentShareSpecialist,
                      (value) => _consentShareSpecialist = value,
                    ),
                    _consent(
                      'Share with facility',
                      _consentShareFacility,
                      (value) => _consentShareFacility = value,
                    ),
                    _consent(
                      'Anonymised planning',
                      _consentAnonymisedPlanning,
                      (value) => _consentAnonymisedPlanning = value,
                    ),
                    _dropdown<ConsentMode>(
                      key: const ValueKey('registration-consent-mode'),
                      label: 'Consent mode',
                      value: _consentMode,
                      items: ConsentMode.values,
                      labelFor: (value) => value.name,
                      onChanged: (value) =>
                          setState(() => _consentMode = value),
                      validator: (value) =>
                          value == null ? 'Please select consent mode' : null,
                    ),
                  ]),
                  const SizedBox(height: 24),
                  FilledButton.icon(
                    key: const ValueKey('registration-save-button'),
                    onPressed: _creating || _createdPatientId != null
                        ? null
                        : _submit,
                    icon: _creating
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.check_circle_outline),
                    label: Text(
                      _creating ? 'Submitting...' : 'Register Patient',
                    ),
                  ),
                  if (_createdPatientId != null)
                    Padding(
                      padding: EdgeInsets.only(top: 12),
                      child: Text('Patient registered. ID: $_createdPatientId'),
                    ),
                  if (_createdPatientId != null)
                    FilledButton.tonal(
                      onPressed: () =>
                          context.push('/patient/$_createdPatientId'),
                      child: const Text('Open patient profile'),
                    ),
                  if (_createError != null)
                    Text(
                      _createError!,
                      style: TextStyle(color: theme.colorScheme.error),
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

  Widget _textField(
    TextEditingController controller,
    String label,
    String keyValue, {
    bool required = false,
    TextInputType? keyboard,
    String? Function(String?)? validator,
  }) => TextFormField(
    key: ValueKey(keyValue),
    controller: controller,
    keyboardType: keyboard,
    decoration: InputDecoration(labelText: label),
    validator:
        validator ??
        (required ? (value) => _requiredError(value, label) : null),
  );

  Widget _dropdown<T>({
    required Key key,
    required String label,
    required T? value,
    required List<T> items,
    required String Function(T) labelFor,
    required ValueChanged<T?> onChanged,
    String? Function(T?)? validator,
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
    validator: validator,
  );

  Widget _consent(String label, bool value, ValueChanged<bool> onChanged) =>
      CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(label),
        value: value,
        onChanged: (selected) => setState(() => onChanged(selected ?? false)),
        controlAffinity: ListTileControlAffinity.leading,
      );

  String? _requiredError(String? value, String label) =>
      value == null || value.trim().isEmpty ? 'Please enter $label' : null;

  String? _mobileError(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Please enter mobile number';
    }
    if (!RegExp(r'^\+?[0-9]+$').hasMatch(value.trim())) {
      return 'Please enter a valid mobile number';
    }
    return null;
  }

  int? _optionalInt(String value) =>
      value.trim().isEmpty ? null : int.tryParse(value.trim());

  DateTime? _parseDateOfBirth() {
    final parts = _dateOfBirthController.text.split('/');
    if (parts.length != 3) return null;
    return DateTime(
      int.parse(parts[2]),
      int.parse(parts[1]),
      int.parse(parts[0]),
    );
  }
}
