import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/storage/local_database.dart';
import '../services/connectivity_service.dart';
import '../services/sync_remote_data_source.dart';
import '../services/sync_service.dart';
import 'api_providers.dart';

final localDatabaseProvider = Provider<LocalDatabase>((ref) {
  final database = LocalDatabase.current;
  if (database == null) {
    throw StateError('Local database has not been initialized.');
  }
  return database;
});

final connectivityGatewayProvider = Provider<ConnectivityGateway>(
  (ref) => PluginConnectivityGateway(),
);

final connectivityStateProvider = StreamProvider<bool>((ref) async* {
  final gateway = ref.watch(connectivityGatewayProvider);
  yield await gateway.isOnline;
  yield* gateway.onOnlineChanged;
});

final syncRemoteDataSourceProvider = Provider<SyncRemoteDataSource>(
  (ref) => DioSyncRemoteDataSource(ref.watch(apiClientProvider).dio),
);

final syncServiceProvider = Provider<SyncService>((ref) {
  final service = SyncService(
    database: ref.watch(localDatabaseProvider),
    remoteDataSource: ref.watch(syncRemoteDataSourceProvider),
    connectivity: ref.watch(connectivityGatewayProvider),
  );
  ref.onDispose(service.dispose);
  return service;
});

enum SyncStatus { idle, syncing, success, error }

class SyncState {
  const SyncState({
    this.status = SyncStatus.idle,
    this.pendingCount = 0,
    this.online,
    this.message,
    this.lastSynchronizedAt,
  });

  final SyncStatus status;
  final int pendingCount;
  final bool? online;
  final String? message;
  final DateTime? lastSynchronizedAt;

  bool get isSyncing => status == SyncStatus.syncing;
}

final syncControllerProvider = NotifierProvider<SyncController, SyncState>(
  SyncController.new,
);

class SyncController extends Notifier<SyncState> {
  @override
  SyncState build() {
    if (LocalDatabase.current == null) return const SyncState();
    final service = ref.read(syncServiceProvider);
    service.onConnectivityRestored = syncNow;
    service.startConnectivityMonitoring();
    return SyncState(pendingCount: service.pendingCount);
  }

  Future<void> syncNow() async {
    if (LocalDatabase.current == null || state.isSyncing) return;
    final service = ref.read(syncServiceProvider);
    state = SyncState(
      status: SyncStatus.syncing,
      pendingCount: service.pendingCount,
      lastSynchronizedAt: state.lastSynchronizedAt,
    );
    final result = await service.syncPending();
    state = SyncState(
      status: result.message == null ? SyncStatus.success : SyncStatus.error,
      pendingCount: service.pendingCount,
      message: result.message,
      lastSynchronizedAt: result.message == null
          ? DateTime.now()
          : state.lastSynchronizedAt,
    );
  }
}
