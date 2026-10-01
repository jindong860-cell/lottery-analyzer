package com.luckylab.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.luckylab.app.data.ApiClient
import com.luckylab.app.data.DrawsPageDto
import com.luckylab.app.data.SyncLogResp
import com.luckylab.app.data.SyncReq
import kotlinx.coroutines.launch

/**
 * 开奖数据页：官方数据源增量/全量同步、分页浏览、同步日志。
 * 数据源（服务端已固化，客户端不直接访问外网）：
 *  - 双色球：中国福利彩票发行管理中心官网开奖公告接口
 *  - 大乐透：中国体育彩票官方 webapi（gameNo=85）
 */
@Composable
fun DrawsScreen(game: String, onMessage: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var page by remember { mutableIntStateOf(1) }
    var data by remember { mutableStateOf<DrawsPageDto?>(null) }
    var log by remember { mutableStateOf<SyncLogResp?>(null) }
    var busy by remember { mutableStateOf(false) }

    suspend fun load() {
        runCatching {
            data = ApiClient.api().draws(game, page = page, pageSize = 20)
            log = ApiClient.api().syncLog()
        }.onFailure { onMessage("加载失败：${it.message}") }
    }

    LaunchedEffect(game, page) { load() }

    Column(Modifier.padding(12.dp)) {
        SectionCard("官方数据同步") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    enabled = !busy,
                    onClick = {
                        scope.launch {
                            busy = true
                            runCatching { ApiClient.api().sync(SyncReq(game, "incremental")) }
                                .onSuccess {
                                    onMessage("增量完成：拉取${it.fetched} 新增${it.inserted} 更新${it.updated}")
                                    load()
                                }
                                .onFailure { onMessage("同步失败：${it.message}") }
                            busy = false
                        }
                    },
                ) { Text("增量同步") }
                OutlinedButton(
                    enabled = !busy,
                    onClick = {
                        scope.launch {
                            busy = true
                            runCatching { ApiClient.api().sync(SyncReq(game, "full")) }
                                .onSuccess {
                                    onMessage("全量完成：库内共${it.totalInDb}期")
                                    page = 1
                                    load()
                                }
                                .onFailure { onMessage("同步失败：${it.message}") }
                            busy = false
                        }
                    },
                ) { Text("首次全量(≤1000期)") }
            }
            StatusText(busy.ifTrue { "同步中…" } ?: "")
        }

        SectionCard("开奖列表（${data?.total ?: 0} 期）") {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                TextButton(enabled = page > 1, onClick = { page-- }) { Text("上一页") }
                Text(
                    "第 $page / ${data?.let { maxOf(1, (it.total + it.pageSize - 1) / it.pageSize) } ?: 1} 页",
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(enabled = data?.let { page * it.pageSize < it.total } == true, onClick = { page++ }) { Text("下一页") }
            }
            LazyColumn {
                items(data?.rows ?: emptyList()) { r ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 6.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column {
                            Text("第 ${r.issue} 期", style = MaterialTheme.typography.bodyMedium)
                            Text(r.drawDate, style = MaterialTheme.typography.bodySmall)
                        }
                        BallRow(r.reds)
                        BallRow(r.blues, blue = true)
                    }
                }
            }
        }

        SectionCard("同步日志（最近10条）") {
            LazyColumn {
                items((log?.rows ?: emptyList()).take(10)) { r ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 3.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text("${r.game} ${if (r.ok) "✅" else "❌"} ${r.inserted}/${r.updated}", style = MaterialTheme.typography.bodySmall)
                        Text(
                            r.message.take(26),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

private fun Boolean.ifTrue(block: () -> String): String? = if (this) block() else null
