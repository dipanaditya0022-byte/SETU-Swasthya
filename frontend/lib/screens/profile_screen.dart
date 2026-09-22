import 'package:flutter/material.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF12343B),
        title: const Text(
          'Profile',
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
            final width =
                constraints.maxWidth > 650 ? 620.0 : constraints.maxWidth;

            return Center(
              child: SizedBox(
                width: width,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(
                    16,
                    18,
                    16,
                    32,
                  ),
                  children: [
                    _buildProfileHeader(),
                    const SizedBox(height: 16),
                    _buildPersonalInformation(),
                    const SizedBox(height: 16),
                    _buildFacilityInformation(),
                    const SizedBox(height: 16),
                    _buildAccessInformation(),
                    const SizedBox(height: 20),
                    _buildSettingsSection(context),
                    const SizedBox(height: 20),
                    _buildLogoutButton(context),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildProfileHeader() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: const Color(0xFFD9E0E2),
        ),
      ),
      child: Column(
        children: [
          Container(
            width: 82,
            height: 82,
            decoration: const BoxDecoration(
              color: Color(0xFFE5F1F2),
              shape: BoxShape.circle,
            ),
            child: const Center(
              child: Text(
                'F',
                style: TextStyle(
                  color: Color(0xFF075965),
                  fontSize: 34,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          const Text(
            'Faeza',
            style: TextStyle(
              fontSize: 21,
              fontWeight: FontWeight.w800,
              color: Color(0xFF172124),
            ),
          ),
          const SizedBox(height: 5),
          const Text(
            'Frontline Health Worker',
            style: TextStyle(
              fontSize: 13,
              color: Color(0xFF687477),
            ),
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 6,
            ),
            decoration: BoxDecoration(
              color: const Color(0xFFEAF7EF),
              borderRadius: BorderRadius.circular(20),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.verified_user_outlined,
                  size: 15,
                  color: Color(0xFF21643D),
                ),
                SizedBox(width: 5),
                Text(
                  'Authenticated Staff',
                  style: TextStyle(
                    color: Color(0xFF21643D),
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPersonalInformation() {
    return _sectionCard(
      title: 'Personal Information',
      icon: Icons.person_outline,
      children: [
        _infoRow(
          'Name',
          'Faeza',
          Icons.badge_outlined,
        ),
        const Divider(height: 24),
        _infoRow(
          'Mobile',
          'Not connected',
          Icons.phone_outlined,
        ),
        const Divider(height: 24),
        _infoRow(
          'Email',
          'Not connected',
          Icons.email_outlined,
        ),
      ],
    );
  }

  Widget _buildFacilityInformation() {
    return _sectionCard(
      title: 'Facility Information',
      icon: Icons.local_hospital_outlined,
      children: [
        _infoRow(
          'Facility',
          'PHC Testville',
          Icons.business_outlined,
        ),
        const Divider(height: 24),
        _infoRow(
          'Facility Type',
          'Primary Health Centre',
          Icons.medical_services_outlined,
        ),
        const Divider(height: 24),
        _infoRow(
          'Location',
          'Testville',
          Icons.location_on_outlined,
        ),
      ],
    );
  }

  Widget _buildAccessInformation() {
    return _sectionCard(
      title: 'Access & Role',
      icon: Icons.admin_panel_settings_outlined,
      children: [
        _infoRow(
          'Role',
          'Frontline Health Worker',
          Icons.person_pin_outlined,
        ),
        const Divider(height: 24),
        _infoRow(
          'Access Level',
          'Facility Operations',
          Icons.lock_outline,
        ),
        const Divider(height: 24),
        _infoRow(
          'Account Status',
          'Active',
          Icons.check_circle_outline,
          valueColor: Color(0xFF21643D),
        ),
      ],
    );
  }

  Widget _buildSettingsSection(BuildContext context) {
    return _sectionCard(
      title: 'Application',
      icon: Icons.settings_outlined,
      children: [
        _actionRow(
          icon: Icons.language_outlined,
          title: 'Language',
          subtitle: 'English',
          onTap: () {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'Language selection will be added later.',
                ),
              ),
            );
          },
        ),
        const Divider(height: 24),
        _actionRow(
          icon: Icons.sync_outlined,
          title: 'Synchronisation',
          subtitle: 'Manage offline data sync',
          onTap: () {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'Sync settings will be connected later.',
                ),
              ),
            );
          },
        ),
        const Divider(height: 24),
        _actionRow(
          icon: Icons.info_outline,
          title: 'About SETU-Swasthya',
          subtitle: 'Application information',
          onTap: () {
            showAboutDialog(
              context: context,
              applicationName: 'SETU-Swasthya',
              applicationVersion: '1.0.0',
              applicationLegalese:
                  'Care-access and quality support platform.',
            );
          },
        ),
      ],
    );
  }

  Widget _buildLogoutButton(BuildContext context) {
    return SizedBox(
      height: 50,
      child: OutlinedButton.icon(
        onPressed: () {
          _showLogoutDialog(context);
        },
        style: OutlinedButton.styleFrom(
          foregroundColor: const Color(0xFFC62828),
          side: const BorderSide(
            color: Color(0xFFE0A3A3),
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(7),
          ),
        ),
        icon: const Icon(Icons.logout),
        label: const Text(
          'Sign Out',
          style: TextStyle(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }

  void _showLogoutDialog(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('Sign Out'),
          content: const Text(
            'Are you sure you want to sign out of SETU-Swasthya?',
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.pop(dialogContext);
              },
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                Navigator.pop(dialogContext);

                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text(
                      'Sign-out will be connected to authentication later.',
                    ),
                  ),
                );
              },
              child: const Text('Sign Out'),
            ),
          ],
        );
      },
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
        border: Border.all(
          color: const Color(0xFFD9E0E2),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                icon,
                color: const Color(0xFF075965),
                size: 21,
              ),
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

  Widget _infoRow(
    String label,
    String value,
    IconData icon, {
    Color valueColor = const Color(0xFF172124),
  }) {
    return Row(
      children: [
        Icon(
          icon,
          color: const Color(0xFF697579),
          size: 20,
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              color: Color(0xFF687477),
            ),
          ),
        ),
        Flexible(
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: valueColor,
            ),
          ),
        ),
      ],
    );
  }

  Widget _actionRow({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: Row(
        children: [
          Icon(
            icon,
            color: const Color(0xFF075965),
            size: 21,
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 11,
                    color: Color(0xFF778286),
                  ),
                ),
              ],
            ),
          ),
          const Icon(
            Icons.chevron_right,
            color: Color(0xFF879194),
          ),
        ],
      ),
    );
  }
}