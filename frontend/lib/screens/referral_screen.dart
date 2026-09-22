import 'package:flutter/material.dart';
import 'package:hive/hive.dart';

import '../models/referral.dart';
import '../models/referral_local.dart';
import '../api_service.dart';

class _FacilityOption {
  final String id;
  final String name;
  final String facilityType;
  final String village;
  final String district;
  final DateTime? createdAt;

  const _FacilityOption({
    required this.id,
    required this.name,
    required this.facilityType,
    required this.village,
    required this.district,
    required this.createdAt,
  });

  factory _FacilityOption.fromJson(Map<String, dynamic> json) {
    return _FacilityOption(
      id: (json['id'] ?? '').toString().trim(),
      name: (json['name'] ?? '').toString().trim(),
      facilityType: (json['facility_type'] ?? '').toString(),
      village: (json['village'] ?? '').toString(),
      district: (json['district'] ?? '').toString(),
      createdAt: DateTime.tryParse((json['created_at'] ?? '').toString()),
    );
  }
}

class ReferralScreen extends StatefulWidget {
  final String patientName;
  final String patientId;
  final String urgency;
  final String reason;

  const ReferralScreen({
    super.key,
    required this.patientName,
    required this.patientId,
    required this.urgency,
    required this.reason,
  });

  @override
  State<ReferralScreen> createState() => _ReferralScreenState();
}

class _ReferralScreenState extends State<ReferralScreen> {
  final _formKey = GlobalKey<FormState>();

  final _reasonController = TextEditingController();
  final _apiService = ApiService.instance;

  List<_FacilityOption> _facilities = const [];
  String? _selectedFacilityName;
  String? _selectedFacilityId;
  String? _backendPatientId;
  String? _sourceFacilityId;
  bool _isLoadingFacilities = true;
  String? _facilityLoadError;
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();

