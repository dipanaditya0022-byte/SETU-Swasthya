enum OtpPurpose { patientRegistration, login, inviteAccept, passwordReset }

class EmailOtpRequest {
  const EmailOtpRequest(this.email);
  final String email;
  Map<String, dynamic> toJson() => {'email': email};
}

class EmailOtpVerifyRequest {
  const EmailOtpVerifyRequest(this.email, this.otp);
  final String email;
  final String otp;
  Map<String, dynamic> toJson() => {'email': email, 'otp': otp};
}

String _purposeValue(OtpPurpose value) => switch (value) {
  OtpPurpose.patientRegistration => 'PATIENT_REGISTRATION',
  OtpPurpose.login => 'LOGIN',
  OtpPurpose.inviteAccept => 'INVITE_ACCEPT',
  OtpPurpose.passwordReset => 'PASSWORD_RESET',
};

class OtpRequestBody {
  const OtpRequestBody({required this.mobile, required this.purpose});
  final String mobile;
  final OtpPurpose purpose;
  Map<String, dynamic> toJson() => {
    'mobile': mobile,
    'purpose': _purposeValue(purpose),
  };
}

class OtpVerifyBody {
  const OtpVerifyBody({required this.mobile, required this.otp});
  final String mobile;
  final String otp;
  Map<String, dynamic> toJson() => {'mobile': mobile, 'otp': otp};
}

class LoginRequest {
  const LoginRequest({
    this.mobile,
    this.email,
    this.password,
    this.otpToken,
    this.deviceFingerprint,
    this.deviceLabel,
  });
  final String? mobile;
  final String? email;
  final String? password;
  final String? otpToken;
  final String? deviceFingerprint;
  final String? deviceLabel;
  Map<String, dynamic> toJson() => {
    'mobile': mobile,
    'email': email,
    'password': password,
    'otp_token': otpToken,
    'device_fingerprint': deviceFingerprint,
    'device_label': deviceLabel,
  };
}

class MfaVerifyRequest {
  const MfaVerifyRequest({
    required this.mfaChallengeToken,
    required this.totpCode,
    this.deviceFingerprint,
    this.deviceLabel,
  });
  final String mfaChallengeToken;
  final String totpCode;
  final String? deviceFingerprint;
  final String? deviceLabel;
  Map<String, dynamic> toJson() => {
    'mfa_challenge_token': mfaChallengeToken,
    'totp_code': totpCode,
    'device_fingerprint': deviceFingerprint,
    'device_label': deviceLabel,
  };
}

class TokenRefreshRequest {
  const TokenRefreshRequest({
    required this.refreshToken,
    this.deviceFingerprint,
  });
  final String refreshToken;
  final String? deviceFingerprint;
  Map<String, dynamic> toJson() => {
    'refresh_token': refreshToken,
    'device_fingerprint': deviceFingerprint,
  };
}

class InviteAcceptRequest {
  const InviteAcceptRequest({
    required this.token,
    required this.mobileOtp,
    this.password,
    this.passwordConfirm,
  });
  final String token;
  final String? password;
  final String? passwordConfirm;
  final String mobileOtp;
  Map<String, dynamic> toJson() => {
    'token': token,
    'password': password,
    'password_confirm': passwordConfirm,
    'mobile_otp': mobileOtp,
  };
}

class PasswordResetRequestBody {
  const PasswordResetRequestBody({required this.mobile});
  final String mobile;
  Map<String, dynamic> toJson() => {'mobile': mobile};
}

class PasswordResetBody {
  const PasswordResetBody({
    required this.mobile,
    required this.otp,
    required this.newPassword,
    required this.newPasswordConfirm,
  });
  final String mobile;
  final String otp;
  final String newPassword;
  final String newPasswordConfirm;
  Map<String, dynamic> toJson() => {
    'mobile': mobile,
    'otp': otp,
    'new_password': newPassword,
    'new_password_confirm': newPasswordConfirm,
  };
}

class PasswordChangeRequest {
  const PasswordChangeRequest({
    required this.currentPassword,
    required this.newPassword,
    required this.newPasswordConfirm,
  });
  final String currentPassword;
  final String newPassword;
  final String newPasswordConfirm;
  Map<String, dynamic> toJson() => {
    'current_password': currentPassword,
    'new_password': newPassword,
    'new_password_confirm': newPasswordConfirm,
  };
}
