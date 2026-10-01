package com.luckylab.app.ui

import android.graphics.Bitmap
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import com.luckylab.app.data.ApiClient
import com.luckylab.app.data.SampleDto
import com.luckylab.app.data.SamplesResp
import com.luckylab.app.data.VerifyReq
import com.luckylab.app.ocr.DEFAULT_PROFILES
import com.luckylab.app.ocr.LocalMatch
import com.luckylab.app.ocr.ScratchPipeline
import com.luckylab.app.ocr.TicketProfile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * 刮刮乐验证页：拍照/相册 → 本地流水线（票种→ROI→ML Kit OCR→模板匹配）→ 上传服务端落库
 * → 录入实际结果验证 → 准确率统计。置信度不足（<0.60）或无匹配时强制人工复核。
 */
@Composable
fun ScratchScreen(game: String, onMessage: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var photo by remember { mutableStateOf<Bitmap?>(null) }
    var local by remember { mutableStateOf<LocalMatch?>(null) }
    var profiles by remember { mutableStateOf(DEFAULT_PROFILES) }
    var hintId by remember { mutableStateOf<String?>(null) }
    var samples by remember { mutableStateOf<SamplesResp?>(null) }
    var accuracyText by remember { mutableStateOf("") }
    var verifyFor by remember { mutableStateOf<SampleDto?>(null) }
    var busy by remember { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }

    // 拍照：FileProvider 临时文件（cache/photos/）
    val cameraFile = remember { File(File(context.cacheDir, "photos").apply { mkdirs() }, "capture.jpg") }
    val cameraUri = remember {
        FileProvider.getUriForFile(context, context.packageName + ".fileprovider", cameraFile)
    }
    val takePicture = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) {
            photo = ScratchPipeline.loadBitmap(context, cameraUri)
        }
    }
    val pickImage = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            runCatching { ScratchPipeline.loadBitmap(context, uri) }
                .onSuccess { photo = it }
                .onFailure { onMessage("读取图片失败：${it.message}") }
        }
    }

    // 拉取服务端票种模板（失败回退内置默认）与样本列表
    LaunchedEffect(tick) {
        runCatching { ApiClient.api().profiles() }
            .onSuccess { resp ->
                profiles = resp.profiles.map { p ->
                    TicketProfile(
                        id = p.id, name = p.name, aspectMin = p.aspectMin, aspectMax = p.aspectMax,
                        refRgb = Triple(
                            p.refRgb.getOrElse(0) { 0 },
                            p.refRgb.getOrElse(1) { 0 },
                            p.refRgb.getOrElse(2) { 0 },
                        ),
                        colorTol = p.colorTol, amountRoi = p.amountRoi,
                        prizeTable = p.prizeTable.entries.associate { (k, v) -> (k.toIntOrNull() ?: 0) to v }
                            .filterKeys { it > 0 },
                    )
                }.ifEmpty { DEFAULT_PROFILES }
            }
        runCatching {
            samples = ApiClient.api().samples(limit = 30)
            val acc = ApiClient.api().accuracy()
            accuracyText = "已验证 ${acc.autoVerified.total} 条：命中 ${acc.autoVerified.match}，" +
                "不符 ${acc.autoVerified.mismatch}，准确率 " +
                (acc.autoVerified.accuracy?.let { "%.1f%%".format(it * 100) } ?: "-")
        }.onFailure { onMessage("样本加载失败：${it.message}") }
    }

    // 本地识别流水线（位图变化触发）
    LaunchedEffect(photo, hintId) {
        val bmp = photo ?: return@LaunchedEffect
        busy = true
        local = withContext(Dispatchers.IO) { ScratchPipeline.run(bmp, hintId, profiles) }
        busy = false
    }

    LazyColumn(Modifier.padding(12.dp)) {
        item {
            SectionCard("① 拍摄/选择未刮票据") {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { takePicture.launch(cameraUri) }) { Text("拍照") }
                    OutlinedButton(onClick = { pickImage.launch("image/*") }) { Text("相册") }
                    if (photo != null) {
                        OutlinedButton(onClick = { photo = null; local = null }) { Text("清除") }
                    }
                }
                photo?.let {
                    Image(
                        bitmap = it.asImageBitmap(),
                        contentDescription = "票据预览",
                        contentScale = ContentScale.FillWidth,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                }
            }
        }

        local?.let { m ->
            item {
                SectionCard("② 本地识别结果") {
                    m.roiBitmap?.let {
                        Image(
                            bitmap = it.asImageBitmap(),
                            contentDescription = "奖区ROI",
                            contentScale = ContentScale.FillWidth,
                            modifier = Modifier.fillMaxWidth(0.6f),
                        )
                    }
                    Text("票种：${m.profile?.name ?: "未识别"}（${m.reason}）", style = MaterialTheme.typography.bodyMedium)
                    Text("OCR(${m.ocrEngine})：${m.ocrText.ifBlank { "(空)" }}", style = MaterialTheme.typography.bodySmall)
                    Text("金额候选：${m.amounts.joinToString("、") { "$it 元" }.ifEmpty { "无" }}", style = MaterialTheme.typography.bodySmall)
                    Text("预测：${m.predictedRank ?: "无"} / ${m.predictedAmount ?: "-"} 元", fontWeight = androidx.compose.ui.text.font.FontWeight.Medium)
                    Text(
                        "置信度 ${m.confidence}" + if (m.needsReview) " · ⚠ 需人工复核（${m.reviewReason}）" else "",
                        color = if (m.needsReview) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
            item {
                SectionCard("③ 上传服务端落库（可追溯）") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            enabled = !busy,
                            onClick = {
                                val bmp = photo ?: return@Button
                                scope.launch {
                                    busy = true
                                    runCatching {
                                        val bytes = ByteArrayOutputStream().use { out ->
                                            bmp.compress(Bitmap.CompressFormat.JPEG, 90, out)
                                            out.toByteArray()
                                        }
                                        val part = MultipartBody.Part.createFormData(
                                            "image", "capture.jpg", bytes.toRequestBody("image/jpeg".toMediaType()),
                                        )
                                        val text = "text/plain".toMediaType()
                                        ApiClient.api().uploadSample(
                                            image = part,
                                            hint = hintId?.toRequestBody(text),
                                            device = "android".toRequestBody(text),
                                            note = ScratchPipeline.noteOf(m).toRequestBody(text),
                                        )
                                    }.onSuccess {
                                        onMessage("已入库 #${it.id}（服务端判定 needsReview=${it.needsReview}）")
                                        tick++
                                    }.onFailure { onMessage("上传失败：${it.message}") }
                                    busy = false
                                }
                            },
                        ) { Text("上传并生成样本") }
                        OutlinedButton(onClick = { verifyFor = null; scope.launch { tick++ } }) { Text("刷新") }
                    }
                    StatusText(busy.ifTrue { "处理中…" } ?: "")
                }
            }
        }

        item {
            SectionCard("④ 样本与验证闭环") {
                StatusText(accuracyText)
                LazyColumn(Modifier.height(300.dp)) {
                    items(samples?.rows ?: emptyList()) { s ->
                        Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text("#${s.id} ${s.ticketType ?: "未识别"}", style = MaterialTheme.typography.bodyMedium)
                                Text(
                                    when (s.matchStatus) {
                                        "match" -> "✅命中"
                                        "mismatch" -> "❌不符"
                                        "review" -> "⚠复核"
                                        else -> "待录入"
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                            Text(
                                "预测:${s.predictedRank ?: "-"} 实际:${s.actualRank ?: "-"} conf=${s.confidence ?: "-"}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            TextButton(onClick = { verifyFor = s }) { Text("录入实际结果") }
                        }
                    }
                }
            }
        }
    }

    verifyFor?.let { s ->
        var rank by remember(s.id) { mutableStateOf(s.predictedRank ?: "") }
        var amount by remember(s.id) { mutableStateOf(s.predictedAmount?.toString() ?: "") }
        AlertDialog(
            onDismissRequest = { verifyFor = null },
            title = { Text("录入实际结果（样本 #${s.id}）") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = rank, onValueChange = { rank = it }, label = { Text("实际奖级(如 100元档)") }, singleLine = true)
                    OutlinedTextField(
                        value = amount,
                        onValueChange = { amount = it.filter { c -> c.isDigit() } },
                        label = { Text("实际金额(元)") }, singleLine = true,
                    )
                    Text("两项至少填一项；与预测逐字段比对后标记 命中/不符/复核。", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        runCatching {
                            ApiClient.api().verify(
                                s.id,
                                VerifyReq(
                                    actualRank = rank.ifBlank { null },
                                    actualAmount = amount.toIntOrNull(),
                                ),
                            )
                        }.onSuccess {
                            onMessage("已验证 #${s.id}：${it.matchStatus}")
                            verifyFor = null
                            tick++
                        }.onFailure { onMessage("验证失败：${it.message}") }
                    }
                }) { Text("提交") }
            },
            dismissButton = { TextButton(onClick = { verifyFor = null }) { Text("取消") } },
        )
    }
}

private fun Boolean.ifTrue(block: () -> String): String? = if (this) block() else null
