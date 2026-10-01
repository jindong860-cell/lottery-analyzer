package com.luckylab.app.ocr

import kotlin.math.abs
import kotlin.math.sqrt

/**
 * 票种模板与本地识别流水线：与 server/lottery_server/ocr.py 严格镜像。
 * 服务端 profiles.json 可通过 /api/scratch/profiles 拉取后覆盖默认模板。
 */

data class TicketProfile(
    val id: String,
    val name: String,
    val aspectMin: Double,
    val aspectMax: Double,
    val refRgb: Triple<Int, Int, Int>,
    val colorTol: Double,
    /** 奖区相对坐标 [x, y, w, h] ∈ [0,1] */
    val amountRoi: List<Double>,
    /** 金额（元）→ 奖级名 */
    val prizeTable: Map<Int, String>,
)

val DEFAULT_PROFILES: List<TicketProfile> = listOf(
    TicketProfile(
        id = "ggl_default_a", name = "示例票种A（红主色）",
        aspectMin = 0.42, aspectMax = 0.58,
        refRgb = Triple(190, 40, 40), colorTol = 80.0,
        amountRoi = listOf(0.10, 0.62, 0.80, 0.18),
        prizeTable = mapOf(10 to "10元档", 20 to "20元档", 50 to "50元档", 100 to "100元档", 500 to "500元档"),
    ),
    TicketProfile(
        id = "ggl_default_b", name = "示例票种B（黄主色）",
        aspectMin = 0.60, aspectMax = 0.85,
        refRgb = Triple(240, 170, 30), colorTol = 80.0,
        amountRoi = listOf(0.12, 0.55, 0.76, 0.22),
        prizeTable = mapOf(5 to "5元档", 15 to "15元档", 30 to "30元档", 60 to "60元档", 150 to "150元档"),
    ),
)

data class LocalMatch(
    val profile: TicketProfile?,
    val typeConf: Double,
    val reason: String,
    val roiWidth: Int,
    val roiHeight: Int,
    val roiBitmap: android.graphics.Bitmap?,
    val ocrText: String,
    val ocrConf: Double,
    val ocrEngine: String,
    val amounts: List<Int>,
    val predictedRank: String?,
    val predictedAmount: Int?,
    val matchConf: Double,
    val confidence: Double,
    val needsReview: Boolean,
    val reviewReason: String,
)

object TicketProfiles {

    /** 宽高比 ±15% 窗口 + 全图均值色距离打分（与 server ocr.detect_ticket_type 一致）。 */
    fun detect(width: Int, height: Int, meanRgb: Triple<Double, Double, Double>, profiles: List<TicketProfile>): Pair<TicketProfile?, Double> {
        val aspect = width.toDouble() / height
        var best: TicketProfile? = null
        var bestScore = 0.0
        for (p in profiles) {
            val lo = p.aspectMin * 0.85
            val hi = p.aspectMax * 1.15
            if (aspect < lo || aspect > hi) continue
            val d = colorDistance(meanRgb, p.refRgb)
            val score = (1.0 - d / (p.colorTol * sqrt(3.0))).coerceIn(0.0, 1.0)
            if (score > bestScore) {
                bestScore = score
                best = p
            }
        }
        return best to bestScore
    }

    fun colorDistance(a: Triple<Double, Double, Double>, b: Triple<Int, Int, Int>): Double =
        sqrt(
            (a.first - b.first) * (a.first - b.first) +
                (a.second - b.second) * (a.second - b.second) +
                (a.third - b.third) * (a.third - b.third),
        )

    /** 相对 ROI → 像素矩形（收敛到图像边界，最小 8px）。 */
    fun roiRect(amountRoi: List<Double>, width: Int, height: Int): IntArray {
        val x = (amountRoi[0] * width).toInt().coerceIn(0, width - 8)
        val y = (amountRoi[1] * height).toInt().coerceIn(0, height - 8)
        val w = (amountRoi[2] * width).toInt().coerceAtMost(width - x).coerceAtLeast(8)
        val h = (amountRoi[3] * height).toInt().coerceAtMost(height - y).coerceAtLeast(8)
        return intArrayOf(x, y, w, h)
    }

    /** 图片全图平均 RGB。 */
    fun meanRgb(bitmap: android.graphics.Bitmap): Triple<Double, Double, Double> {
        val step = maxOf(1, minOf(bitmap.width, bitmap.height) / 64)
        var r = 0.0; var g = 0.0; var b = 0.0; var n = 0
        var y = 0
        while (y < bitmap.height) {
            var x = 0
            while (x < bitmap.width) {
                val c = bitmap.getPixel(x, y)
                r += android.graphics.Color.red(c)
                g += android.graphics.Color.green(c)
                b += android.graphics.Color.blue(c)
                n++
                x += step
            }
            y += step
        }
        return Triple(r / n, g / n, b / n)
    }

    /** 从 OCR 文本提取金额（阿拉伯数字 + 常见中文数字），去重升序（与 server parse_amounts 一致）。 */
    fun parseAmounts(text: String): List<Int> {
        val out = LinkedHashSet<Int>()
        // 阿拉伯数字（允许「元/￥/¥」前后缀）
        Regex("(\\d{1,4})\\s*元?").findAll(text).forEach { m ->
            val v = m.groupValues[1].toInt()
            if (v > 0) out.add(v)
        }
        // 中文数字（票面常见小额）
        val cn = mapOf(
            "十元" to 10, "廿元" to 20, "五十元" to 50, "百元" to 100,
            "五元" to 5, "十五元" to 15, "三十元" to 30, "六十元" to 60, "一百五十元" to 150,
        )
        cn.forEach { (k, v) -> if (text.contains(k)) out.add(v) }
        return out.toList().sorted()
    }

    /** 模板匹配：唯一命中 conf=1.0；多命中取最大金额 conf=0.5；无命中 0.0。 */
    fun templateMatch(profile: TicketProfile, amounts: List<Int>): Triple<String?, Int?, Double> {
        val hits = amounts.filter { profile.prizeTable.containsKey(it) }
        return when {
            hits.size == 1 -> {
                val a = hits[0]
                Triple(profile.prizeTable[a], a, 1.0)
            }
            hits.size > 1 -> {
                val a = hits.max()
                Triple(profile.prizeTable[a], a, 0.5)
            }
            else -> Triple(null, null, 0.0)
        }
    }

    /** 置信度合成（0.4/0.35/0.25，与服务端一致）。 */
    fun confidence(typeConf: Double, ocrConf: Double, matchConf: Double): Double =
        (0.4 * typeConf + 0.35 * ocrConf + 0.25 * matchConf).let { Math.round(it * 10000.0) / 10000.0 }

    /** 票种概率一致（本地票种检测命中率远高于随机）。 */
    fun agree(a: TicketProfile?, b: TicketProfile?): Boolean =
        (a == null && b == null) || (a != null && b != null && a.id == b.id)

    fun near(x: Double, y: Double, tol: Double = 1e-6): Boolean = abs(x - y) < tol
}
