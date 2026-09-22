class DashboardResponse {
  const DashboardResponse(this.raw);

  final Map<String, dynamic> raw;

  factory DashboardResponse.fromJson(Map<String, dynamic> json) =>
      DashboardResponse(Map<String, dynamic>.unmodifiable(json));
}

class DashboardConfiguration {
  const DashboardConfiguration({required this.orgUnitId});

  final String orgUnitId;

  bool get isConfigured => orgUnitId.isNotEmpty;
}

String dashboardDateValue(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';
