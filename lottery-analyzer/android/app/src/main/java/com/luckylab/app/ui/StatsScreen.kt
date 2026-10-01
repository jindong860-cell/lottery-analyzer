package com.luckylab.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.unit.dp
import com.luckylab.app.data.ApiClient
import com.luckylab.app.data.FreqResp
import com.luckylab.app.data.OmitResp
import com.luckylab.app.data.TrendResp

/**
 * 统计分析页：频率（柱图）、遗漏、走势。
 * 计算方法（与服务端一致，结果页均附）：
 *  频率 = 出现期数 / 统计期数；遗漏当前 = 距最近开出的期数；最大 = 历史最长间隔；平均 = 历史间隔均值。
 */
@Composable
fun StatsScreen(game: String, onMessage: (String) -> Unit) {
    var window by remember { mutableStateOf("100") }
    var freq by remember { mutableStateOf<FreqResp?>(null) }
    var omit by remember { mutableStateOf<OmitResp?>(null) }
    var trend by remember { mutableStateOf<TrendResp?>(null) }
    var loadTick by remember { mutableIntStateOf(0) }

    LaunchedEffect(game, loadTick) {
        runCatching {
            freq = ApiClient.api().frequency(game, window = window.toIntOrNull() ?: 0)
            omit = ApiClient.api().omission(game)
            trend = ApiClient.api().trend(game, lastN = 30)
        }.onFailure { onMessage("统计失败：${it.message}") }
    }

    LazyColumn(Modifier.padding(12.dp)) {
        item {
            SectionCard("统计窗口") {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = window,
                        onValueChange = { window = it.filter { c -> c.isDigit() } },
                        label = { Text("期数(0=全部)") },
                        modifier = Modifier.fillMaxWidth(0.5f),
                        singleLine = true,
                    )
                    Button(onClick = { loadTick++ }) { Text("计算") }
                }
            }
        }
        freq?.let { f ->
            item {
                SectionCard("前区频率（最近${f.drawCount}期）") {
                    FreqCanvas(f)
                }
            }
        }
        omit?.let { o ->
            item {
                SectionCard("前区遗漏（当前/最大/平均）") {
                    LazyColumn(Modifier.height(260.dp)) {
                        items(o.front) { x ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text("${x.num}", Modifier.padding(start = 8.dp))
                                Text(
                                    "${x.current} / ${x.max} / ${x.avg ?: "从未"}",
                                    Modifier.padding(end = 8.dp),
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                        }
                    }
                }
            }
        }
        trend?.let { t ->
            item {
                SectionCard("近期走势（最新在前，前${t.lastN}期）") {
                    LazyColumn {
                        items(t.rows) { r ->
                            Row(
                                Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                            ) {
                                Text("${r.issue}·${r.drawDate.take(10)}", style = MaterialTheme.typography.bodySmall)
                                BallRow(r.reds)
                                BallRow(r.blues, blue = true)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 频率柱状图：Canvas 绘制，柱高∝count，号码标注在底部。 */
@Composable
private fun FreqCanvas(freq: FreqResp) {
    val bar = MaterialTheme.colorScheme.primary
    Canvas(
        Modifier
            .fillMaxWidth()
            .height(180.dp)
            .padding(top = 6.dp),
    ) {
        val data = freq.front
        val maxC = maxOf(1, data.maxOf { it.count })
        val bw = size.width / data.size
        val chartH = size.height - 24f
        data.forEachIndexed { i, d ->
            val h = (d.count.toDouble() / maxC * chartH).toFloat()
            drawRect(
                color = bar,
                topLeft = Offset(i * bw + 1f, chartH - h),
                size = Size((bw - 3f).coerceAtLeast(2f), h),
            )
            drawIntoCanvas { c ->
                val paint = android.graphics.Paint().apply {
                    color = android.graphics.Color.GRAY
                    textSize = 20f
                    isAntiAlias = true
                }
                c.nativeCanvas.drawText(
                    d.num.toString(),
                    i * bw + bw / 2 - 10f,
                    size.height - 6f,
                    paint,
                )
            }
        }
    }
    Text(
        "频率=出现期数/${freq.drawCount}期；蓝球口径同理，详见「说明」",
        style = MaterialTheme.typography.bodySmall,
        color = Color.Gray,
    )
}
