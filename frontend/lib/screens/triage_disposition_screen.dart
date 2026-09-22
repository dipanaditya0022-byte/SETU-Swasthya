import 'package:flutter/material.dart';

import '../api_service.dart';
import '../models/patient.dart';
import 'referral_screen.dart';

class TriageDispositionScreen extends StatefulWidget {
  final PatientLocal patient;
  final String bp;
  final double hb;
  final int gestationWeeks;

  const TriageDispositionScreen({
    super.key,
    required this.patient,
    required this.bp,
    required this.hb,
    required this.gestationWeeks,
  });

  @override
  State<TriageDispositionScreen> createState() =>
      _TriageDispositionScreenState();
}

class _TriageDispositionScreenState extends State<TriageDispositionScreen> {
  final ApiService _apiService = ApiService.instance;
  bool _isSubmitting = true;
  bool _hasSubmitError = false;
  String? _submitError;

  @override
  void initState() {
    super.initState();
    _submitEncounter();
  }

  Future<void> _submitEncounter() async {
    setState(() {
      _isSubmitting = true;
      _hasSubmitError = false;
      _submitError = null;
    });

    final disposition = _evaluateRisk(widget.bp, widget.hb);
    final backendPatientId = widget.patient.backendPatientId?.trim();

    if (backendPatientId == null || backendPatientId.isEmpty) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isSubmitting = false;
        _hasSubmitError = true;
        _submitError = 'This patient is missing the backend patient ID. Please refresh the patient list and try again.';
      });
      return;
    }

    try {
      await _apiService.createTriage(
        patientId: backendPatientId,
        facilityId: widget.patient.facilityId,
        triageDisposition: disposition,
      );

      if (!mounted) {
        return;
      }

      setState(() {
        _isSubmitting = false;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isSubmitting = false;
        _hasSubmitError = true;
        _submitError = error is AuthenticationException
            ? error.message
            : error is NetworkException
            ? error.message
            : error.toString();
      });
    }
  }

  String _evaluateRisk(String bpString, double hemoglobin) {
    try {
      final parts = bpString.split('/');

      if (parts.length != 2) {
        return 'ROUTINE';
      }

      final systolic = int.parse(parts[0].trim());
      final diastolic = int.parse(parts[1].trim());

      if (systolic >= 160 || diastolic >= 110 || hemoglobin < 7.0) {
        return 'EMERGENCY';
      }

      if ((systolic >= 140 && systolic < 160) ||
          (diastolic >= 90 && diastolic < 110) ||
          (hemoglobin >= 7.0 && hemoglobin < 10.0)) {
        return 'PRIORITY';
      }
    } catch (_) {
      return 'ROUTINE';
    }

    return 'ROUTINE';
  }

  _RiskPresentation _presentation(String riskLevel) {
    switch (riskLevel) {
      case 'EMERGENCY':
        return const _RiskPresentation(
          background: Color(0xFFFFEBEE),
          border: Color(0xFFE57373),
          iconBackground: Color(0xFFC62828),
          text: Color(0xFFB71C1C),
          icon: Icons.warning_rounded,
          title: 'Emergency',
          description: 'Immediate clinical attention is required.',
          action: 'Arrange immediate physician evaluation and prepare for emergency referral according to approved clinical protocol.',
        );

      case 'PRIORITY':
        return const _RiskPresentation(
          background: Color(0xFFFFF4E5),
          border: Color(0xFFFFCC80),
          iconBackground: Color(0xFFEF8C00),
          text: Color(0xFF9A5A00),
          icon: Icons.priority_high_rounded,
          title: 'Priority',
          description: 'The patient requires timely clinical review.',
          action: 'Review by the appropriate medical officer within the recommended timeframe and follow the approved care protocol.',
        );

      default:
        return const _RiskPresentation(
          background: Color(0xFFEAF7EF),
          border: Color(0xFFA5D6B7),
          iconBackground: Color(0xFF2E7D4F),
          text: Color(0xFF21643D),
          icon: Icons.check_circle_rounded,
          title: 'Routine',
          description:
              'No high-risk indicator was identified by this assessment.',
          action: 'Continue routine care and follow the next scheduled clinical review according to protocol.',
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final riskLevel = _evaluateRisk(widget.bp, widget.hb);
    final presentation = _presentation(riskLevel);

    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF12343B),
        title: const Text(
          'Triage Result',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: const Color(0xFFD9E0E2)),
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
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 18, 16, 30),
                  children: [
                    if (_isSubmitting)
                      Container(
                        padding: const EdgeInsets.all(12),
                        margin: const EdgeInsets.only(bottom: 12),
                        decoration: BoxDecoration(
                          color: const Color(0xFFEAF4F5),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFFC7DFE2)),
                        ),
                        child: const Row(
                          children: [
                            SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                            SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                'Saving triage encounter...',
                                style: TextStyle(
                                  color: Color(0xFF075965),
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                      )
                    else if (_hasSubmitError)
                      Container(
                        padding: const EdgeInsets.all(14),
                        margin: const EdgeInsets.only(bottom: 12),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFFF3F3),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFFE57373)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Unable to save triage encounter',
                              style: TextStyle(
                                color: Color(0xFFB71C1C),
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              _submitError ?? 'Please try again.',
                              style: const TextStyle(color: Color(0xFF7A1C1C)),
                            ),
                            const SizedBox(height: 10),
                            FilledButton.icon(
                              onPressed: _submitEncounter,
                              icon: const Icon(Icons.refresh),
                              label: const Text('Retry'),
                              style: FilledButton.styleFrom(
                                backgroundColor: const Color(0xFF075965),
                                foregroundColor: Colors.white,
                              ),
                            ),
                          ],
                        ),
                      )
                    else
                      const SizedBox.shrink(),
                    _buildRiskCard(presentation),
                    const SizedBox(height: 16),
                    _buildVitalsCard(),
                    const SizedBox(height: 16),
                    _buildActionCard(presentation),
                    const SizedBox(height: 20),
                    _buildClinicalNotice(),
                    const SizedBox(height: 20),
                    if (riskLevel == 'EMERGENCY' ||
                        riskLevel == 'PRIORITY') ...[
                      SizedBox(
                        width: double.infinity,
                        height: 52,
                        child: FilledButton.icon(
                          onPressed: () async {
                            final referral = await Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => ReferralScreen(
                                  patientName: widget.patient.name,
                                  patientId: widget.patient.clientUuid,
                                  urgency: riskLevel,
                                  reason: presentation.action,
                                ),
                              ),
                            );

                            if (!context.mounted || referral == null) {
                              return;
                            }

                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text('Referral created successfully.'),
                              ),
                            );
                          },
                          style: FilledButton.styleFrom(
                            backgroundColor: riskLevel == 'EMERGENCY'
                                ? const Color(0xFFC62828)
                                : const Color(0xFF075965),
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(7),
                            ),
                          ),
                          icon: const Icon(Icons.send_outlined),
                          label: Text(
                            riskLevel == 'EMERGENCY'
                                ? 'Create Emergency Referral'
                                : 'Create Referral',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: OutlinedButton.icon(
                        onPressed: () => Navigator.pop(context),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: const Color(0xFF075965),
                          side: const BorderSide(color: Color(0xFF075965)),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(7),
                          ),
                        ),
                        icon: const Icon(Icons.arrow_back),
                        label: const Text(
                          'Back to Triage',
                          style: TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildRiskCard(_RiskPresentation presentation) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: presentation.background,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: presentation.border, width: 1.5),
      ),
      child: Column(
        children: [
          Container(
            width: 58,
            height: 58,
            decoration: BoxDecoration(
              color: presentation.iconBackground,
              shape: BoxShape.circle,
            ),
            child: Icon(presentation.icon, color: Colors.white, size: 30),
          ),
          const SizedBox(height: 14),
          const Text(
            'RISK DISPOSITION',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1,
              color: Color(0xFF687477),
            ),
          ),
          const SizedBox(height: 6),
          Text(
            presentation.title,
            style: TextStyle(
              color: presentation.text,
              fontSize: 28,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            presentation.description,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: Color(0xFF566367),
              fontSize: 12,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildVitalsCard() {
    return _sectionCard(
      title: 'Evaluated Vitals',
      icon: Icons.monitor_heart_outlined,
      children: [
        _vitalRow(
          icon: Icons.favorite_outline,
          label: 'Blood Pressure',
          value: widget.bp,
          unit: 'mmHg',
        ),
        const Divider(height: 24),
        _vitalRow(
          icon: Icons.bloodtype_outlined,
          label: 'Hemoglobin',
          value: widget.hb.toStringAsFixed(1),
          unit: 'g/dL',
        ),
        const Divider(height: 24),
        _vitalRow(
          icon: Icons.calendar_month_outlined,
          label: 'Gestation',
          value: '${widget.gestationWeeks}',
          unit: 'weeks',
        ),
      ],
    );
  }

  Widget _vitalRow({
    required IconData icon,
    required String label,
    required String value,
    required String unit,
  }) {
    return Row(
      children: [
        Icon(icon, color: const Color(0xFF075965), size: 21),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: Color(0xFF5E6A6E), fontSize: 13),
          ),
        ),
        Text(
          value,
          style: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: Color(0xFF172124),
          ),
        ),
        const SizedBox(width: 5),
        Text(
          unit,
          style: const TextStyle(fontSize: 11, color: Color(0xFF7A8588)),
        ),
      ],
    );
  }

  Widget _buildActionCard(_RiskPresentation presentation) {
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
              const Icon(
                Icons.assignment_outlined,
                color: Color(0xFF075965),
                size: 21,
              ),
              const SizedBox(width: 8),
              const Text(
                'Recommended Action',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF172124),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: presentation.background,
              borderRadius: BorderRadius.circular(7),
            ),
            child: Text(
              presentation.action,
              style: const TextStyle(
                fontSize: 12,
                height: 1.5,
                color: Color(0xFF465255),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildClinicalNotice() {
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F3F4),
        borderRadius: BorderRadius.circular(7),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, size: 18, color: Color(0xFF657276)),
          SizedBox(width: 9),
          Expanded(
            child: Text(
              'This is an initial decision-support assessment. '
              'It does not replace professional clinical judgment '
              'or approved emergency protocols.',
              style: TextStyle(
                fontSize: 11,
                height: 1.4,
                color: Color(0xFF657276),
              ),
            ),
          ),
        ],
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

class _RiskPresentation {
  final Color background;
  final Color border;
  final Color iconBackground;
  final Color text;
  final IconData icon;
  final String title;
  final String description;
  final String action;

  const _RiskPresentation({
    required this.background,
    required this.border,
    required this.iconBackground,
    required this.text,
    required this.icon,
    required this.title,
    required this.description,
    required this.action,
  });
}
