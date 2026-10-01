package com.luckylab.app.ml

import kotlin.math.exp
import kotlin.math.ln

/**
 * 纯 Kotlin 模型推理：与 server/lottery_server/model.py 的特征工程/标准化/逻辑回归严格镜像。
 * 权重来自服务端训练产物（report.weights），本模块不做训练，保证两端口径一致。
 *
 * 特征（FEATURE_VERSION=freq_omit_v1，逐号码）：
 *   x1 = 该号在窗口期内的出现次数
 *   x2 = 当前遗漏 / 窗口
 *   x3 = 该号与最近3期同区号码的重合次数 / 3
 *   x4 = 1.0（偏置）
 */
object ModelMath {

    const val FEATURE_VERSION = "freq_omit_v1"

    data class Weights(val mean: List<Double>, val std: List<Double>, val w: List<Double>, val b: Double)

    fun weightsOf(mean: List<Double>, std: List<Double>, w: List<Double>, b: Double): Weights =
        Weights(mean, std, w, b)

    /** 从最近 drawCount 期开奖（时间升序）构造下一期每个前区号码的特征。 */
    fun featuresForNext(
        frontsAsc: List<List<Int>>,
        frontMax: Int,
        window: Int,
    ): Map<Int, List<Double>> {
        val n = frontsAsc.size
        val hist = frontsAsc.takeLast(window)
        val recent3 = frontsAsc.takeLast(3).flatten().toSet()
        val lastSeen = HashMap<Int, Int>()
        frontsAsc.forEachIndexed { t, nums -> nums.forEach { num -> lastSeen[num] = t } }

        return (1..frontMax).associateWith { num ->
            val freq = hist.count { it.contains(num) }
            val ls = lastSeen[num]
            val omit = if (ls == null) n else n - 1 - ls
            val hot3 = if (recent3.contains(num)) 1.0 else 0.0
            listOf(freq.toDouble(), omit / window.toDouble(), hot3 / 3.0, 1.0)
        }
    }

    /** 标准化 + 逻辑回归，返回每个号码的概率（与服务端 predict_proba 一致）。 */
    fun probabilities(model: Weights, features: Map<Int, List<Double>>): Map<Int, Double> =
        features.mapValues { (_, x) ->
            var z = model.b
            for (i in x.indices) {
                val sd = if (model.std[i] == 0.0) 1.0 else model.std[i]
                z += model.w[i] * ((x[i] - model.mean[i]) / sd)
            }
            sigmoid(z)
        }

    /** 取概率最高的前 k 个号码（平手时号码小者优先，与服务端排序一致）。 */
    fun topK(probs: Map<Int, Double>, k: Int): List<Pair<Int, Double>> =
        probs.entries.sortedWith(compareByDescending<Map.Entry<Int, Double>> { it.value }.thenBy { it.key })
            .take(k).map { it.key to it.value }

    private fun sigmoid(z: Double): Double = when {
        z >= 0.0 -> 1.0 / (1.0 + exp(-z))
        else -> {
            val e = exp(z)
            e / (1.0 + e)
        }
    }

    /** 参考：二分类交叉熵（服务端 log_loss 同式），供本地自检。 */
    fun logLoss(p: Double, y: Int): Double = -(y * ln(p.coerceIn(1e-9, 1.0)) + (1 - y) * ln((1 - p).coerceIn(1e-9, 1.0)))
}
