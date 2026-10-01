package com.luckylab.app.data

import android.content.Context
import com.luckylab.app.data.local.DrawDao
import com.luckylab.app.data.local.DrawEntity
import com.luckylab.app.data.local.LocalDb
import com.luckylab.app.data.local.SampleDao
import com.luckylab.app.data.local.SampleEntity

/**
 * 应用级依赖图：服务器地址持久化 + 本地缓存写入。
 * 刷新缓存统一走 [refreshCaches]：拉取服务端第一页并 REPLACE 入库。
 */
object AppGraph {

    private const val PREFS = "luckylab_prefs"
    private const val KEY_BASE_URL = "base_url"
    const val DEFAULT_BASE_URL = "http://10.0.2.2:8000/"   // 模拟器访问宿主机；真机改局域网 IP

    fun loadBaseUrl(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_BASE_URL, DEFAULT_BASE_URL)!!

    /** 切换后端地址：重建 Retrofit + 持久化。返回是否生效（非空校验）。 */
    fun saveBaseUrl(context: Context, url: String): String {
        val trimmed = url.trim()
        require(trimmed.startsWith("http://") || trimmed.startsWith("https://")) { "地址须以 http:// 或 https:// 开头" }
        val normalized = if (trimmed.endsWith("/")) trimmed else "$trimmed/"
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_BASE_URL, normalized).apply()
        ApiClient.setBaseUrl(normalized)
        return normalized
    }

    /** 启动时调用：让 Retrofit 与持久化的地址一致。 */
    fun init(context: Context) {
        ApiClient.setBaseUrl(loadBaseUrl(context))
    }

    suspend fun refreshDrawCache(context: Context, game: String): Int {
        val page = ApiClient.api().draws(game, page = 1, pageSize = 100)
        val now = System.currentTimeMillis()
        val rows = page.rows.map {
            DrawEntity(
                key = "$game:${it.issue}", game = game, issue = it.issue, drawDate = it.drawDate,
                reds = it.reds.joinToString(","), blues = it.blues.joinToString(","), cachedAt = now,
            )
        }
        db(context).first.putAll(rows)
        return rows.size
    }

    suspend fun refreshSampleCache(context: Context): Int {
        val resp = ApiClient.api().samples(limit = 50)
        val now = System.currentTimeMillis()
        val rows = resp.rows.map {
            SampleEntity(
                id = it.id, ticketType = it.ticketType, predictedRank = it.predictedRank,
                predictedAmount = it.predictedAmount, confidence = it.confidence,
                needsReview = it.needsReview, matchStatus = it.matchStatus, createdAt = it.createdAt,
                cachedAt = now,
            )
        }
        db(context).second.putAll(rows)
        return rows.size
    }

    fun drawDao(context: Context): DrawDao = db(context).first
    fun sampleDao(context: Context): SampleDao = db(context).second

    private fun db(context: Context): Pair<DrawDao, SampleDao> {
        val database = LocalDb.get(context)
        return database.drawDao() to database.sampleDao()
    }
}
