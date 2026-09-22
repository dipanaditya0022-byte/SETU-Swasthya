import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import '../api_service.dart';
import '../core/theme/app_theme.dart';
import '../models/patient.dart';

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  final _apiService = ApiService.instance;

  int _totalPatients = 0;
  int _totalReferrals = 0;
  int _pendingReferrals = 0;
  int _emergencyReferrals = 0;
  int _priorityReferrals = 0;
  List<MapEntry<String, int>> _facilityCounts = const [];
  bool _isLoading = true;
  String? _backendError;

  @override
  void initState() {
    super.initState();
    _loadBackendReportData();
  }

  Future<void> _loadBackendReportData() async {
    try {
      final results = await Future.wait<List<Map<String, dynamic>>>([
        _apiService.getPatients(),
        _apiService.getFacilities(),
      ]);
      final patients = results[0];
      final facilities = results[1];
      final facilityNames = <String, String>{};
      final facilityIds = <String>[];

      for (final facility in facilities) {
        final id = (facility['id'] ?? '').toString().trim();
        final name = (facility['name'] ?? '').toString().trim();
        if (id.isNotEmpty && name.isNotEmpty) {
          facilityNames[id] = name;
          facilityIds.add(id);
        }
      }

      final referralLists = await Future.wait(
        facilityIds.map((id) => _apiService.getReferrals(facilityId: id)),
      );
      final referralsById = <String, Map<String, dynamic>>{};
      for (final referrals in referralLists) {
        for (final referral in referrals) {
          final id = (referral['id'] ?? '').toString().trim();
          if (id.isNotEmpty) {
            referralsById[id] = referral;
          }
        }
      }

      final referrals = referralsById.values.toList(growable: false);
      final activeStatuses = {'initiated', 'accepted', 'in_progress'};
      final facilityCounts = <String, int>{};
      var pendingReferrals = 0;
      var emergencyReferrals = 0;
      var priorityReferrals = 0;

      for (final referral in referrals) {
        final status = (referral['status'] ?? '').toString().toLowerCase();
        if (activeStatuses.contains(status)) {
          pendingReferrals++;
        }

        final urgency = (referral['urgency'] ?? '').toString().toLowerCase();
        if (urgency == 'emergency') {
          emergencyReferrals++;
        } else if (urgency == 'priority') {
          priorityReferrals++;
        }

        final destinationId = (referral['destination_facility_id'] ?? '')
            .toString();
        final destinationName = facilityNames[destinationId] ?? destinationId;
        if (destinationName.isNotEmpty) {
          facilityCounts.update(
            destinationName,
            (value) => value + 1,
            ifAbsent: () => 1,
          );
        }
      }

      final sortedFacilities = facilityCounts.entries.toList()
        ..sort((a, b) => b.value.compareTo(a.value));

      if (!mounted) return;
      setState(() {
        _totalPatients = patients.length;
        _totalReferrals = referrals.length;
        _pendingReferrals = pendingReferrals;
        _emergencyReferrals = emergencyReferrals;
        _priorityReferrals = priorityReferrals;
        _facilityCounts = sortedFacilities;
        _isLoading = false;
        _backendError = null;
      });
    } on NetworkException catch (error) {
      _setBackendError(error.message);
    } on AuthenticationException catch (error) {
      _setBackendError(error.message);
    } catch (_) {
      _setBackendError('Unable to load backend report data.');
    }
  }

  void _setBackendError(String message) {
    if (!mounted) return;
    setState(() {
      _isLoading = false;
      _backendError = message;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: AppTheme.textPrimary,
        title: const Text(
          'Reports & Analytics',
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
            final width = constraints.maxWidth > 850
                ? 820.0
                : constraints.maxWidth;

            return Center(
              child: SizedBox(
                width: width,
                child: ValueListenableBuilder(
                  valueListenable: Hive.box<PatientLocal>('patients')
                      .listenable(),
                  builder: (context, Box<PatientLocal> patientBox, _) {
                    final pendingSyncPatients = patientBox.values
                        .where((patient) => !patient.synced)
                        .length;

                    return ListView(
                      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
                      children: [
                        _buildHeader(),
                        if (_backendError != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 12),
                            child: Text(
                              'Backend reporting unavailable: $_backendError',
                              style: const TextStyle(
                                color: AppTheme.error,
                                fontSize: 12,
                              ),
                            ),
                          ),
                        const SizedBox(height: 16),
                        if (_isLoading)
                          const Padding(
                            padding: EdgeInsets.only(bottom: 16),
                            child: LinearProgressIndicator(),
                          ),
                        _buildMetricsGrid(
                          totalPatients: _totalPatients,
                          pendingSyncPatients: pendingSyncPatients,
                          totalReferrals: _totalReferrals,
                          pendingReferrals: _pendingReferrals,
                        ),
                        const SizedBox(height: 16),
                        _buildReferralBreakdown(
                          emergencyReferrals: _emergencyReferrals,
                          priorityReferrals: _priorityReferrals,
                          pendingReferrals: _pendingReferrals,
                          totalReferrals: _totalReferrals,
                          facilityCounts: _facilityCounts,
                        ),
                      ],
                    );
                  },
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFEAF4F5),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFC7DFE2)),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.analytics_outlined, color: AppTheme.primary, size: 24),
          SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Operational Overview',
                  style: TextStyle(
                    color: AppTheme.primary,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                SizedBox(height: 5),
                Text(
                  'Live local data from the facility registry and referral queue.',
                  style: TextStyle(
                    color: AppTheme.textSecondary,
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

  Widget _buildMetricsGrid({
    required int totalPatients,
    required int pendingSyncPatients,
    required int totalReferrals,
    required int pendingReferrals,
  }) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final cards = [
          _metricCard(
            label: 'Total Registered',
            value: '$totalPatients',
            icon: Icons.people_outline,
            iconColor: AppTheme.primary,
          ),
          _metricCard(
            label: 'Pending Sync',
            value: '$pendingSyncPatients',
            icon: Icons.sync_outlined,
            iconColor: AppTheme.warning,
          ),
          _metricCard(
            label: 'Total Referrals',
            value: '$totalReferrals',
            icon: Icons.alt_route_outlined,
            iconColor: const Color(0xFF6D4EB2),
          ),
          _metricCard(
            label: 'Pending Referrals',
            value: '$pendingReferrals',
            icon: Icons.pending_actions_outlined,
            iconColor: AppTheme.warning,
          ),
        ];

        if (constraints.maxWidth >= 560) {
          return Column(
            children: [
              Row(
                children: [
                  Expanded(child: cards[0]),
                  const SizedBox(width: 12),
                  Expanded(child: cards[1]),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: cards[2]),
                  const SizedBox(width: 12),
                  Expanded(child: cards[3]),
                ],
              ),
            ],
          );
        }

        return Column(
          children: [
            cards[0],
            const SizedBox(height: 12),
            cards[1],
            const SizedBox(height: 12),
            cards[2],
            const SizedBox(height: 12),
            cards[3],
          ],
        );
      },
    );
  }

  Widget _metricCard({
    required String label,
    required String value,
    required IconData icon,
    required Color iconColor,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: _cardDecoration(),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: iconColor.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(icon, color: iconColor, size: 23),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  label,
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildReferralBreakdown({
    required int emergencyReferrals,
    required int priorityReferrals,
    required int pendingReferrals,
    required int totalReferrals,
    required List<MapEntry<String, int>> facilityCounts,
  }) {
    return Column(
      children: [
        _sectionCard(
          title: 'Referral Breakdown',
          icon: Icons.assignment_outlined,
          child: Column(
            children: [
              _summaryRow(
                label: 'Emergency referrals',
                value: '$emergencyReferrals',
                color: AppTheme.error,
                icon: Icons.warning_amber_rounded,
              ),
              const Divider(height: 24),
              _summaryRow(
                label: 'Priority referrals',
                value: '$priorityReferrals',
                color: AppTheme.warning,
                icon: Icons.priority_high_rounded,
              ),
              const Divider(height: 24),
              _summaryRow(
                label: 'Pending referrals',
                value: '$pendingReferrals',
                color: AppTheme.primary,
                icon: Icons.pending_actions_outlined,
              ),
              const Divider(height: 24),
              _summaryRow(
                label: 'Total referrals',
                value: '$totalReferrals',
                color: AppTheme.success,
                icon: Icons.fact_check_outlined,
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        _sectionCard(
          title: 'Destination Facilities',
          icon: Icons.local_hospital_outlined,
          child: facilityCounts.isEmpty
              ? const Center(
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: 16),
                    child: Text(
                      'No referral data available yet.',
                      style: TextStyle(
                        color: AppTheme.textSecondary,
                        fontSize: 13,
                      ),
                    ),
                  ),
                )
              : Column(
                  children: facilityCounts.map((entry) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              entry.key,
                              style: const TextStyle(
                                color: AppTheme.textPrimary,
                                fontSize: 12,
                              ),
                            ),
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 10,
                              vertical: 5,
                            ),
                            decoration: BoxDecoration(
                              color: AppTheme.primary.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              '${entry.value}',
                              style: const TextStyle(
                                color: AppTheme.primary,
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList(),
                ),
        ),
      ],
    );
  }

  Widget _sectionCard({
    required String title,
    required IconData icon,
    required Widget child,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: _cardDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: AppTheme.primary, size: 21),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }

  Widget _summaryRow({
    required String label,
    required String value,
    required IconData icon,
    required Color color,
  }) {
    return Row(
      children: [
        Icon(icon, color: color, size: 21),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12),
          ),
        ),
        Text(
          value,
          style: const TextStyle(
            fontWeight: FontWeight.w800,
            fontSize: 15,
            color: AppTheme.textPrimary,
          ),
        ),
      ],
    );
  }

  BoxDecoration _cardDecoration() {
    return BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFD9E0E2)),
    );
  }
}
