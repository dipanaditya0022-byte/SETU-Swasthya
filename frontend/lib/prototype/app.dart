import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/router/app_router.dart';
import '../core/theme/app_theme.dart';
import 'providers/sync_providers.dart';
import 'providers/prototype_session_provider.dart';

class SetuSwasthyaApp extends StatelessWidget {
  const SetuSwasthyaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ProviderScope(child: const _SyncBootstrap());
  }
}

class _SyncBootstrap extends ConsumerWidget {
  const _SyncBootstrap();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!prototypeDemoMode) ref.watch(syncControllerProvider);
    return MaterialApp.router(
      title: 'SETU-Swasthya',
      theme: AppTheme.lightTheme(),
      routerConfig: AppRouter.router,
    );
  }
}
