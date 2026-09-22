import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api_service.dart';
import '../core/network/api_client.dart';
import '../core/storage/local_database.dart';
import '../repositories/patient_repository.dart';
import '../services/patient_remote_data_source.dart';
import 'sync_providers.dart';

final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(dio: ApiService.instance.dio),
);

final patientRemoteDataSourceProvider = Provider<PatientRemoteDataSource>(
  (ref) => DioPatientRemoteDataSource(ref.watch(apiClientProvider).dio),
);

final patientRepositoryProvider = Provider<PatientRepository>(
  (ref) => PatientRepositoryImpl(
    ref.watch(patientRemoteDataSourceProvider),
    localDatabase: LocalDatabase.current,
    syncService: LocalDatabase.current == null
        ? null
        : ref.watch(syncServiceProvider),
  ),
);
