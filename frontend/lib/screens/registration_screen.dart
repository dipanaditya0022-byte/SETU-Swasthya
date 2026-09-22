import 'dart:math';

import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import '../api_service.dart';
import '../models/patient.dart';

class RegistrationScreen extends StatefulWidget {
  const RegistrationScreen({super.key});

  @override
  State<RegistrationScreen> createState() => _RegistrationScreenState();
}

class _RegistrationScreenState extends State<RegistrationScreen> {
  static const String _facilityId =
      '5623cb23-b615-4eeb-acdb-cc5b5159b639';

  final _formKey = GlobalKey<FormState>();
  final ApiService _apiService = ApiService();

  final _nameController = TextEditingController();
  final _dobController = TextEditingController();
  final _phoneController = TextEditingController();
  final _idController = TextEditingController();
  final _addressController = TextEditingController();
  final _householdHeadController = TextEditingController();
  final _relationController = TextEditingController();

  String? _selectedGender;
  bool _isLoading = false;

  @override
  void dispose() {
    _nameController.dispose();
    _dobController.dispose();
    _phoneController.dispose();
    _idController.dispose();
    _addressController.dispose();
    _householdHeadController.dispose();
    _relationController.dispose();
    super.dispose();
  }

  Future<void> _selectDateOfBirth() async {
    final now = DateTime.now();

    final selectedDate = await showDatePicker(
      context: context,
      initialDate: DateTime(
        now.year - 25,
        now.month,
        now.day,
      ),
      firstDate: DateTime(1900),
      lastDate: now,
      helpText: 'Select date of birth',
    );

    if (selectedDate == null || !mounted) {
      return;
    }

    final day = selectedDate.day.toString().padLeft(2, '0');
    final month = selectedDate.month.toString().padLeft(2, '0');
    final year = selectedDate.year.toString();

    setState(() {
      _dobController.text = '$day/$month/$year';
    });
  }

