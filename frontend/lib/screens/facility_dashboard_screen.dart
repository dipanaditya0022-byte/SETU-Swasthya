import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import '../api_service.dart';
import '../models/patient.dart';
import '../models/referral_local.dart';

class FacilityDashboardScreen extends StatefulWidget {
  const FacilityDashboardScreen({super.key});

  @override
  State<FacilityDashboardScreen> createState() =>
      _FacilityDashboardScreenState();
}

class _FacilityDashboardScreenState extends State<FacilityDashboardScreen> {
  final _apiService = ApiService();
  List<Map<String, dynamic>> _backendReferrals = const [];
  Map<String, String> _facilityNames = const {};
  bool _isLoadingReferrals = true;
  String? _referralLoadError;
  final Set<String> _updatingReferralIds = <String>{};
  String? _currentUserId;

  @override
  void initState() {
    super.initState();
    _loadCurrentUser();
    _loadBackendReferrals();
  }

  Future<void> _loadCurrentUser() async {
    try {
      final user = await _apiService.getCurrentUser();
      if (!mounted) return;
      setState(() {
        _currentUserId = user.id;
      });
    } catch (_) {
      // Non-fatal: only blocks the arrival/consulted actions below, which
      // already guard on _currentUserId being null (see _buildStatusActions).
    }
  }

  Future<void> _loadBackendReferrals() async {
    try {
      final facilities = await _apiService.getFacilities();
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

      if (!mounted) return;
      setState(() {
        _backendReferrals = referralsById.values.toList(growable: false);
        _facilityNames = facilityNames;
        _isLoadingReferrals = false;
        _referralLoadError = null;
      });
    } on NetworkException catch (error) {
      _setReferralLoadError(error.message);
    } on AuthenticationException catch (error) {
      _setReferralLoadError(error.message);
    } catch (_) {
      _setReferralLoadError('Unable to load backend referrals.');
    }
  }

  void _setReferralLoadError(String message) {
    if (!mounted) return;
    setState(() {
      _isLoadingReferrals = false;
      _referralLoadError = message;
      _backendReferrals = const [];
    });
  }

  bool _isActiveBackendReferral(Map<String, dynamic> referral) {
    final status = (referral['status'] ?? '').toString().toLowerCase();
    return status != 'completed' && status != 'cancelled' && status != 'closed';
  }

  bool _localReferralMatchesBackend(
    ReferralLocal localReferral,
    Map<String, dynamic> backendReferral,
    Box<PatientLocal> patientBox,
  ) {
    final backendPatientId = (backendReferral['patient_id'] ?? '').toString();
    final backendDestinationId =
        (backendReferral['destination_facility_id'] ?? '').toString();
    final localPatient = patientBox.values.cast<PatientLocal?>().firstWhere(
      (patient) => patient?.clientUuid == localReferral.patientId,
      orElse: () => null,
    );

    final patientMatches =
        localReferral.patientId == backendPatientId ||
        localPatient?.backendPatientId == backendPatientId;
    final destinationMatches = _facilityNames.entries.any(
      (entry) =>
          entry.key == backendDestinationId &&
          entry.value == localReferral.destinationFacility,
    );
    return patientMatches &&
        destinationMatches &&
        localReferral.reason == (backendReferral['reason'] ?? '').toString();
  }

  List<Widget> _buildReferralCards(Box<ReferralLocal> referralBox) {
    final patientBox = Hive.box<PatientLocal>('patients');
    final backendCards = _backendReferrals
        .where(_isActiveBackendReferral)
        .map(
          (referral) => _buildExceptionRow(
            (referral['id'] ?? '').toString(),
            'Patient ID: ${(referral['patient_id'] ?? '').toString()}',
            _facilityNames[(referral['destination_facility_id'] ?? '')
                    .toString()] ??
                (referral['destination_facility_id'] ?? '').toString(),
            (referral['urgency'] ?? '').toString(),
            (referral['status'] ?? '').toString(),
            (referral['reason'] ?? '').toString(),
            sourceFacility:
                _facilityNames[(referral['from_facility_id'] ?? '').toString()],
            actions: _buildStatusActions(referral),
          ),
        )
        .toList();

    final localCards = referralBox.values
        .where((referral) => referral.status.toLowerCase() == 'pending')
        .where(
          (localReferral) => !_backendReferrals.any(
            (backendReferral) => _localReferralMatchesBackend(
              localReferral,
              backendReferral,
              patientBox,
            ),
          ),
        )
        .map(
          (referral) => _buildExceptionRow(
            referral.id,
            referral.patientName,
            referral.destinationFacility,
            referral.urgency,
            referral.status,
            referral.reason,
            sourceFacility: referral.sourceFacility,
          ),
        )
        .toList();

    return [...backendCards, ...localCards];
  }

