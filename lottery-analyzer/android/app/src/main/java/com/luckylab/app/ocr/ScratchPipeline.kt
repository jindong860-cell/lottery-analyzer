package com.luckylab.app.ocr

import android.graphics.Bitmap
import android.net.Uri
import com.google.android.gms.tasks.Task
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * 刮刮乐本地识别流水线（设备端 ML Kit，离线可用）：
 *   拍照/选图 → 票种识别（宽高比+主色）→ ROI 裁剪 → ML Kit OCR → 模板匹配 → 置信度合成。
 *
 * 与服务端的关系：本地识别用于「即时预览」；识别记录的权威版本仍由服务端
 * /api/scratch/samples 落库（服务器无 tesseract 时其记录会标记 needs_review）。
 * 本地预测结果会写入上传的 note 字段（如 "mlkit预测:100元档 conf=0.71"），保证可追溯。
 */
object ScratchPipeline {

    private val recognizer by lazy {
        TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
    }

    private suspend fun recognize(bitmap: Bitmap): Text =
        suspendCancellableCoroutine { cont ->
            val task: Task<Text> = recognizer.process(InputImage.fromBitmap(bitmap, 0))
            task.addOnSuccessListener { if (cont.isActive) cont.resume(it) }
            task.addOnFailureListener { if (cont.isActive) cont.resumeWithException(it) }
            // 注：GMS Task 不支持取消；cont.isActive 守卫保证协程取消后结果被丢弃。
        }

    /**
     * 完整流水线。返回 [LocalMatch]；不做任何服务端交互。
     * @param profiles 票种模板（建议来自 /api/scratch/profiles，缺省用内置示例模板）
     */
    suspend fun run(bitmap: Bitmap, hintId: String?, profiles: List<TicketProfile>): LocalMatch {
        val w = bitmap.width
        val h = bitmap.height

        // 1) 票种识别
        val (candidate, typeConf) = TicketProfiles.detect(w, h, TicketProfiles.meanRgb(bitmap), profiles)
        val profile = when {
            hintId != null -> profiles.firstOrNull { it.id == hintId }
                ?.let { p -> if (candidate != null && candidate.id == p.id) p else p } // 提示优先
            else -> candidate
        }
        val effectiveTypeConf = if (hintId != null && profile != null) 1.0 else typeConf

        if (profile == null) {
            return LocalMatch(
                profile = null, typeConf = typeConf, reason = "票种不匹配任何模板（宽高比/主色不符）",
                roiWidth = 0, roiHeight = 0, roiBitmap = null,
                ocrText = "", ocrConf = 0.0, ocrEngine = "none",
                amounts = emptyList(), predictedRank = null, predictedAmount = null, matchConf = 0.0,
                confidence = TicketProfiles.confidence(typeConf, 0.0, 0.0),
                needsReview = true, reviewReason = "no_ticket_type",
            )
        }

        // 2) ROI 裁剪
        val rect = TicketProfiles.roiRect(profile.amountRoi, w, h)
        val roi = Bitmap.createBitmap(bitmap, rect[0], rect[1], rect[2], rect[3])

        // 3) OCR（ML Kit 中文）
        val text = try {
            recognize(roi).text
        } catch (e: Exception) {
            ""
        }
        // ML Kit 不输出逐词置信度，块级置信度以「识别成功且非空」计 0.85，否则 0
        val ocrConf = if (text.isNotBlank()) 0.85 else 0.0

        // 4) 模板匹配
        val amounts = TicketProfiles.parseAmounts(text)
        val (rank, amount, matchConf) = TicketProfiles.templateMatch(profile, amounts)

        // 5) 置信度合成与人工复核判定（阈值 0.60 与服务端一致）
        val confidence = TicketProfiles.confidence(effectiveTypeConf, ocrConf, matchConf)
        val needsReview: Boolean
        val reviewReason: String
        when {
            text.isBlank() -> { needsReview = true; reviewReason = "ocr_failed" }
            rank == null -> { needsReview = true; reviewReason = "no_template_match" }
            confidence < 0.60 -> { needsReview = true; reviewReason = "low_confidence" }
            else -> { needsReview = false; reviewReason = "" }
        }

        return LocalMatch(
            profile = profile, typeConf = effectiveTypeConf,
            reason = if (hintId != null) "用户指定票种" else "宽高比+主色自动识别",
            roiWidth = rect[2], roiHeight = rect[3], roiBitmap = roi,
            ocrText = text, ocrConf = ocrConf, ocrEngine = "mlkit-chinese",
            amounts = amounts, predictedRank = rank, predictedAmount = amount, matchConf = matchConf,
            confidence = confidence, needsReview = needsReview, reviewReason = reviewReason,
        )
    }

    /** 读取 Uri 为向下采样的 Bitmap（最长边 ≤1600，避免 OOM）。 */
    fun loadBitmap(context: android.content.Context, uri: Uri, maxSide: Int = 1600): Bitmap {
        val opts = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { BitmapFactory_.decode(it, opts) }
        var sample = 1
        var side = maxOf(opts.outWidth, opts.outHeight)
        while (side / 2 >= maxSide) { sample *= 2; side /= 2 }
        val decode = android.graphics.BitmapFactory.Options().apply { inSampleSize = sample }
        val bmp = context.contentResolver.openInputStream(uri)?.use { BitmapFactory_.decode(it, decode) }
            ?: throw IllegalArgumentException("无法读取图片：$uri")
        return bmp
    }

    // 独立命名以避免与 Options 混淆的静态方法引用
    private object BitmapFactory_ {
        fun decode(input: java.io.InputStream, opts: android.graphics.BitmapFactory.Options): Bitmap? =
            android.graphics.BitmapFactory.decodeStream(input, null, opts)
    }

    /** note 字段：本地预测写入服务端样本，保证可追溯。 */
    fun noteOf(m: LocalMatch): String =
        "mlkit预测:${m.predictedRank ?: "无"} conf=${m.confidence} engine=${m.ocrEngine}"
}
