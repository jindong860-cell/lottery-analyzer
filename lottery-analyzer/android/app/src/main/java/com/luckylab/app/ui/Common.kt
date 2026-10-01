package com.luckylab.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.luckylab.app.ui.Blue
import com.luckylab.app.ui.Red

/** 号码球：红/蓝圆形（与 Web 视觉一致）。pick=true 时金色描边（Top-K 预测）。 */
@Composable
fun Ball(num: Int, blue: Boolean = false, pick: Boolean = false) {
    Box(
        modifier = Modifier
            .padding(2.dp)
            .size(34.dp)
            .background(if (blue) Blue else Red, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = num.toString().padStart(2, '0'),
            color = if (pick) Color(0xFFFBBF24) else Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp,
        )
    }
}

@Composable
fun BallRow(nums: List<Int>, blue: Boolean = false, picks: Set<Int> = emptySet()) {
    Row { nums.forEach { Ball(it, blue, picks.contains(it)) } }
}

@Composable
fun SectionCard(title: String, content: @Composable () -> Unit) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        tonalElevation = 1.dp,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
    }
}

@Composable
fun Labeled(label: String, content: @Composable () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        content()
    }
}

@Composable
fun StatusText(text: String) {
    if (text.isNotEmpty()) {
        Text(
            text,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

@Composable
fun DisclaimerBox(text: String) {
    if (text.isEmpty()) return
    Surface(
        color = Color(0xFFFEF3C7),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 8.dp),
    ) {
        Text(
            text,
            color = Color(0xFF92400E),
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(8.dp),
        )
    }
}
