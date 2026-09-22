class AuthSession {
  final String accessToken;
  final String? refreshToken;
  final String tokenType;
  final int expiresIn;

  const AuthSession({
    required this.accessToken,
    this.refreshToken,
    required this.tokenType,
    required this.expiresIn,
  });

  factory AuthSession.fromJson(Map<String, dynamic> json) {
    final accessToken = json['access_token'];
    final refreshToken = json['refresh_token'];

    return AuthSession(
      accessToken: accessToken is String ? accessToken : accessToken.toString(),
      refreshToken: refreshToken is String ? refreshToken : null,
      tokenType: json['token_type'] is String
          ? json['token_type'] as String
          : 'bearer',
      expiresIn: json['expires_in'] is int
          ? json['expires_in'] as int
          : (json['expires_in'] is num ? (json['expires_in'] as num).toInt() : 0),
    );
  }
}