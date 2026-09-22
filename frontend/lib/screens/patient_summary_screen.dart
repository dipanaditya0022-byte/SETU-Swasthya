import 'package:flutter/material.dart';

import '../models/patient.dart';
import 'triage_form_screen.dart';

class PatientSummaryScreen extends StatelessWidget {
  final PatientLocal patient;

  const PatientSummaryScreen({super.key, required this.patient});

  @override
  Widget build(BuildContext context) {
    final Color teal = Colors.teal.shade800;

    return Scaffold(
      backgroundColor: const Color(0xFFF7F9FA),
      appBar: AppBar(
        backgroundColor: Colors.white,
        foregroundColor: Colors.black87,
        elevation: 0,
        title: const Text(
          'Citizen Record',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          Container(
            margin: const EdgeInsets.only(right: 12),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
            decoration: BoxDecoration(
              color: Colors.red.shade700,
              borderRadius: BorderRadius.circular(20),
            ),
            child: const Center(
              child: Text(
                'EMERGENCY',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ----------------------------------------------------------
          // PROFILE HEADER
          // ----------------------------------------------------------
          _buildProfileCard(teal),

          const SizedBox(height: 16),

          // ----------------------------------------------------------
          // CURRENT HEALTH DATA
          // ----------------------------------------------------------
          _buildHealthDataCard(teal),

          const SizedBox(height: 16),

          // ----------------------------------------------------------
          // RECENT ENCOUNTERS
          // ----------------------------------------------------------
          _buildRecentEncountersCard(teal),

          const SizedBox(height: 20),

          // ----------------------------------------------------------
          // UPDATE VITALS
          // ----------------------------------------------------------
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton.icon(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => TriageFormScreen(patient: patient),
                  ),
                );
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: teal,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              icon: const Icon(Icons.add_circle_outline),
              label: const Text(
                'Update Vitals',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
              ),
            ),
          ),

          const SizedBox(height: 24),
        ],
      ),
    );
  }

  // ================================================================
  // PROFILE CARD
  // ================================================================

  Widget _buildProfileCard(Color teal) {
    final String initial = patient.name.isNotEmpty
        ? patient.name[0].toUpperCase()
        : '?';

    return Card(
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: Color(0xFFD9E0E3)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 30,
                  backgroundColor: const Color(0xFFE7EFF1),
                  child: Text(
                    initial,
                    style: TextStyle(
                      color: teal,
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),

                const SizedBox(width: 14),

                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        patient.name,
                        style: const TextStyle(
                          fontSize: 19,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          const Icon(
                            Icons.person_outline,
                            size: 15,
                            color: Colors.grey,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            'Age: ${patient.age}',
                            style: const TextStyle(color: Colors.black54),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          const Icon(
                            Icons.location_on_outlined,
                            size: 15,
                            color: Colors.grey,
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Text(
                              patient.village,
                              style: const TextStyle(color: Colors.black54),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),

                const Icon(Icons.qr_code_2, color: Colors.grey),
              ],
            ),

            const SizedBox(height: 14),

            const Divider(height: 1),

            const SizedBox(height: 12),

            Row(
              children: [
                const Text(
                  'Patient ID',
                  style: TextStyle(color: Colors.grey, fontSize: 13),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    patient.clientUuid,
                    style: const TextStyle(
                      fontSize: 13,
                      fontFamily: 'monospace',
                    ),
                  ),
                ),
              ],
            ),

            const SizedBox(height: 10),

            Row(
              children: [
                const Text(
                  'Sync Status',
                  style: TextStyle(color: Colors.grey, fontSize: 13),
                ),
                const SizedBox(width: 8),
                Icon(
                  patient.synced ? Icons.cloud_done : Icons.cloud_off,
                  size: 17,
                  color: patient.synced
                      ? Colors.green.shade700
                      : Colors.orange.shade700,
                ),
                const SizedBox(width: 4),
                Text(
                  patient.synced ? 'Synced' : 'Pending Local Sync',
                  style: TextStyle(
                    color: patient.synced
                        ? Colors.green.shade700
                        : Colors.orange.shade700,
                    fontWeight: FontWeight.w500,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // ================================================================
  // HEALTH DATA CARD
  // ================================================================

  Widget _buildHealthDataCard(Color teal) {
    return Card(
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: Color(0xFFD9E0E3)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Row(
              children: [
                Icon(Icons.monitor_heart_outlined, color: teal),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Current Health Data',
                    style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                  ),
                ),
              ],
            ),

            const SizedBox(height: 18),

            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFA),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFE1E6E8)),
              ),
              child: Column(
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: Colors.grey.shade100,
                    ),
                    child: Icon(
                      Icons.monitor_heart_outlined,
                      size: 34,
                      color: Colors.grey.shade400,
                    ),
                  ),

                  const SizedBox(height: 16),

                  const Text(
                    'No health data available yet',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  ),

                  const SizedBox(height: 8),

                  const Text(
                    'Record vitals to start tracking.\n'
                    'Consistent monitoring helps maintain a '
                    'comprehensive health profile.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey, height: 1.4),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ================================================================
  // RECENT ENCOUNTERS
  // ================================================================

  Widget _buildRecentEncountersCard(Color teal) {
    return Card(
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: Color(0xFFD9E0E3)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.history, color: teal),
                const SizedBox(width: 8),
                const Text(
                  'Recent Encounters',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                ),
              ],
            ),

            const SizedBox(height: 18),

            Center(
              child: Column(
                children: [
                  Icon(
                    Icons.event_note_outlined,
                    size: 42,
                    color: Colors.grey.shade400,
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'No recent encounters',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 5),
                  const Text(
                    'Clinical encounters will appear here.',
                    style: TextStyle(color: Colors.grey),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