  String _generateClientUuid() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));

    bytes[6] = (bytes[6] & 0x0F) | 0x40;
    bytes[8] = (bytes[8] & 0x3F) | 0x80;

    final chars = <String>[];
    for (final byte in bytes) {
      chars.add(byte.toRadixString(16).padLeft(2, '0'));
    }

    final uuid = <String>[
      '${chars[0]}${chars[1]}${chars[2]}${chars[3]}',
      '${chars[4]}${chars[5]}',
      '${chars[6]}${chars[7]}',
      '${chars[8]}${chars[9]}',
      '${chars[10]}${chars[11]}${chars[12]}${chars[13]}${chars[14]}${chars[15]}',
    ].join('-');

    return uuid;
  }

  int _calculateAgeFromDob(String dobText) {
    final parts = dobText.split('/');
    if (parts.length != 3) {
      throw const FormatException('Invalid date of birth');
    }

    final day = int.tryParse(parts[0]);
    final month = int.tryParse(parts[1]);
    final year = int.tryParse(parts[2]);

    if (day == null || month == null || year == null) {
      throw const FormatException('Invalid date of birth');
    }

    final birthDate = DateTime(year, month, day);
    final now = DateTime.now();

    var age = now.year - birthDate.year;
    if (now.month < birthDate.month ||
        (now.month == birthDate.month && now.day < birthDate.day)) {
      age--;
    }

    return age;
  }

  String _normalizePhone(String value) {
    final trimmed = value.trim();
    final digits = trimmed.replaceAll(RegExp(r'\D'), '');

    if (digits.isEmpty) {
      return trimmed;
    }

    if (trimmed.startsWith('+91')) {
      return '+91${digits.substring(2)}';
    }

    if (trimmed.startsWith('91') && digits.length >= 10) {
      return '+$digits';
    }

    if (digits.length == 10) {
      return '+91$digits';
    }

    return '+$digits';
  }

  Future<void> _savePatientLocally({
    required String clientUuid,
    required String name,
    required int age,
    required String village,
    required String phone,
    required bool synced,
    String? backendPatientId,
  }) async {
    final patientBox = Hive.box<PatientLocal>('patients');

    if (patientBox.containsKey(clientUuid)) {
      return;
    }

    final patientRecord = PatientLocal(
      clientUuid: clientUuid,
      name: name,
      age: age,
      village: village,
      synced: synced,
      phone: phone,
      facilityId: _facilityId,
      backendPatientId: backendPatientId,
    );

    await patientBox.put(clientUuid, patientRecord);
  }

  Future<void> _registerCitizen() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    if (_selectedGender == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please select a gender.'),
        ),
      );
      return;
    }

    final name = _nameController.text.trim();
    final village = _addressController.text.trim();

    if (village.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Please enter the residential address; this is used as the patient village/locality for backend registration.',
          ),
        ),
      );
      return;
    }

    int age;
    try {
      age = _calculateAgeFromDob(_dobController.text.trim());
    } catch (_) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please enter a valid date of birth.'),
        ),
      );
      return;
    }

    final phone = _normalizePhone(_phoneController.text);
    final clientUuid = _generateClientUuid();

    setState(() {
      _isLoading = true;
    });

    try {
      final createdPatient = await _apiService.createPatient(
        name: name,
        age: age,
        village: village,
        phone: phone,
        facilityId: _facilityId,
        clientUuid: clientUuid,
      );

      final backendPatientId = (createdPatient['id'] ?? '').toString().trim();

      await _savePatientLocally(
        clientUuid: clientUuid,
        name: name,
        age: age,
        village: village,
        phone: phone,
        synced: true,
        backendPatientId: backendPatientId.isEmpty ? null : backendPatientId,
      );

      if (!mounted) {
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Citizen registered successfully.'),
        ),
      );

      if (Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
      }
    } on NetworkException {
      await _savePatientLocally(
        clientUuid: clientUuid,
        name: name,
        age: age,
        village: village,
        phone: phone,
        synced: false,
      );

      if (!mounted) {
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Saved locally. It will sync when the connection is restored.',
          ),
        ),
      );
    } on AuthenticationException catch (e) {
      if (!mounted) {
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.message),
        ),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Unable to register the citizen. Please check the details and try again.',
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
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
          'Add Citizen',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
          ),
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(
            height: 1,
            color: const Color(0xFFD9E0E2),
          ),
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
                    padding: const EdgeInsets.fromLTRB(
                      16,
                      16,
                      16,
                      32,
                    ),
                    children: [
                      _buildSection(
                        title: 'Personal Details',
                        children: [
                          _buildTextField(
                            controller: _nameController,
                            label: 'Full Name',
                            hint: 'e.g. John Doe',
                            icon: Icons.person_outline,
                            validator: (value) {
                              if (value == null ||
                                  value.trim().isEmpty) {
                                return 'Please enter the full name';
                              }

                              if (value.trim().length < 2) {
                                return 'Enter a valid name';
                              }

                              return null;
                            },
                          ),
                          const SizedBox(height: 14),
                          _buildTextField(
                            controller: _dobController,
                            label: 'Date of Birth',
                            hint: 'dd/mm/yyyy',
                            icon: Icons.calendar_today_outlined,
                            readOnly: true,
                            onTap: _selectDateOfBirth,
                            validator: (value) {
                              if (value == null ||
                                  value.trim().isEmpty) {
                                return 'Please select date of birth';
                              }

                              return null;
                            },
                          ),
                          const SizedBox(height: 14),
                          _buildGenderSelector(),
                          const SizedBox(height: 14),
                          _buildTextField(
                            controller: _phoneController,
                            label: 'Phone Number',
                            hint: '+91',
                            icon: Icons.phone_outlined,
                            keyboardType: TextInputType.phone,
                            validator: (value) {
                              final phone =
                                  value?.trim() ?? '';

                              if (phone.isEmpty) {
                                return 'Please enter phone number';
                              }

                              final digits = phone.replaceAll(
                                RegExp(r'\D'),
                                '',
                              );

                              if (digits.length < 10) {
                                return 'Enter a valid phone number';
                              }

                              return null;
                            },
                          ),
                          const SizedBox(height: 14),
                          _buildTextField(
                            controller: _idController,
                            label: 'Aadhaar / ID Number',
                            hint: 'XXXX XXXX XXXX',
                            icon: Icons.badge_outlined,
                          ),
                          const SizedBox(height: 14),
                          _buildTextField(
                            controller: _addressController,
                            label: 'Residential Address',
                            hint: 'Enter full address...',
                            icon: Icons.location_on_outlined,
                            maxLines: 3,
                            validator: (value) {
                              final address = value?.trim() ?? '';

                              if (address.isEmpty) {
                                return 'Please enter the residential address; this is used as the patient village/locality for backend registration.';
                              }

                              return null;
                            },
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      _buildSection(
                        title: 'Household Details',
                        children: [
                          _buildTextField(
                            controller: _householdHeadController,
                            label: 'Head of Household Name',
                            hint: 'Name of household head',
                            icon: Icons.groups_outlined,
                          ),
                          const SizedBox(height: 14),
                          _buildTextField(
                            controller: _relationController,
                            label: 'Relation to Head',
                            hint: 'e.g. Son, Daughter, Self',
                            icon: Icons.family_restroom_outlined,
                          ),
                        ],
                      ),
                      const SizedBox(height: 20),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor:
                                const Color(0xFF075965),
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(
                              vertical: 15,
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius:
                                  BorderRadius.circular(6),
                            ),
                          ),
                          onPressed:
                              _isLoading ? null : _registerCitizen,
                          child: _isLoading
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child:
                                      CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
                                )
                              : const Text(
                                  'Register Citizen',
                                  style: TextStyle(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
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

  Widget _buildSection({
    required String title,
    required List<Widget> children,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(
          color: const Color(0xFFD9E0E2),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: Color(0xFF075965),
            ),
          ),
          const SizedBox(height: 12),
          ...children,
        ],
      ),
    );
  }

  Widget _buildTextField({
    required TextEditingController controller,
    required String label,
    required String hint,
    required IconData icon,
    TextInputType? keyboardType,
    String? Function(String?)? validator,
    bool readOnly = false,
    VoidCallback? onTap,
    int maxLines = 1,
  }) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      validator: validator,
      readOnly: readOnly,
      onTap: onTap,
      maxLines: maxLines,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        prefixIcon: Icon(
          icon,
          size: 20,
          color: const Color(0xFF5D6B6F),
        ),
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 13,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(5),
          borderSide: const BorderSide(
            color: Color(0xFFBFC9CC),
          ),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(5),
          borderSide: const BorderSide(
            color: Color(0xFFBFC9CC),
          ),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(5),
          borderSide: const BorderSide(
            color: Color(0xFF075965),
            width: 1.5,
          ),
        ),
      ),
    );
  }

  Widget _buildGenderSelector() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Gender',
          style: TextStyle(
            fontSize: 12,
            color: Color(0xFF526064),
          ),
        ),
        const SizedBox(height: 5),
        RadioGroup<String>(
  groupValue: _selectedGender,
  onChanged: (value) {
    setState(() {
      _selectedGender = value;
    });
  },
  child: Row(
    children: [
      _buildGenderOption('Male'),
      _buildGenderOption('Female'),
      _buildGenderOption('Other'),
    ],
  ),
),
      ],
    );
  }

  Widget _buildGenderOption(String gender) {
  return Expanded(
    // RadioListTile paints its ink splash/selection highlight on the
    // nearest Material ancestor -- _buildSection's own white-background
    // Container (not a Material) sits between this and the Scaffold,
    // which made those effects invisible (confirmed live via Flutter's
    // own "ListTile background color or ink splashes may be invisible"
    // assertion). `type: MaterialType.transparency` provides that
    // Material surface locally without painting any visible background
    // of its own, so the section's white card styling is untouched.
    child: Material(
      type: MaterialType.transparency,
      child: RadioListTile<String>(
        value: gender,
        title: Text(
          gender,
          style: const TextStyle(
            fontSize: 12,
          ),
        ),
        contentPadding: EdgeInsets.zero,
        dense: true,
        activeColor: const Color(0xFF075965),
      ),
    ),
  );
}
}