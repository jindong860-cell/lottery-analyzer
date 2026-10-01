package com.luckylab.app.data.local

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

/**
 * Room 本地缓存：仅缓存「开奖列表」与「刮刮乐样本」，真源始终是服务端 SQLite。
 * 目的：弱网/离线时仍可查看最近数据；不做双向写（避免数据分叉）。
 */

@Entity(tableName = "draws")
data class DrawEntity(
    @PrimaryKey val key: String,          // "{game}:{issue}" 复合唯一
    val game: String,
    val issue: String,
    val drawDate: String,
    val reds: String,                     // 逗号分隔
    val blues: String,
    val cachedAt: Long,
)

@Entity(tableName = "samples")
data class SampleEntity(
    @PrimaryKey val id: Long,
    val ticketType: String?,
    val predictedRank: String?,
    val predictedAmount: Int?,
    val confidence: Double?,
    val needsReview: Boolean,
    val matchStatus: String,
    val createdAt: String,
    val cachedAt: Long,
)

@Dao
interface DrawDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAll(rows: List<DrawEntity>)

    @Query("SELECT * FROM draws WHERE game = :game ORDER BY issue DESC LIMIT :limit")
    fun observe(game: String, limit: Int = 100): Flow<List<DrawEntity>>

    @Query("SELECT COUNT(*) FROM draws WHERE game = :game")
    suspend fun count(game: String): Int
}

@Dao
interface SampleDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAll(rows: List<SampleEntity>)

    @Query("SELECT * FROM samples ORDER BY id DESC LIMIT :limit")
    fun observe(limit: Int = 50): Flow<List<SampleEntity>>
}

@Database(entities = [DrawEntity::class, SampleEntity::class], version = 1, exportSchema = false)
abstract class LocalDb : RoomDatabase() {
    abstract fun drawDao(): DrawDao
    abstract fun sampleDao(): SampleDao

    companion object {
        @Volatile private var instance: LocalDb? = null

        fun get(context: Context): LocalDb = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, LocalDb::class.java, "luckylab.db")
                .fallbackToDestructiveMigration()
                .build()
                .also { instance = it }
        }
    }
}
