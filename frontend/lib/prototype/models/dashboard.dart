class DashboardResponse {
  const DashboardResponse(this.raw);

  final Map<String, dynamic> raw;

  factory DashboardResponse.fromJson(Map<String, dynamic> json) =>
      DashboardResponse(Map<String, dynamic>.unmodifiable(json));

  Map<String, dynamic> get _facility => _map(raw['facility']);
  Map<String, dynamic> get _metrics => _map(raw['metrics']);

  String get facilityName => _string(_facility['name']) ?? 'Facility';
  String? get facilityId => _string(_facility['id']);
  String? get facilityType => _string(_facility['type']);
  DateTime? get generatedAt => _dateTime(raw['generated_at']);
  DateTime? get date => _dateTime(raw['date']);

  int get openReferrals => _count(_metrics['open_referrals']) ?? 0;
  int get triageCompleted => _count(_metrics['triage_today']) ?? 0;
  int get breachedReferrals => _numerator(_metrics['breached']) ?? 0;
  int get syncedRecords => _numerator(_metrics['synced_today']) ?? 0;
  int get recordsCreatedToday => _denominator(_metrics['synced_today']) ?? 0;
  double get syncRate => _number(_map(_metrics['synced_today'])['rate_pct']);

  // The current facility-dashboard route does not return these fields.
  // Keep them nullable so the UI shows unavailable data instead of inventing
  // live figures from demo constants or unrelated local storage.
  int? get registeredPatients => _count(_metrics['registered_patients']);
  int? get arrivedReferrals => _count(_metrics['arrived_referrals']);

  bool get hasRecords =>
      openReferrals > 0 ||
      triageCompleted > 0 ||
      breachedReferrals > 0 ||
      recordsCreatedToday > 0;

  static Map<String, dynamic> _map(Object? value) => value is Map
      ? Map<String, dynamic>.from(value)
      : const <String, dynamic>{};

  static int? _count(Object? value) {
    final map = _map(value);
    final count = map['count'];
    return count is num ? count.toInt() : null;
  }

  static int? _numerator(Object? value) {
    final numerator = _map(value)['numerator'];
    return numerator is num ? numerator.toInt() : null;
  }

  static int? _denominator(Object? value) {
    final denominator = _map(value)['denominator'];
    return denominator is num ? denominator.toInt() : null;
  }

  static double _number(Object? value) => value is num ? value.toDouble() : 0;

  static String? _string(Object? value) {
    if (value is! String || value.trim().isEmpty) return null;
    return value;
  }

  static DateTime? _dateTime(Object? value) {
    if (value is! String) return null;
    return DateTime.tryParse(value);
  }
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
