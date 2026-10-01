package com.luckylab.app.data

/**
 * 后端接口 DTO：字段与 server/lottery_server/http_api.py 返回的 JSON 一一对应。
 * snake_case JSON 通过 Gson 完全兼容 Kotlin 小驼峰属性（配套 FieldNamingStrategy 见 Api.kt）。
 */

data class HealthDto(val status: String, val games: List<String>, val version: String)

data class DrawDto(
    val issue: String,
    val drawDate: String,
    val reds: List<Int>,
    val blues: List<Int>,
)

data class DrawsPageDto(
    val game: String,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val rows: List<DrawDto>,
)

data class SyncResp(
    val game: String,
    val mode: String,
    val source: String,
    val fetched: Int,
    val inserted: Int,
    val updated: Int,
    val errors: Int,
    val totalInDb: Int,
)

data class SyncLogRow(
    val id: Long,
    val ts: String,
    val game: String,
    val ok: Boolean,
    val message: String,
    val fetched: Int,
    val inserted: Int,
    val updated: Int,
)

data class FreqItem(val num: Int, val count: Int, val rate: Double?)
data class FreqResp(
    val game: String,
    val gameName: String,
    val window: Int,
    val drawCount: Int,
    val front: List<FreqItem>,
    val back: List<FreqItem>,
)

data class OmitItem(val num: Int, val current: Int, val max: Int, val avg: Double?)
data class OmitResp(
    val game: String,
    val gameName: String,
    val drawCount: Int,
    val front: List<OmitItem>,
    val back: List<OmitItem>,
)

data class TrendRow(val issue: String, val drawDate: String, val reds: List<Int>, val blues: List<Int>)
data class TrendResp(
    val game: String,
    val gameName: String,
    val lastN: Int,
    val frontMax: Int,
    val backMax: Int,
    val rows: List<TrendRow>,
)

data class MetricsDto(val auc: Double?, val logLoss: Double?, val brier: Double?)
data class SimulationDto(
    val topK: Int,
    val draws: Int,
    val avgHits: Double,
    val randomBaselineAvgHits: Double,
    val hitRateAtLeast1: Double,
    val hitDistribution: Map<String, Int>,
)

data class RunDto(
    val id: Long,
    val game: String,
    val gameName: String,
    val createdAt: String,
    val window: Int,
    val testRatio: Double,
    val trainSamples: Int,
    val testSamples: Int,
    val metrics: MetricsDto?,
)

data class WeightsDto(val mean: List<Double>, val std: List<Double>, val w: List<Double>, val b: Double)

/** runs/{id} 返回的 report（服务端保留全部字段，此处只声明客户端需要的键，其余由 Gson 忽略）。 */
data class ReportDto(
    val weights: WeightsDto?,
    val featureNames: List<String>?,
    val window: Int?,
    val featureVersion: String?,
    val modelName: String?,
    val datasetFingerprint: String?,
    val testDrawRange: List<String>?,
    val drawRange: List<String>?,
)

data class RunDetailDto(
    val id: Long,
    val game: String,
    val gameName: String,
    val createdAt: String,
    val window: Int?,
    val testRatio: Double?,
    val trainSamples: Int?,
    val testSamples: Int?,
    val metrics: MetricsDto?,
    val report: ReportDto?,
)

data class TrainResp(
    val runId: Long,
    val game: String,
    val gameName: String,
    val metrics: MetricsDto?,
    val simulation: SimulationDto?,
)

data class RunsResp(val rows: List<RunDto>)
data class SyncLogResp(val rows: List<SyncLogRow>)
data class SamplesResp(val rows: List<SampleDto>)

data class PredictItem(val num: Int, val prob: Double)
data class PredictResp(
    val game: String,
    val gameName: String,
    val basedOnRunId: Long,
    val trainedAt: String,
    val basedOnDraws: Int,
    val latestIssue: String,
    val topK: List<PredictItem>,
    val allProbs: List<PredictItem>,
    val disclaimer: String,
)

data class SampleDto(
    val id: Long,
    val createdAt: String,
    val imageUrl: String?,
    val roiUrl: String?,
    val ticketType: String?,
    val ticketTypeConf: Double?,
    val ocrEngine: String?,
    val ocrText: String?,
    val predictedRank: String?,
    val predictedAmount: Int?,
    val confidence: Double?,
    val needsReview: Boolean,
    val reviewReason: String?,
    val actualRank: String?,
    val actualAmount: Int?,
    val matchStatus: String,
    val verifiedAt: String?,
    val device: String?,
    val note: String?,
)

data class VerifyResp(
    val id: Long,
    val matchStatus: String,
    val actualRank: String?,
    val actualAmount: Int?,
    val predictedRank: String?,
    val predictedAmount: Int?,
    val note: String?,
)

data class AutoVerifiedDto(val total: Int, val match: Int, val mismatch: Int, val accuracy: Double?)
data class TicketTypeAccDto(
    val ticketType: String,
    val judged: Int,
    val match: Int,
    val mismatch: Int,
    val accuracy: Double?,
)

data class AccuracyResp(
    val total: Int,
    val byStatus: Map<String, Int>,
    val autoVerified: AutoVerifiedDto,
    val byTicketType: List<TicketTypeAccDto>,
)

data class ProfileDto(
    val id: String,
    val name: String,
    val aspectMin: Double,
    val aspectMax: Double,
    val refRgb: List<Int>,
    val colorTol: Double,
    val amountRoi: List<Double>,
    val prizeTable: Map<String, String>,
)

data class ProfilesResp(val profiles: List<ProfileDto>)

/** 训练请求体 */
data class TrainReq(val game: String, val seed: Int = 7, val testRatio: Double = 0.2, val window: Int = 30)

/** 同步请求体 */
data class SyncReq(val game: String, val mode: String = "incremental")

/** 预测请求体 */
data class PredictReq(val game: String, val runId: Long? = null, val topK: Int? = null)

/** 验证请求体：两者至少其一 */
data class VerifyReq(val actualRank: String?, val actualAmount: Int?, val note: String? = null)