  // Backend's real state machine (app/models/referral_state.py) -- NOT the
  // 4-stage INITIATED/ACCEPTED/IN_PROGRESS/COMPLETED model this screen used
  // to assume. That model didn't exist anywhere in the backend (confirmed
  // live: PATCH .../status?status=ACCEPTED 422s, "ACCEPTED" isn't a valid
  // ReferralState member at all), so every tap here used to fail. Mapped
  // onto real, ALLOWED_TRANSITIONS-valid next states instead, each carrying
  // whatever TRANSITION_REQUIRED_FIELDS demands for that transition.
  static const Set<String> _cancellableStatuses = {
    'INITIATED',
    'SLOT_BOOKED',
    'TRANSPORT_ARRANGED',
    'ARRIVED',
    'RESCHEDULED',
  };

  List<Widget> _buildStatusActions(Map<String, dynamic> referral) {
    final referralId = (referral['id'] ?? '').toString().trim();
    final status = (referral['status'] ?? '').toString().toUpperCase();
    if (referralId.isEmpty) {
      return const [];
    }

    String? nextStatus;
    String? actionLabel;
    Map<String, dynamic>? Function()? buildBody;

    if (status == 'INITIATED') {
      nextStatus = 'SLOT_BOOKED';
      actionLabel = 'Accept';
      buildBody = () => {
        'slot_datetime': DateTime.now().toUtc().toIso8601String(),
        'destination_org_unit_id': referral['destination_facility_id'],
      };
    } else if (status == 'SLOT_BOOKED' && _currentUserId != null) {
      nextStatus = 'ARRIVED';
      actionLabel = 'Mark Arrived';
      buildBody = () => {'arrival_confirmed_by': _currentUserId};
    } else if (status == 'ARRIVED' && _currentUserId != null) {
      nextStatus = 'CONSULTED';
      actionLabel = 'Mark Consulted';
      buildBody = () => {'consulted_by_user_id': _currentUserId};
    } else if (status == 'CONSULTED') {
      nextStatus = 'CLOSED';
      actionLabel = 'Close';
      buildBody = () => null;
    }

    final isUpdating = _updatingReferralIds.contains(referralId);
    return [
      if (nextStatus != null)
        TextButton(
          onPressed: isUpdating
              ? null
              : () => _updateReferralStatus(
                  referralId: referralId,
                  status: nextStatus!,
                  data: buildBody!(),
                ),
          child: Text(actionLabel!),
        ),
      if (_cancellableStatuses.contains(status))
        TextButton(
          onPressed: isUpdating ? null : () => _cancelReferral(referralId),
          child: const Text('Cancel'),
        ),
    ];
  }

