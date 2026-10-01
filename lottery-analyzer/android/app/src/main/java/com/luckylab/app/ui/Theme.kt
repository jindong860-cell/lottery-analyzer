package com.luckylab.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// 与 Web 端同色系：主红 + 蓝球。
val Red = Color(0xFFB91C1C)
val RedDark = Color(0xFF991B1B)
val Blue = Color(0xFF2563EB)
val Amber = Color(0xFFFBBF24)

private val LightColors = lightColorScheme(
    primary = Red,
    onPrimary = Color.White,
    secondary = Blue,
    tertiary = Amber,
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFF87171),
    onPrimary = Color(0xFF1F0505),
    secondary = Color(0xFF93C5FD),
)

@Composable
fun LuckyLabTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}
