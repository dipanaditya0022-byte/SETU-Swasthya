import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import '../models/patient.dart';
import 'triage_disposition_screen.dart';

class TriageFormScreen extends StatefulWidget {
  final PatientLocal? patient;

  const TriageFormScreen({super.key, this.patient});

  @override
  State<TriageFormScreen> createState() => _TriageFormScreenState();
}

class _TriageFormScreenState extends State<TriageFormScreen> {
  final _formKey = GlobalKey<FormState>();

  final _bpController = TextEditingController();
  final _hbController = TextEditingController();
  final _gestationController = TextEditingController();

  PatientLocal? _selectedPatient;

  @override
  void initState() {
    super.initState();
    _selectedPatient = widget.patient;

    _bpController.text = '120/80';
    _hbController.text = '10.5';
    _gestationController.text = '28';
  }

  @override
  void dispose() {
    _bpController.dispose();
    _hbController.dispose();
    _gestationController.dispose();
    super.dispose();
  }

  void _submitTriage() {
    if (_selectedPatient == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please select a patient before starting triage.'),
        ),
      );
      return;
    }

    if (!_formKey.currentState!.validate()) {
      return;
    }

    final bp = _bpController.text.trim();
    final hb = double.parse(_hbController.text.trim());
    final gestation = int.parse(_gestationController.text.trim());

    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => TriageDispositionScreen(
          patient: _selectedPatient!,
          bp: bp,
          hb: hb,
          gestationWeeks: gestation,
        ),
      ),
    );
  }

  String? _validateBloodPressure(String? value) {
    final text = value?.trim() ?? '';

    if (text.isEmpty) {
      return 'Please enter blood pressure';
    }

    final parts = text.split('/');

    if (parts.length != 2) {
      return 'Use the format systolic/diastolic';
    }

    final systolic = int.tryParse(parts[0].trim());
    final diastolic = int.tryParse(parts[1].trim());

    if (systolic == null || diastolic == null) {
      return 'Enter valid numbers, e.g. 120/80';
    }

    if (systolic < 50 || systolic > 300) {
      return 'Systolic value must be between 50 and 300';
    }

    if (diastolic < 30 || diastolic > 200) {
      return 'Diastolic value must be between 30 and 200';
    }

    return null;
  }

  String? _validateHemoglobin(String? value) {
    final text = value?.trim() ?? '';

    if (text.isEmpty) {
      return 'Please enter hemoglobin level';
    }

    final number = double.tryParse(text);

    if (number == null) {
      return 'Enter a valid number';
    }

    if (number <= 0 || number > 25) {
      return 'Enter a value between 0 and 25 g/dL';
    }

    return null;
  }

  String? _validateGestation(String? value) {
    final text = value?.trim() ?? '';

    if (text.isEmpty) {
      return 'Please enter gestation weeks';
    }

    final weeks = int.tryParse(text);

    if (weeks == null) {
      return 'Enter a valid whole number';
    }

    if (weeks < 1 || weeks > 45) {
      return 'Enter a value between 1 and 45 weeks';
    }

    return null;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF12343B),
        title: const Text(
          'Clinical Triage',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
        ),
      ),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final contentWidth = constraints.maxWidth > 650
                ? 620.0
                : constraints.maxWidth;

            return Center(
              child: SizedBox(
                width: contentWidth,
                child: Form(
                  key: _formKey,
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
                    children: [
                      _buildIntroCard(),
                      const SizedBox(height: 16),
                      _buildPatientSection(),
                      const SizedBox(height: 16),
                      _buildVitalsSection(),
                      const SizedBox(height: 20),
                      SizedBox(
                        width: double.infinity,
                        height: 52,
                        child: FilledButton.icon(
                          onPressed: _submitTriage,
                          style: FilledButton.styleFrom(
                            backgroundColor: const Color(0xFF075965),
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(7),
                            ),
                          ),
                          icon: const Icon(Icons.health_and_safety_outlined),
                          label: const Text(
                            'Evaluate Triage Risk',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Assessment is performed locally for offline continuity. '
                        'Clinical decisions should follow approved protocols.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: Color(0xFF7A8588),
                          fontSize: 11,
                          height: 1.4,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildIntroCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFEAF4F5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFC7DFE2)),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, color: Color(0xFF075965), size: 22),
          SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Clinical Triage Assessment',
                  style: TextStyle(
                    color: Color(0xFF075965),
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: 5),
                Text(
                  'Select the patient and enter their current maternal '
                  'indicators to generate an initial risk disposition.',
                  style: TextStyle(
                    color: Color(0xFF496064),
                    fontSize: 12,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPatientSection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFD9E0E2)),
      ),
      child: ValueListenableBuilder<Box<PatientLocal>>(
        valueListenable: Hive.box<PatientLocal>('patients').listenable(),
        builder: (context, box, _) {
          final patients = box.values.toList();

          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(
                children: [
                  Icon(
                    Icons.person_outline,
                    color: Color(0xFF075965),
                    size: 21,
                  ),
                  SizedBox(width: 8),
                  Text(
                    'Patient',
                    style: TextStyle(
                      color: Color(0xFF075965),
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              const Text(
                'Select the patient being assessed.',
                style: TextStyle(color: Color(0xFF778286), fontSize: 11),
              ),
              const SizedBox(height: 14),
              if (patients.isEmpty)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFF4E5),
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: const Row(
                    children: [
                      Icon(Icons.info_outline, color: Color(0xFF9A5A00)),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'No patients are registered yet. '
                          'Register a patient before starting triage.',
                          style: TextStyle(
                            color: Color(0xFF9A5A00),
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ],
                  ),
                )
              else
                DropdownButtonFormField<PatientLocal>(
                  initialValue: _selectedPatient,
                  isExpanded: true,
                  decoration: InputDecoration(
                    labelText: 'Patient',
                    prefixIcon: const Icon(Icons.person_outline),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(7),
                    ),
                  ),
                  items: patients.map((patient) {
                    return DropdownMenuItem<PatientLocal>(
                      value: patient,
                      child: Text(
                        '${patient.name} • Age ${patient.age}',
                        overflow: TextOverflow.ellipsis,
                      ),
                    );
                  }).toList(),
                  onChanged: widget.patient != null
                      ? null
                      : (patient) {
                          setState(() {
                            _selectedPatient = patient;
                          });
                        },
                  validator: (value) {
                    if (value == null) {
                      return 'Please select a patient';
                    }
                    return null;
                  },
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildVitalsSection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFD9E0E2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Maternal Vitals & Indicators',
            style: TextStyle(
              color: Color(0xFF075965),
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            'Enter the latest available measurements.',
            style: TextStyle(color: Color(0xFF778286), fontSize: 11),
          ),
          const SizedBox(height: 16),
          _buildField(
            controller: _bpController,
            label: 'Blood Pressure',
            hint: '120/80',
            unit: 'mmHg',
            icon: Icons.monitor_heart_outlined,
            keyboardType: TextInputType.text,
            validator: _validateBloodPressure,
          ),
          const SizedBox(height: 14),
          _buildField(
            controller: _hbController,
            label: 'Hemoglobin',
            hint: '10.5',
            unit: 'g/dL',
            icon: Icons.bloodtype_outlined,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            validator: _validateHemoglobin,
          ),
          const SizedBox(height: 14),
          _buildField(
            controller: _gestationController,
            label: 'Gestation',
            hint: '28',
            unit: 'weeks',
            icon: Icons.calendar_month_outlined,
            keyboardType: TextInputType.number,
            validator: _validateGestation,
          ),
        ],
      ),
    );
  }

  Widget _buildField({
    required TextEditingController controller,
    required String label,
    required String hint,
    required String unit,
    required IconData icon,
    required TextInputType keyboardType,
    required String? Function(String?) validator,
  }) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        prefixIcon: Icon(icon, color: const Color(0xFF5D6B6F), size: 21),
        suffixText: unit,
        suffixStyle: const TextStyle(color: Color(0xFF697579), fontSize: 12),
        filled: true,
        fillColor: const Color(0xFFFCFDFD),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: const BorderSide(color: Color(0xFFBFC9CC)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: const BorderSide(color: Color(0xFFBFC9CC)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: const BorderSide(color: Color(0xFF075965), width: 1.5),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: const BorderSide(color: Color(0xFFC62828)),
        ),
      ),
    );
  }
}
