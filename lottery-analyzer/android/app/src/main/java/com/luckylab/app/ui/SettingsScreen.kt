package com.luckylab.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.luckylab.app.data.ApiClient
import com.luckylab.app.data.AppGraph
import kotlinx.coroutines.launch

/**
 * 设置页：后端地址（共享 Web 同一后端）。
 * 模拟器默认 http://10.0.2.2:8000/；真机改为电脑局域网 IP（如 http://192.168.1.100:8000/）。
 */
@Composable
fun SettingsScreen(onMessage: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(AppGraph.loadBaseUrl(context)) }
    var health by remember { mutableStateOf("") }

    Column(Modifier.padding(12.dp)) {
        SectionCard("后端服务地址") {
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Base URL") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(top = 8.dp),
            ) {
                Button(onClick = {
                    runCatching { AppGraph.saveBaseUrl(context, url) }
                        .onSuccess { url = it; onMessage("已保存并切换：$it") }
                        .onFailure { onMessage("保存失败：${it.message}") }
                }) { Text("保存") }
                OutlinedButton(onClick = {
                    scope.launch {
                        runCatching { ApiClient.api().health() }
                            .onSuccess { health = "✅ ${it.status} · 彩种：${it.games.joinToString("、")} · v${it.version}" }
                            .onFailure { health = "❌ ${it.message}" }
                    }
                }) { Text("测试连接") }
            }
            if (health.isNotEmpty()) {
                Text(health, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
            }
            Text(
                "提示：模拟器访问宿主机用 10.0.2.2；真机请与本机同处一个局域网，并填写电脑的局域网 IP。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 6.dp),
            )
        }

        SectionCard("数据与免责声明") {
            Text(
                "开奖数据仅来自官方公开渠道（双色球：中国福彩官网公告接口；大乐透：中国体彩官方 webapi）。" +
                    "官方接口不可用时同步失败并记录日志，应用不生成任何合成开奖数据。",
                style = MaterialTheme.typography.bodySmall,
            )
            DisclaimerBox(
                "彩票开奖为独立随机事件。历史统计、模型回测指标与预测结果仅供方法学习与数据参考，" +
                    "不构成投注建议；请理性购彩，量力而行。",
            )
        }
    }
}
