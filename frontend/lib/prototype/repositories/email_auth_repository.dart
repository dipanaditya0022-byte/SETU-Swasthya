import '../core/network/api_exception.dart';
import '../models/auth_requests.dart';
import '../services/email_auth_remote_data_source.dart';

abstract interface class EmailAuthRepository {
  Future<void> sendOtp(String email);
  Future<String> verifyOtp(String email, String otp);
}

class EmailAuthRepositoryImpl implements EmailAuthRepository {
  const EmailAuthRepositoryImpl(this._source);
  final EmailAuthRemoteDataSource _source;

  @override
  Future<void> sendOtp(String email) => _source.sendOtp(EmailOtpRequest(email));

  @override
  Future<String> verifyOtp(String email, String otp) async {
    final response = await _source.verifyOtp(EmailOtpVerifyRequest(email, otp));
    final token = response['access_token'];
    if (token is! String || token.isEmpty) {
      throw const UnexpectedApiException(
        message: 'OTP verification did not return an access token.',
      );
    }
    return token;
  }
}
