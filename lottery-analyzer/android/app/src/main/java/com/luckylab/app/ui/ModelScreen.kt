package com.luckylab.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.luckylab.app.data.ApiClient
import com.luckylab.app.data.PredictReq
import com.luckylab.app.data.PredictResp
import com.luckylab.app.data.ReportDto
import com.luckylab.app.data.RunsResp
import com.luckylab.app.data.TrainReq
import com.luckylab.app.data.TrainResp
import kotlinx.coroutines.launch

/**
 * 模型与回测页：训练（时间切分训练/测试集）→ 回测指标 → 下期参考概率。
 * 方法与免责声明由服务端报告携带并在此展示（随机性提示不省略）。
 */
@Composable
fun ModelScreen(game: String, onMessage: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var ratio by remember { mutableStateOf("0.2") }
    var window by remember { mutableStateOf("30") }
    var runs by remember { mutableStateOf<RunsResp?>(null) }
    var report by remember { mutableStateOf<ReportDto?>(null) }
    var trainInfo by remember { mutableStateOf("") }
    var predict by remember { mutableStateOf<PredictResp?>(null) }
    var tick by remember { mutableIntStateOf(0) }

    LaunchedEffect(game, tick) {
        runCatching {
            runs = ApiClient.api().runs(game, limit = 20)
            runs?.rows?.firstOrNull()?.let { report = ApiClient.api().runDetail(it.id).report }
        }.onFailure { onMessage("运行列表失败：${it.message}") }
    }

    Column(Modifier.padding(12.dp)) {
        SectionCard("训练与回测") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = ratio, onValueChange = { ratio = it },
                    label = { Text("测试比例") }, singleLine = true, modifier = Modifier.fillMaxWidth(0.32f),
                )
                OutlinedTextField(
                    value = window, onValueChange = { window = it.filter { c -> c.isDigit() } },
                    label = { Text("特征窗口") }, singleLine = true, modifier = Modifier.fillMaxWidth(0.32f),
                )
                Button(onClick = {
                    scope.launch {
                        runCatching {
                            ApiClient.api().train(
                                TrainReq(
                                    game = game,
                                    testRatio = ratio.toDoubleOrNull() ?: 0.2,
                                    window = window.toIntOrNull() ?: 30,
                                ),
                            )
                        }.onSuccess { t: TrainResp ->
                            trainInfo = "#${t.runId} AUC=${t.metrics?.auc} Top${t.simulation?.topK}" +
                                " 平均命中${t.simulation?.avgHits}（随机基线${t.simulation?.randomBaselineAvgHits}）"
                            tick++
                        }.onFailure { onMessage("训练失败：${it.message}") }
                    }
                }) { Text("训练") }
            }
            StatusText(trainInfo)
        }

        predict?.let { p ->
            SectionCard("下期参考（Top${p.topK.size}，基于运行#${p.basedOnRunId}，样本${p.basedOnDraws}期）") {
                Row { BallRow(p.topK.map { it.num }, picks = p.topK.map { it.num }.toSet()) }
                Text(
                    "概率：" + p.topK.joinToString("，") { "${it.num}→${"%.3f".format(it.prob)}" },
                    style = MaterialTheme.typography.bodySmall,
                )
                DisclaimerBox(p.disclaimer)
            }
        }

        SectionCard("历史运行（最新在上）") {
            LazyColumn(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                items(runs?.rows ?: emptyList()) { r ->
                    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("#${r.id} ${r.gameName}", fontWeight = FontWeight.Medium, fontSize = 14.sp)
                            Text("AUC=${r.metrics?.auc ?: "-"}", fontSize = 13.sp)
                        }
                        Text(
                            "窗口${r.window} 测试${r.testRatio} 样本${r.trainSamples}/${r.testSamples} · ${r.createdAt}",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        OutlinedButton(onClick = {
                            scope.launch {
                                runCatching { ApiClient.api().runDetail(r.id) }
                                    .onSuccess { report = it.report }
                                    .onFailure { onMessage("报告加载失败：${it.message}") }
                            }
                        }) { Text("查看报告") }
                        HorizontalDivider()
                    }
                }
            }
        }

        report?.let { rep ->
            SectionCard("回测报告摘要") {
                Text(
                    buildString {
                        appendLine("特征: ${rep.featureVersion ?: "-"} (${rep.featureNames?.joinToString(",") ?: "-"})")
                        appendLine("窗口: ${rep.window ?: "-"}  指纹: ${rep.datasetFingerprint?.take(16) ?: "-"}")
                        rep.drawRange?.let { appendLine("训练范围: ${it.firstOrNull()} ~ ${it.lastOrNull()}") }
                        rep.testDrawRange?.let { appendLine("测试范围: ${it.firstOrNull()} ~ ${it.lastOrNull()}") }
                    },
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    "完整报告（含模拟细节与免责声明）见 Web 端或 GET /api/model/runs/{id}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(onClick = {
                    scope.launch {
                        runCatching { ApiClient.api().predict(PredictReq(game)) }
                            .onSuccess { predict = it }
                            .onFailure { onMessage("预测失败：${it.message}") }
                    }
                }) { Text("基于最新运行预测下期") }
            }
        }
    }
}
