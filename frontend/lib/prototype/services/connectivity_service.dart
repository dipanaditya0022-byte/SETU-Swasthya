import 'package:connectivity_plus/connectivity_plus.dart';

abstract interface class ConnectivityGateway {
  Stream<bool> get onOnlineChanged;
  Future<bool> get isOnline;
}

class PluginConnectivityGateway implements ConnectivityGateway {
  PluginConnectivityGateway([Connectivity? connectivity])
    : _connectivity = connectivity ?? Connectivity();

  final Connectivity _connectivity;

  @override
  Stream<bool> get onOnlineChanged => _connectivity.onConnectivityChanged.map(
    (results) => results.any((result) => result != ConnectivityResult.none),
  );

  @override
  Future<bool> get isOnline async {
    final results = await _connectivity.checkConnectivity();
    return results.any((result) => result != ConnectivityResult.none);
  }
}
