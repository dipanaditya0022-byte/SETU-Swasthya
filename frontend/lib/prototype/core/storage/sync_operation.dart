enum SyncOperationType { patientRegistration, referralCreation }

enum SyncOperationStatus { pending, syncing, synced, failed }

class SyncOperation {
  const SyncOperation({
    required this.id,
    required this.type,
    required this.payload,
    required this.status,
    required this.createdAt,
    this.attempts = 0,
    this.lastError,
  });

  final String id;
  final SyncOperationType type;
  final Map<String, dynamic> payload;
  final SyncOperationStatus status;
  final DateTime createdAt;
  final int attempts;
  final String? lastError;

  SyncOperation copyWith({
    SyncOperationStatus? status,
    int? attempts,
    String? lastError,
    bool clearError = false,
  }) => SyncOperation(
    id: id,
    type: type,
    payload: payload,
    status: status ?? this.status,
    createdAt: createdAt,
    attempts: attempts ?? this.attempts,
    lastError: clearError ? null : lastError ?? this.lastError,
  );

  Map<String, dynamic> toMap() => {
    'id': id,
    'type': type.name,
    'payload': payload,
    'status': status.name,
    'created_at': createdAt.toIso8601String(),
    'attempts': attempts,
    'last_error': lastError,
  };

  factory SyncOperation.fromMap(Map<dynamic, dynamic> map) => SyncOperation(
    id: map['id'] as String,
    type: SyncOperationType.values.byName(map['type'] as String),
    payload: Map<String, dynamic>.from(map['payload'] as Map),
    status: SyncOperationStatus.values.byName(map['status'] as String),
    createdAt: DateTime.parse(map['created_at'] as String),
    attempts: map['attempts'] as int? ?? 0,
    lastError: map['last_error'] as String?,
  );
}
