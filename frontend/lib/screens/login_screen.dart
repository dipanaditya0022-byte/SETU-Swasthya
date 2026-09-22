import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api_service.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({this.apiService, super.key});

  final ApiService? apiService;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _mobileFieldKey = GlobalKey<FormFieldState<String>>();
  final _otpFieldKey = GlobalKey<FormFieldState<String>>();
  final _mobileController = TextEditingController();
  final _otpController = TextEditingController();

  late final ApiService _apiService;
  bool _otpRequested = false;
  bool _isRequestingOtp = false;
  bool _isVerifyingOtp = false;
  String? _errorMessage;

  bool get _isBusy => _isRequestingOtp || _isVerifyingOtp;

  @override
  void initState() {
    super.initState();
    _apiService = widget.apiService ?? ApiService.instance;
  }

  @override
  void dispose() {
    _mobileController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  String? _validateMobile(String? value) {
    final mobile = value?.trim() ?? '';
    if (mobile.isEmpty) return 'Please enter your mobile number';
    if (!RegExp(r'^\+[1-9]\d{9,14}$').hasMatch(mobile)) {
      return 'Use international format, for example +919000000106';
    }
    return null;
  }

  String? _validateOtp(String? value) {
    final otp = value?.trim() ?? '';
    if (!RegExp(r'^\d{6}$').hasMatch(otp)) {
      return 'Enter the six-digit OTP';
    }
    return null;
  }

  Future<void> _requestOtp() async {
    if (_isBusy || !(_mobileFieldKey.currentState?.validate() ?? false)) {
      return;
    }

    setState(() {
      _isRequestingOtp = true;
      _errorMessage = null;
    });

    try {
      await _apiService.requestLoginOtp(_mobileController.text.trim());
      if (!mounted) return;
      setState(() {
        _otpRequested = true;
        _otpController.clear();
      });
    } on AuthenticationException catch (error) {
      if (mounted) setState(() => _errorMessage = error.message);
    } catch (_) {
      if (mounted) {
        setState(
          () => _errorMessage =
              'Unable to send the OTP. Please check the server connection.',
        );
      }
    } finally {
      if (mounted) setState(() => _isRequestingOtp = false);
    }
  }

  Future<void> _verifyOtp() async {
    if (_isBusy || !(_otpFieldKey.currentState?.validate() ?? false)) return;

    setState(() {
      _isVerifyingOtp = true;
      _errorMessage = null;
    });

    try {
      await _apiService.verifyLoginOtp(
        mobile: _mobileController.text.trim(),
        otp: _otpController.text.trim(),
      );
      if (mounted) context.go('/home');
    } on AuthenticationException catch (error) {
      if (mounted) setState(() => _errorMessage = error.message);
    } catch (_) {
      if (mounted) {
        setState(
          () => _errorMessage =
              'Unable to sign in. Please check the OTP or server connection.',
        );
      }
    } finally {
      if (mounted) setState(() => _isVerifyingOtp = false);
    }
  }

  void _changeMobile() {
    if (_isBusy) return;
    setState(() {
      _otpRequested = false;
      _otpController.clear();
      _errorMessage = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF12343B),
        title: const Text(
          'Sign In',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  width: 76,
                  height: 76,
                  decoration: BoxDecoration(
                    color: const Color(0xFFE5F1F2),
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: const Icon(
                    Icons.health_and_safety_outlined,
                    size: 42,
                    color: Color(0xFF075965),
                  ),
                ),
                const SizedBox(height: 20),
                const Text(
                  'Welcome to SETU-Swasthya',
                  style: TextStyle(
                    fontSize: 25,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF172124),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _otpRequested
                      ? 'Enter the OTP sent for ${_mobileController.text.trim()}.'
                      : 'Sign in with the mobile number linked to your staff account.',
                  style: const TextStyle(
                    color: Color(0xFF687477),
                    fontSize: 14,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 30),
                TextFormField(
                  key: _mobileFieldKey,
                  controller: _mobileController,
                  enabled: !_otpRequested && !_isBusy,
                  keyboardType: TextInputType.phone,
                  textInputAction: _otpRequested
                      ? TextInputAction.next
                      : TextInputAction.done,
                  onFieldSubmitted: (_) {
                    if (!_otpRequested) _requestOtp();
                  },
                  autofillHints: const [AutofillHints.telephoneNumber],
                  decoration: InputDecoration(
                    labelText: 'Mobile Number',
                    hintText: '+919000000106',
                    prefixIcon: const Icon(Icons.phone_outlined),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  validator: _validateMobile,
                ),
                if (_otpRequested) ...[
                  const SizedBox(height: 16),
                  TextFormField(
                    key: _otpFieldKey,
                    controller: _otpController,
                    enabled: !_isBusy,
                    keyboardType: TextInputType.number,
                    textInputAction: TextInputAction.done,
                    autofillHints: const [AutofillHints.oneTimeCode],
                    maxLength: 6,
                    obscureText: true,
                    onFieldSubmitted: (_) => _verifyOtp(),
                    decoration: InputDecoration(
                      labelText: 'Six-digit OTP',
                      prefixIcon: const Icon(Icons.password_outlined),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                    validator: _validateOtp,
                  ),
                ],
                const SizedBox(height: 24),
                SizedBox(
                  height: 52,
                  child: FilledButton.icon(
                    key: ValueKey(
                      _otpRequested
                          ? 'verify-login-otp-button'
                          : 'request-login-otp-button',
                    ),
                    style: FilledButton.styleFrom(
                      backgroundColor: const Color(0xFF075965),
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                    onPressed: _isBusy
                        ? null
                        : (_otpRequested ? _verifyOtp : _requestOtp),
                    icon: _isBusy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Icon(
                            _otpRequested
                                ? Icons.login
                                : Icons.send_to_mobile_outlined,
                          ),
                    label: Text(
                      _isRequestingOtp
                          ? 'Sending OTP...'
                          : _isVerifyingOtp
                          ? 'Verifying...'
                          : _otpRequested
                          ? 'Verify OTP & Sign In'
                          : 'Send OTP',
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
                if (_otpRequested) ...[
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      TextButton(
                        key: const ValueKey('resend-login-otp-button'),
                        onPressed: _isBusy ? null : _requestOtp,
                        child: const Text('Resend OTP'),
                      ),
                      TextButton(
                        onPressed: _isBusy ? null : _changeMobile,
                        child: const Text('Change mobile'),
                      ),
                    ],
                  ),
                ],
                if (_errorMessage != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _errorMessage!,
                    key: const ValueKey('login-error-message'),
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                const Text(
                  'Staff accounts are provisioned by authorised officials. '
                  'There is no public staff registration.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Color(0xFF7A8588),
                    fontSize: 11,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