  Future<void> _cancelReferral(String referralId) async {
    final reason = await showDialog<String>(
      context: context,
      builder: (dialogContext) {
        final controller = TextEditingController();
        return AlertDialog(
          title: const Text('Cancel referral'),
          content: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Reason for cancellation',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('Back'),
            ),
            TextButton(
              onPressed: () =>
                  Navigator.of(dialogContext).pop(controller.text.trim()),
              child: const Text('Cancel referral'),
            ),
          ],
        );
      },
    );
    if (reason == null || reason.isEmpty) return;

    await _updateReferralStatus(
      referralId: referralId,
      status: 'CANCELLED',
      data: {'cancellation_reason': reason},
    );
  }

  Future<void> _updateReferralStatus({
    required String referralId,
    required String status,
    Map<String, dynamic>? data,
  }) async {
    if (_updatingReferralIds.contains(referralId)) return;
    setState(() {
      _updatingReferralIds.add(referralId);
    });

    try {
      await _apiService.updateReferralStatus(
        referralId: referralId,
        status: status,
        body: data,
      );
      await _loadBackendReferrals();
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Referral updated to $status.')));
    } on NetworkException catch (error) {
      _showStatusUpdateError(error.message);
    } on AuthenticationException catch (error) {
      _showStatusUpdateError(error.message);
    } catch (_) {
      _showStatusUpdateError(
        'Unable to update the referral. Please try again.',
      );
    } finally {
      if (mounted) {
        setState(() {
          _updatingReferralIds.remove(referralId);
        });
      }
    }
  }

  void _showStatusUpdateError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Referral status update failed: $message')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Facility Dashboard'),
        backgroundColor: Colors.blue.shade800,
        foregroundColor: Colors.white,
        bottom: const PreferredSize(
          preferredSize: Size.fromHeight(24),
          child: Padding(
            padding: EdgeInsets.only(bottom: 8.0),
            child: Text(
              'PHC Testville • Live Local Metrics',
              style: TextStyle(color: Colors.white70, fontSize: 14),
            ),
          ),
        ),
      ),
      body: ValueListenableBuilder(
        valueListenable: Hive.box<PatientLocal>('patients').listenable(),
        builder: (context, Box<PatientLocal> patientBox, _) {
          final totalPatients = patientBox.values.length;
          final unsyncedCount = patientBox.values
              .where((p) => !p.synced)
              .length;
          final syncedCount = patientBox.values.where((p) => p.synced).length;

          return Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: _buildMetricCard(
                        'Total Registered',
                        '$totalPatients',
                        Colors.blue.shade50,
                        Colors.blue.shade900,
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: _buildMetricCard(
                        'Pending Sync',
                        '$unsyncedCount',
                        Colors.orange.shade50,
                        Colors.orange.shade900,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: _buildMetricCard(
                        'Successfully Synced',
                        '$syncedCount',
                        Colors.green.shade50,
                        Colors.green.shade900,
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: _buildMetricCard(
                        'Breached SLAs',
                        '0',
                        Colors.red.shade50,
                        Colors.red.shade900,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 32),
                const Text(
                  'Active Exceptions',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: ValueListenableBuilder(
                    valueListenable: Hive.box<ReferralLocal>('referrals')
                        .listenable(),
                    builder: (context, Box<ReferralLocal> referralBox, _) {
                      if (_isLoadingReferrals) {
                        return const Center(child: CircularProgressIndicator());
                      }

                      final referralCards = _buildReferralCards(referralBox);

                      if (referralCards.isEmpty) {
                        return Center(
                          child: Text(
                            _referralLoadError == null
                                ? 'No active referral exceptions.'
                                : 'No backend referrals available. Showing saved records.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: Colors.grey.shade600,
                              fontSize: 15,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        );
                      }

                      return ListView(children: referralCards);
                    },
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildMetricCard(
    String label,
    String value,
    Color bgColor,
    Color textColor,
  ) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: textColor.withValues(alpha: 0.2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(color: textColor, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(
              color: textColor,
              fontSize: 28,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildExceptionRow(
    String id,
    String patientName,
    String destinationFacility,
    String urgency,
    String status,
    String reason, {
    String? sourceFacility,
    List<Widget> actions = const [],
  }) {
    final urgencyNormalized = urgency.toLowerCase();
    final isEmergency = urgencyNormalized == 'emergency';
    final iconColor = isEmergency ? Colors.red : Colors.orange;
    final icon = isEmergency
        ? Icons.warning_amber_rounded
        : Icons.priority_high_rounded;

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 0,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ListTile(
        leading: Icon(icon, color: iconColor, size: 28),
        title: Text(id, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 4),
            Text(patientName),
            const SizedBox(height: 2),
            if (sourceFacility != null && sourceFacility.isNotEmpty)
              Text(
                '$sourceFacility → $destinationFacility',
                style: const TextStyle(fontSize: 12),
              ),
            Text(
              '${urgency.toUpperCase()} • ${status.toUpperCase()}',
              style: const TextStyle(fontSize: 12),
            ),
            const SizedBox(height: 4),
            Text(reason, style: const TextStyle(fontSize: 12)),
            if (actions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Wrap(spacing: 4, children: actions),
              ),
          ],
        ),
      ),
    );
  }
}
