class CurrentUser {
  final String id;
  final String role;
  final List<String> permissions;
  final String? orgUnitId;
  final String? scopePath;
  final String fullName;
  final String mobileMasked;

  const CurrentUser({
    required this.id,
    required this.role,
    required this.permissions,
    required this.orgUnitId,
    required this.scopePath,
    required this.fullName,
    required this.mobileMasked,
  });

  factory CurrentUser.fromJson(Map<String, dynamic> json) {
    final scope = json['scope'];
    final scopeMap = scope is Map
        ? Map<String, dynamic>.from(scope)
        : <String, dynamic>{};
    final permissions = json['permissions'];

    return CurrentUser(
      id: (json['id'] ?? '').toString(),
      role: (json['role'] ?? '').toString(),
      permissions: permissions is List
          ? permissions
                .map((item) => item?.toString() ?? '')
                .where((item) => item.isNotEmpty)
                .toList(growable: false)
          : const [],
      orgUnitId:
          (scopeMap['org_unit_id'] ?? scopeMap['orgUnitId'] ?? '')
              .toString()
              .isEmpty
          ? null
          : (scopeMap['org_unit_id'] ?? scopeMap['orgUnitId']).toString(),
      scopePath:
          (scopeMap['scope_path'] ?? scopeMap['scopePath'] ?? '')
              .toString()
              .isEmpty
          ? null
          : (scopeMap['scope_path'] ?? scopeMap['scopePath']).toString(),
      fullName: (json['full_name'] ?? '').toString(),
      mobileMasked: (json['mobile_masked'] ?? '').toString(),
    );
  }

  bool hasPermission(String permission) {
    return permissions.contains(permission);
  }
}
