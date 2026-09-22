import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';

import '../api_service.dart';
import '../models/patient.dart';
import 'patient_summary_screen.dart';
import 'registration_screen.dart';

class PatientListScreen extends StatefulWidget {
  const PatientListScreen({super.key});

  @override
  State<PatientListScreen> createState() => _PatientListScreenState();
}

class _PatientListScreenState extends State<PatientListScreen> {
  String _searchQuery = '';
  String _selectedFilter = 'All';
  bool _isRefreshing = false;

  final List<String> _filters = ['All', 'Vaccinations', 'Prenatal', 'General'];

  @override
  void initState() {
    super.initState();
    _refreshPatientsFromServer();
  }

  Future<void> _refreshPatientsFromServer() async {
    if (_isRefreshing) {
      return;
    }

    setState(() {
      _isRefreshing = true;
    });

    try {
      final serverPatients = await ApiService().getPatients();
      final patientBox = Hive.box<PatientLocal>('patients');

      for (final item in serverPatients) {
        final rawUuid = (item['client_uuid'] ?? '').toString().trim();
        if (rawUuid.isEmpty) {
          continue;
        }

        final existing = patientBox.get(rawUuid);
        if (existing != null && !existing.synced) {
          continue;
        }

        final name = (item['name'] ?? '').toString();
        final ageValue = item['age'];
        final age = ageValue is int
            ? ageValue
            : int.tryParse(ageValue?.toString() ?? '') ?? 0;
        final village = (item['village'] ?? '').toString();
        final phone = (item['phone'] ?? '').toString();
        final facilityId = (item['facility_id'] ?? '').toString();
        final backendPatientId = (item['id'] ?? '').toString().trim();

        await patientBox.put(
          rawUuid,
          PatientLocal(
            clientUuid: rawUuid,
            name: name,
            age: age,
            village: village,
            synced: true,
            phone: phone,
            facilityId: facilityId,
            backendPatientId: backendPatientId.isEmpty
                ? existing?.backendPatientId
                : backendPatientId,
          ),
        );
      }
    } on NetworkException {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Unable to refresh records. Showing saved records.'),
          duration: Duration(seconds: 2),
        ),
      );
    } on AuthenticationException {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Unable to refresh records. Showing saved records.'),
          duration: Duration(seconds: 2),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Unable to refresh records. Showing saved records.'),
          duration: Duration(seconds: 2),
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isRefreshing = false;
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
        centerTitle: false,
        titleSpacing: 20,
        title: Row(
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                color: const Color(0xFFE8F4F5),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(
                Icons.local_hospital_outlined,
                color: Color(0xFF075965),
                size: 21,
              ),
            ),
            const SizedBox(width: 10),
            const Expanded(
              child: Text(
                'Public Health\nRegistry',
                style: TextStyle(
                  fontSize: 18,
                  height: 1.05,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF12343B),
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(
                color: const Color(0xFFC8102E),
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Text(
                'EMERGENCY',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.3,
                ),
              ),
            ),
          ],
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: const Color(0xFFD9E0E2)),
        ),
      ),
      body: SafeArea(
        child: ValueListenableBuilder<Box<PatientLocal>>(
          valueListenable: Hive.box<PatientLocal>('patients').listenable(),
          builder: (context, box, _) {
            final allPatients = box.values.toList();

            final filteredPatients = allPatients.where((patient) {
              final query = _searchQuery.trim().toLowerCase();

              if (query.isEmpty) {
                return true;
              }

              final nameMatches = patient.name.toLowerCase().contains(query);

              final villageMatches = patient.village.toLowerCase().contains(
                query,
              );

              final idMatches = patient.clientUuid.toLowerCase().contains(
                query,
              );

              return nameMatches || villageMatches || idMatches;
            }).toList();

            return LayoutBuilder(
              builder: (context, constraints) {
                final contentWidth = constraints.maxWidth > 650
                    ? 620.0
                    : constraints.maxWidth;

                return Center(
                  child: SizedBox(
                    width: contentWidth,
                    child: Column(
                      children: [
                        Expanded(
                          child: ListView(
                            padding: const EdgeInsets.fromLTRB(16, 14, 16, 100),
                            children: [
                              _buildSearchField(),
                              const SizedBox(height: 12),
                              _buildFilterRow(),
                              const SizedBox(height: 12),
                              if (_isRefreshing)
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 8,
                                  ),
                                  child: const Row(
                                    children: [
                                      SizedBox(
                                        width: 14,
                                        height: 14,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                          color: Color(0xFF075965),
                                        ),
                                      ),
                                      SizedBox(width: 10),
                                      Text(
                                        'Refreshing records...',
                                        style: TextStyle(
                                          fontSize: 12,
                                          color: Color(0xFF4C5A5F),
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              const SizedBox(height: 8),
                              _buildSectionHeader(filteredPatients.length),
                              const SizedBox(height: 8),
                              if (allPatients.isEmpty)
                                _buildEmptyState()
                              else if (filteredPatients.isEmpty)
                                _buildNoResultsState()
                              else
                                ...filteredPatients.map(_buildPatientCard),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
      floatingActionButton: Hive.box<PatientLocal>('patients').isNotEmpty
          ? FloatingActionButton.extended(
              backgroundColor: const Color(0xFF075965),
              foregroundColor: Colors.white,
              elevation: 2,
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const RegistrationScreen()),
                );
              },
              icon: const Icon(Icons.person_add_alt_1),
              label: const Text(
                'Add Citizen',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
            )
          : null,
    );
  }

  Widget _buildSearchField() {
    return TextField(
      onChanged: (value) {
        setState(() {
          _searchQuery = value;
        });
      },
      decoration: InputDecoration(
        hintText: 'Search by name or ID',
        hintStyle: const TextStyle(color: Color(0xFF9AA5A8), fontSize: 14),
        prefixIcon: const Icon(
          Icons.search,
          color: Color(0xFF667276),
          size: 21,
        ),
        suffixIcon: _searchQuery.isNotEmpty
            ? IconButton(
                tooltip: 'Clear search',
                icon: const Icon(Icons.close, size: 19),
                onPressed: () {
                  setState(() {
                    _searchQuery = '';
                  });
                },
              )
            : null,
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(7),
          borderSide: const BorderSide(color: Color(0xFFD5DDDF)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(7),
          borderSide: const BorderSide(color: Color(0xFFD5DDDF)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(7),
          borderSide: const BorderSide(color: Color(0xFF075965), width: 1.5),
        ),
      ),
    );
  }

  Widget _buildFilterRow() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: _filters.map((filter) {
          final selected = _selectedFilter == filter;

          return Padding(
            padding: const EdgeInsets.only(right: 7),
            child: ChoiceChip(
              label: Text(filter),
              selected: selected,
              onSelected: (_) {
                setState(() {
                  _selectedFilter = filter;
                });
              },
              labelStyle: TextStyle(
                fontSize: 12,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                color: selected ? Colors.white : const Color(0xFF445256),
              ),
              selectedColor: const Color(0xFF075965),
              backgroundColor: Colors.white,
              side: BorderSide(
                color: selected
                    ? const Color(0xFF075965)
                    : const Color(0xFFD5DDDF),
              ),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(18),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 2),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildSectionHeader(int count) {
    return Row(
      children: [
        Text(
          'CITIZEN RECORDS',
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.7,
            color: Colors.grey.shade700,
          ),
        ),
        const SizedBox(width: 6),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
          decoration: BoxDecoration(
            color: const Color(0xFFE7ECEE),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            '$count',
            style: const TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: Color(0xFF445256),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildPatientCard(PatientLocal patient) {
    final initial = patient.name.trim().isEmpty
        ? '?'
        : patient.name.trim()[0].toUpperCase();

    final shortId = patient.clientUuid.length > 13
        ? patient.clientUuid.substring(patient.clientUuid.length - 13)
        : patient.clientUuid;

    return Card(
      margin: const EdgeInsets.only(bottom: 9),
      elevation: 0,
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: const BorderSide(color: Color(0xFFD9E0E2)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => PatientSummaryScreen(patient: patient),
            ),
          );
        },
        child: Padding(
          padding: const EdgeInsets.all(13),
          child: Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: const Color(0xFFE3EEF0),
                child: Text(
                  initial,
                  style: const TextStyle(
                    color: Color(0xFF075965),
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      patient.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFF172124),
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'ID: $shortId',
                      style: const TextStyle(
                        fontSize: 11,
                        color: Color(0xFF697579),
                      ),
                    ),
                    const SizedBox(height: 7),
                    Row(
                      children: [
                        _buildSyncBadge(patient.synced),
                        const SizedBox(width: 7),
                        Flexible(
                          child: Text(
                            patient.village,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 11,
                              color: Color(0xFF697579),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Color(0xFF9AA5A8)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSyncBadge(bool synced) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: synced ? const Color(0xFFE5F3EA) : const Color(0xFFFFF0DC),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            synced ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
            size: 12,
            color: synced ? const Color(0xFF267A45) : const Color(0xFFB96A00),
          ),
          const SizedBox(width: 3),
          Text(
            synced ? 'Synced' : 'Pending',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              color: synced ? const Color(0xFF267A45) : const Color(0xFFB96A00),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Container(
      margin: const EdgeInsets.only(top: 70),
      padding: const EdgeInsets.all(28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFD9E0E2)),
      ),
      child: Column(
        children: [
          const Icon(
            Icons.folder_open_outlined,
            size: 52,
            color: Color(0xFF8E9A9E),
          ),
          const SizedBox(height: 16),
          const Text(
            'No citizens found',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Color(0xFF172124),
            ),
          ),
          const SizedBox(height: 7),
          const Text(
            'Start by adding a new record to the registry.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: Color(0xFF778286)),
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFF075965),
                padding: const EdgeInsets.symmetric(vertical: 13),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(6),
                ),
              ),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const RegistrationScreen()),
                );
              },
              icon: const Icon(Icons.person_add_alt_1, size: 18),
              label: const Text('Add Citizen'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNoResultsState() {
    return Container(
      margin: const EdgeInsets.only(top: 50),
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          const Icon(Icons.search_off, size: 46, color: Color(0xFF9AA5A8)),
          const SizedBox(height: 14),
          const Text(
            'No matching citizens',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          const Text(
            'Try searching with another name or ID.',
            style: TextStyle(color: Color(0xFF7A8588), fontSize: 12),
          ),
        ],
      ),
    );
  }
}