    _reasonController.text = widget.reason;
    _loadFacilities();
    _resolvePatientIdentity();
  }

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  Future<void> _loadFacilities() async {
    try {
      final data = await _apiService.getFacilities();
      final facilities = data
          .map(_FacilityOption.fromJson)
          .where(
            (facility) => facility.id.isNotEmpty && facility.name.isNotEmpty,
          )
          .toList(growable: false);

      if (!mounted) return;
      setState(() {
        _facilities = facilities;
        _isLoadingFacilities = false;
        _facilityLoadError = null;
      });
    } on NetworkException catch (error) {
      _setFacilityLoadError(error.message);
    } on AuthenticationException catch (error) {
      _setFacilityLoadError(error.message);
    } catch (_) {
      _setFacilityLoadError('Unable to load facilities. Please try again.');
    }
  }

  void _setFacilityLoadError(String message) {
    if (!mounted) return;
    setState(() {
      _isLoadingFacilities = false;
      _facilityLoadError = message;
    });
  }

  Future<void> _resolvePatientIdentity() async {
    try {
      final patients = await _apiService.getPatients();
      Map<String, dynamic>? patient;

      for (final item in patients) {
        if (item['id']?.toString() == widget.patientId ||
            item['client_uuid']?.toString() == widget.patientId) {
          patient = item;
          break;
        }
      }

      final backendPatientId = patient?['id']?.toString().trim();
      final sourceFacilityId = patient?['facility_id']?.toString().trim();

      if (!mounted) return;
      setState(() {
        _backendPatientId = backendPatientId?.isEmpty == true
            ? null
            : backendPatientId;
        _sourceFacilityId = sourceFacilityId?.isEmpty == true
            ? null
            : sourceFacilityId;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _backendPatientId = null;
        _sourceFacilityId = null;
      });
    }
  }

  Future<void> _createReferral() async {
    if (!_formKey.currentState!.validate() || _selectedFacilityId == null) {
      return;
    }

    if (_isSubmitting) return;

    final urgency = widget.urgency.toUpperCase() == 'EMERGENCY'
        ? ReferralUrgency.emergency
        : ReferralUrgency.priority;

    final referral = Referral(
      id: 'REF-${DateTime.now().millisecondsSinceEpoch}',
      patientId: widget.patientId,
      patientName: widget.patientName,
      sourceFacility: 'Current Facility',
      destinationFacility: _selectedFacilityName!,
      reason: _reasonController.text.trim(),
      urgency: urgency,
      status: ReferralStatus.pending,
      createdAt: DateTime.now(),
    );

    final referralLocal = ReferralLocal(
      id: referral.id,
      patientId: referral.patientId,
      patientName: referral.patientName,
      sourceFacility: referral.sourceFacility,
      destinationFacility: referral.destinationFacility,
      reason: referral.reason,
      urgency: referral.urgency.name,
      status: 'pending',
      createdAt: referral.createdAt,
    );

    Hive.box<ReferralLocal>('referrals').add(referralLocal);

    if (_backendPatientId == null || _sourceFacilityId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Referral saved locally, but the patient record is not ready for backend submission.',
          ),
        ),
      );
      return;
    }

    setState(() {
      _isSubmitting = true;
    });

    try {
      await _apiService.createReferral(
        patientId: _backendPatientId!,
        fromFacilityId: _sourceFacilityId!,
        destinationFacilityId: _selectedFacilityId!,
        reason: referral.reason,
        urgency: referral.urgency.name,
      );

      if (!mounted) return;
      Navigator.pop(context, referral);
    } on NetworkException catch (error) {
      _showSubmissionFailure(error.message);
    } on AuthenticationException catch (error) {
      _showSubmissionFailure(error.message);
    } catch (_) {
      _showSubmissionFailure(
        'Referral saved locally, but backend submission failed. Please try again later.',
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  void _showSubmissionFailure(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Referral saved locally, but backend submission failed: $message',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isEmergency = widget.urgency.toUpperCase() == 'EMERGENCY';

    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF12343B),
        title: const Text(
          'Create Referral',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
        ),
      ),
      body: SafeArea(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: isEmergency
                      ? const Color(0xFFFFEBEE)
                      : const Color(0xFFFFF4E5),
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(
                    color: isEmergency
                        ? const Color(0xFFE57373)
                        : const Color(0xFFFFCC80),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      isEmergency
                          ? Icons.warning_rounded
                          : Icons.priority_high_rounded,
                      color: isEmergency
                          ? const Color(0xFFC62828)
                          : const Color(0xFFEF8C00),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        '${widget.urgency} referral required',
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: isEmergency
                              ? const Color(0xFFB71C1C)
                              : const Color(0xFF9A5A00),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 16),

              _sectionCard(
                title: 'Patient',
                icon: Icons.person_outline,
                children: [
                  Text(
                    widget.patientName,
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Patient ID: ${widget.patientId}',
                    style: const TextStyle(
                      color: Color(0xFF687477),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),

              const SizedBox(height: 16),

              _sectionCard(
                title: 'Referral Details',
                icon: Icons.assignment_outlined,
                children: [
                  DropdownButtonFormField<String>(
                    initialValue: _selectedFacilityName,
                    hint: Text(
                      _isLoadingFacilities
                          ? 'Loading facilities...'
                          : _facilityLoadError ??
                                'Select a destination facility',
                    ),
                    decoration: InputDecoration(
                      labelText: 'Destination Facility',
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(7),
                      ),
                    ),
                    items: _facilities.map((facility) {
                      return DropdownMenuItem(
                        value: facility.name,
                        child: Text(facility.name),
                      );
                    }).toList(),
                    isExpanded: true,
                    onChanged: (value) {
                      if (value == null) return;
                      final selectedFacility = _facilities.firstWhere(
                        (facility) => facility.name == value,
                      );
                      setState(() {
                        _selectedFacilityName = selectedFacility.name;
                        _selectedFacilityId = selectedFacility.id;
                      });
                    },
                    validator: (value) {
                      if (value == null ||
                          value.isEmpty ||
                          _selectedFacilityId == null) {
                        return 'Select a destination facility';
                      }
                      return null;
                    },
                  ),

                  const SizedBox(height: 16),

                  TextFormField(
                    controller: _reasonController,
                    maxLines: 4,
                    decoration: InputDecoration(
                      labelText: 'Reason for Referral',
                      alignLabelWithHint: true,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(7),
                      ),
                    ),
                    validator: (value) {
                      if (value == null || value.trim().isEmpty) {
                        return 'Enter the referral reason';
                      }
                      return null;
                    },
                  ),
                ],
              ),

              const SizedBox(height: 20),

              SizedBox(
                height: 52,
                child: FilledButton.icon(
                  onPressed: _isSubmitting ? null : _createReferral,
                  style: FilledButton.styleFrom(
                    backgroundColor: isEmergency
                        ? const Color(0xFFC62828)
                        : const Color(0xFF075965),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(7),
                    ),
                  ),
                  icon: _isSubmitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.send_outlined),
                  label: const Text(
                    'Create Referral',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ),

              const SizedBox(height: 12),

              const Text(
                'Referral decisions should follow approved clinical protocols and local escalation procedures.',
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
  }

  Widget _sectionCard({
    required String title,
    required IconData icon,
    required List<Widget> children,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: const Color(0xFFD9E0E2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: const Color(0xFF075965), size: 21),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF172124),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          ...children,
        ],
      ),
    );
  }
}
