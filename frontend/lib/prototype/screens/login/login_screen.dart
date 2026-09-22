import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers/email_auth_provider.dart';
import '../../providers/prototype_session_provider.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _emailController = TextEditingController();
  final _otpController = TextEditingController();
  Timer? _timer;
  int _resendSeconds = 0;
  String? _validationError;

  @override
  void dispose() {
    _timer?.cancel();
    _emailController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  void _startCountdown() {
    _timer?.cancel();
    setState(() => _resendSeconds = 30);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return;
      setState(() => _resendSeconds--);
      if (_resendSeconds <= 0) timer.cancel();
    });
  }

  Future<void> _sendOtp() async {
    final email = _emailController.text.trim();
    if (!RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(email)) {
      setState(() => _validationError = 'Enter a valid email address.');
      return;
    }
    if (prototypeDemoMode && email.toLowerCase() != 'demo@gmail.com') {
      setState(() => _validationError = 'Use demo@gmail.com in Demo Mode.');
      return;
    }
    setState(() => _validationError = null);
    await ref.read(emailAuthProvider.notifier).sendOtp(email);
    if (mounted && ref.read(emailAuthProvider).status == EmailAuthStatus.sent) {
      _startCountdown();
    }
  }

  Future<void> _verifyOtp() async {
    final otp = _otpController.text.trim();
    if (!RegExp(r'^\d{6}$').hasMatch(otp)) {
      setState(() => _validationError = 'Enter the six-digit OTP.');
      return;
    }
    setState(() => _validationError = null);
    await ref.read(emailAuthProvider.notifier).verifyOtp(otp);
    if (mounted &&
        ref.read(emailAuthProvider).status == EmailAuthStatus.authenticated) {
      context.go('/home');
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(emailAuthProvider);
    final sent = auth.otpSent;
    final theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Column(
                children: [
                  Icon(
                    Icons.medical_services_outlined,
                    size: 56,
                    color: theme.colorScheme.primary,
                  ),
                  const SizedBox(height: 12),
                  Text('SETU', style: theme.textTheme.displaySmall),
                  Text('Swasthya', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 8),
                  const Text('Digital Health & Care Management'),
                  const SizedBox(height: 32),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            'STAFF SIGN UP',
                            style: theme.textTheme.labelLarge,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Create your account',
                            style: theme.textTheme.headlineSmall,
                          ),
                          const SizedBox(height: 8),
                          const Text(
                            'Sign up with your Gmail address to access the SETU-Swasthya workspace.',
                          ),
                          if (prototypeDemoMode)
                            const Padding(
                              padding: EdgeInsets.only(top: 8),
                              child: Text(
                                'DEMO MODE - Synthetic OTP: 123456. Use synthetic data only.',
                              ),
                            ),
                          const SizedBox(height: 24),
                          TextField(
                            key: const ValueKey('email-field'),
                            controller: _emailController,
                            enabled: !sent && !auth.isBusy,
                            keyboardType: TextInputType.emailAddress,
                            autofillHints: const [AutofillHints.email],
                            textInputAction: TextInputAction.done,
                            decoration: const InputDecoration(
                              labelText: 'Email address',
                              prefixIcon: Icon(Icons.email_outlined),
                            ),
                          ),
                          const SizedBox(height: 16),
                          if (!sent)
                            FilledButton.icon(
                              key: const ValueKey('send-otp-button'),
                              onPressed: auth.isBusy ? null : _sendOtp,
                              icon: const Icon(Icons.send_outlined),
                              label: Text(
                                auth.isBusy
                                    ? 'Sending...'
                                    : 'Create account & send OTP',
                              ),
                            ),
                          if (sent) ...[
                            Text(
                              prototypeDemoMode
                                  ? 'Demo code for ${auth.email}'
                                  : 'Code sent to ${auth.email}',
                            ),
                            const SizedBox(height: 12),
                            TextField(
                              key: const ValueKey('otp-field'),
                              controller: _otpController,
                              keyboardType: TextInputType.number,
                              maxLength: 6,
                              decoration: const InputDecoration(
                                labelText: 'Six-digit OTP',
                                prefixIcon: Icon(Icons.password_outlined),
                              ),
                            ),
                            FilledButton(
                              key: const ValueKey('verify-otp-button'),
                              onPressed: auth.isBusy ? null : _verifyOtp,
                              child: Text(
                                auth.isBusy ? 'Verifying...' : 'Verify OTP',
                              ),
                            ),
                            TextButton(
                              key: const ValueKey('resend-otp-button'),
                              onPressed: auth.isBusy || _resendSeconds > 0
                                  ? null
                                  : _sendOtp,
                              child: Text(
                                _resendSeconds > 0
                                    ? 'Resend in ${_resendSeconds}s'
                                    : 'Resend OTP',
                              ),
                            ),
                            TextButton(
                              onPressed: auth.isBusy
                                  ? null
                                  : () {
                                      _timer?.cancel();
                                      _otpController.clear();
                                      ref
                                          .read(emailAuthProvider.notifier)
                                          .changeEmail();
                                    },
                              child: const Text('Change email'),
                            ),
                          ],
                          if (_validationError != null)
                            Text(
                              _validationError!,
                              style: TextStyle(color: theme.colorScheme.error),
                            ),
                          if (auth.errorMessage != null)
                            Text(
                              auth.errorMessage!,
                              style: TextStyle(color: theme.colorScheme.error),
                            ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
