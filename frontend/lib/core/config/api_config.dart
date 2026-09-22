import 'package:flutter/foundation.dart';

class ApiConfig {
  const ApiConfig._();

  static String get baseUrl {
    const configuredBaseUrl = String.fromEnvironment('API_BASE_URL');
    if (configuredBaseUrl.isNotEmpty) return configuredBaseUrl;

    if (kIsWeb) {
      return 'http://localhost:8002';
    }

    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8002';
    }

    return 'http://localhost:8002';
  }
}
