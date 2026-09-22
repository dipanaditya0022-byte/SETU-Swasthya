import 'dart:async';

import 'package:uuid/uuid.dart';

import '../core/network/api_exception.dart';
import '../core/storage/local_database.dart';
import '../core/storage/sync_operation.dart';
import 'connectivity_service.dart';
import 'sync_remote_data_source.dart';

class SyncRunResult {
  const SyncRunResult({
    required this.attempted,
    required this.synced,
    this.message,
  });

  final int attempted;
  final int synced;
  final String? message;
}

class SyncService {
  SyncService({
    required this.database,
    required this.remoteDataSource,
    required this.connectivity,
  });

  final LocalDatabase database;
  final SyncRemoteDataSource remoteDataSource;
  final ConnectivityGateway connectivity;
  final _uuid = const Uuid();
  bool _running = false;
  StreamSubscription<bool>? _connectivitySubscription;
  Future<void> Function()? onConnectivityRestored;

  bool get isRunning => _running;

  int get pendingCount => database.queue
      .where(
        (operation) =>
            operation.status == SyncOperationStatus.pending ||
            operation.status == SyncOperationStatus.failed,
      )
      .length;

  Future<String> enqueue({
    required SyncOperationType type,
    required Map<String, dynamic> payload,
  }) async {
    final id = _uuid.v4();
    await database.saveOperation(
      SyncOperation(
        id: id,
        type: type,
        payload: payload,
        status: SyncOperationStatus.pending,
        createdAt: DateTime.now().toUtc(),
      ),
    );
    return id;
  }

  void startConnectivityMonitoring() {
    _connectivitySubscription ??= connectivity.onOnlineChanged.listen((online) {
      if (online) onConnectivityRestored?.call();
    });
  }

  Future<SyncRunResult> syncPending() async {
    if (_running) {
      return const SyncRunResult(
        attempted: 0,
        synced: 0,
        message: 'Sync already running.',
      );
    }
    final operations = database.queue
        .where(
          (operation) =>
              operation.status == SyncOperationStatus.pending ||
              operation.status == SyncOperationStatus.failed,
        )
        .toList();
    if (operations.isEmpty) return const SyncRunResult(attempted: 0, synced: 0);

    _running = true;
    for (final operation in operations) {
      await database.saveOperation(
        operation.copyWith(
          status: SyncOperationStatus.syncing,
          attempts: operation.attempts + 1,
          clearError: true,
        ),
      );
    }
    try {
      final result = await remoteDataSource.sync(operations);
      if (!result.acknowledged) {
        const message =
            'Sync response was not acknowledged by the documented contract.';
        for (final operation in operations) {
          await database.saveOperation(
            operation.copyWith(
              status: SyncOperationStatus.failed,
              attempts: operation.attempts + 1,
              lastError: message,
            ),
          );
        }
        return const SyncRunResult(attempted: 0, synced: 0, message: message);
      }
      for (final operation in operations) {
        await database.saveOperation(
          operation.copyWith(status: SyncOperationStatus.synced),
        );
      }
      return SyncRunResult(
        attempted: operations.length,
        synced: operations.length,
      );
    } on ApiException catch (error) {
      for (final operation in operations) {
        await database.saveOperation(
          operation.copyWith(
            status: SyncOperationStatus.failed,
            attempts: operation.attempts + 1,
            lastError: error.toString(),
          ),
        );
      }
      return SyncRunResult(
        attempted: operations.length,
        synced: 0,
        message: error.toString(),
      );
    } finally {
      _running = false;
    }
  }

  Future<void> dispose() async => _connectivitySubscription?.cancel();
}
