package com.luckylab.app.data

import com.google.gson.FieldNamingPolicy
import com.google.gson.GsonBuilder
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

/**
 * 与 Web 端共用同一套后端接口（server/lottery_server/http_api.py）。
 * 通过 [ApiClient.setBaseUrl] 在设置页切换服务器地址后重建 Retrofit。
 */
interface LotteryApi {

    @GET("api/health")
    suspend fun health(): HealthDto

    @POST("api/draws/sync")
    suspend fun sync(@Body req: SyncReq): SyncResp

    @GET("api/draws")
    suspend fun draws(
        @Query("game") game: String,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 20,
    ): DrawsPageDto

    @GET("api/draws/synclog")
    suspend fun syncLog(): SyncLogResp

    @GET("api/stats/frequency")
    suspend fun frequency(@Query("game") game: String, @Query("window") window: Int = 0): FreqResp

    @GET("api/stats/omission")
    suspend fun omission(@Query("game") game: String): OmitResp

    @GET("api/stats/trend")
    suspend fun trend(@Query("game") game: String, @Query("last_n") lastN: Int = 30): TrendResp

    @POST("api/model/train")
    suspend fun train(@Body req: TrainReq): TrainResp

    @GET("api/model/runs")
    suspend fun runs(@Query("game") game: String, @Query("limit") limit: Int = 20): RunsResp

    @GET("api/model/runs/{id}")
    suspend fun runDetail(@Path("id") id: Long): RunDetailDto

    @POST("api/model/predict")
    suspend fun predict(@Body req: PredictReq): PredictResp

    @Multipart
    @POST("api/scratch/samples")
    suspend fun uploadSample(
        @Part image: MultipartBody.Part,
        @Part("ticket_type_hint") hint: okhttp3.RequestBody?,
        @Part("device") device: okhttp3.RequestBody?,
        @Part("note") note: okhttp3.RequestBody?,
    ): SampleDto

    @GET("api/scratch/samples")
    suspend fun samples(
        @Query("status") status: String? = null,
        @Query("limit") limit: Int = 50,
    ): SamplesResp

    @POST("api/scratch/samples/{id}/verify")
    suspend fun verify(@Path("id") id: Long, @Body req: VerifyReq): VerifyResp

    @GET("api/scratch/accuracy")
    suspend fun accuracy(): AccuracyResp

    @GET("api/scratch/profiles")
    suspend fun profiles(): ProfilesResp

    @PUT("api/scratch/profiles")
    suspend fun saveProfiles(@Body body: ProfilesResp): ProfilesResp
}

/**
 * Retrofit 单例。个人使用场景：服务器地址可变（本机/局域网 IP），
 * 因此提供 setBaseUrl 重建实例；地址持久化在 SharedPreferences（见 AppGraph）。
 */
object ApiClient {

    @Volatile
    private var current: LotteryApi = build("http://10.0.2.2:8000/")

    fun api(): LotteryApi = current

    /** 切换后端地址（须以 / 结尾）。线程安全：volatile 替换。 */
    fun setBaseUrl(baseUrl: String): LotteryApi {
        val normalized = if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
        val next = build(normalized)
        current = next
        return next
    }

    private fun build(baseUrl: String): LotteryApi {
        val gson = GsonBuilder()
            .setFieldNamingPolicy(FieldNamingPolicy.LOWER_CASE_WITH_UNDERSCORES)
            .create()
        val client = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)   // 训练接口可能较慢
            .writeTimeout(60, TimeUnit.SECONDS)  // 图片上传
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
            .create(LotteryApi::class.java)
    }
}
