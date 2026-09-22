import 'package:flutter/material.dart';

abstract final class AppColors {
  static const teal = Color(0xFF087F7B);
  static const background = Color(0xFFF7F8F5);
  static const emergency = Color(0xFFC93636);
}

abstract final class AppTheme {
  static ThemeData get light {
    final colorScheme =
        ColorScheme.fromSeed(
          seedColor: AppColors.teal,
          brightness: Brightness.light,
        ).copyWith(
          primary: AppColors.teal,
          surface: Colors.white,
          error: AppColors.emergency,
        );

    return ThemeData(
      colorScheme: colorScheme,
      scaffoldBackgroundColor: AppColors.background,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.white,
        foregroundColor: Color(0xFF173331),
        elevation: 0,
      ),
      cardTheme: const CardThemeData(
        color: Colors.white,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(20)),
        ),
      ),
      inputDecorationTheme: const InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.all(Radius.circular(12)),
        ),
      ),
      useMaterial3: true,
    );
  }
}
