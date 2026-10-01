package com.luckylab.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Analytics
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.ModelTraining
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.FilterChip
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.luckylab.app.data.AppGraph
import com.luckylab.app.ui.DrawsScreen
import com.luckylab.app.ui.LuckyLabTheme
import com.luckylab.app.ui.ModelScreen
import com.luckylab.app.ui.ScratchScreen
import com.luckylab.app.ui.SettingsScreen
import com.luckylab.app.ui.StatsScreen
import kotlinx.coroutines.launch

/**
 * 单一应用入口：开奖 / 统计 / 模型 / 刮刮乐 / 设置 五个页签（对应冻结功能 F2–F6）。
 * 开奖彩种（双色球/大乐透）作为全局选择，作用于开奖、统计、模型三页。
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppGraph.init(this)
        setContent {
            LuckyLabTheme { MainApp() }
        }
    }
}

private data class Tab(val key: String, val label: String, val icon: @Composable () -> Unit)

@Composable
private fun MainApp() {
    var tab by remember { mutableStateOf("draws") }
    var game by remember { mutableStateOf("dlt") }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    fun notify(text: String) {
        scope.launch { snackbar.showSnackbar(text.take(120)) }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            NavigationBar {
                val tabs = listOf(
                    Tab("draws", "开奖") { Icon(Icons.Filled.Home, null) },
                    Tab("stats", "统计") { Icon(Icons.Filled.Analytics, null) },
                    Tab("model", "模型") { Icon(Icons.Filled.ModelTraining, null) },
                    Tab("scratch", "刮刮乐") { Icon(Icons.Filled.Info, null) },
                    Tab("settings", "设置") { Icon(Icons.Filled.Settings, null) },
                )
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t.key,
                        onClick = { tab = t.key },
                        icon = t.icon,
                        label = { Text(t.label) },
                    )
                }
            }
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            if (tab != "settings" && tab != "scratch") {
                Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
                    FilterChip(
                        selected = game == "dlt",
                        onClick = { game = "dlt" },
                        label = { Text("大乐透") },
                    )
                    androidx.compose.foundation.layout.Spacer(Modifier.padding(4.dp))
                    FilterChip(
                        selected = game == "ssq",
                        onClick = { game = "ssq" },
                        label = { Text("双色球") },
                    )
                }
            }
            when (tab) {
                "draws" -> DrawsScreen(game) { notify(it) }
                "stats" -> StatsScreen(game) { notify(it) }
                "model" -> ModelScreen(game) { notify(it) }
                "scratch" -> ScratchScreen(game) { notify(it) }
                else -> SettingsScreen { notify(it) }
            }
        }
    }

    // 首启提示一次免责声明（各结果页内同样随数据展示）
    LaunchedEffect(Unit) {
        snackbar.showSnackbar("数据来自官方公开渠道；预测仅供参考，不构成投注建议。")
    }
}
