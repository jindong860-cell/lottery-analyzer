"""SQLite 持久层：建表、开奖 UPSERT 去重、样本/模型/同步日志 DAO。

设计要点：
- 单文件本地库（个人使用），启用 WAL 提升读写并发；
- 开奖表以 (game, issue) 为唯一键：重复拉取只更新不新增，天然去重（幂等同步）；
- 刮刮乐样本与验证结果全量持久化（约束：可追溯）；模型运行记录含指纹与完整报告（约束：可复现）。
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    game       TEXT NOT NULL,
    issue      TEXT NOT NULL,
    draw_date  TEXT NOT NULL,
    reds       TEXT NOT NULL,             -- JSON 数组，升序，如 [1,7,12]
    blues      TEXT NOT NULL,             -- JSON 数组，升序
    source     TEXT NOT NULL,             -- 数据来源说明
    fetched_at TEXT NOT NULL,
    UNIQUE (game, issue)
);
CREATE INDEX IF NOT EXISTS idx_draws_game_date ON draws (game, draw_date);

CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    game       TEXT NOT NULL,
    source     TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    message    TEXT NOT NULL,
    fetched    INTEGER NOT NULL DEFAULT 0,
    inserted   INTEGER NOT NULL DEFAULT 0,
    updated    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scratch_samples (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    image_path       TEXT NOT NULL,       -- 相对 data 目录路径
    roi_path         TEXT,                -- ROI 裁剪图相对路径（票种识别失败时为空）
    ticket_type      TEXT,
    ticket_type_conf REAL,
    ocr_engine       TEXT,                -- mlkit / tesseract / unavailable
    ocr_text         TEXT NOT NULL DEFAULT '',
    predicted_rank   TEXT,
    predicted_amount INTEGER,
    confidence       REAL,
    needs_review     INTEGER NOT NULL DEFAULT 1,
    review_reason    TEXT NOT NULL DEFAULT '',
    actual_rank      TEXT,
    actual_amount    INTEGER,
    match_status     TEXT NOT NULL DEFAULT 'pending',  -- pending/match/mismatch/review
    verified_at      TEXT,
    device           TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_samples_status ON scratch_samples (match_status);

CREATE TABLE IF NOT EXISTS model_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    game                TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    feature_version     TEXT NOT NULL,
    seed                INTEGER NOT NULL,
    test_ratio          REAL NOT NULL,
    window              INTEGER NOT NULL,
    train_samples       INTEGER NOT NULL,
    test_samples        INTEGER NOT NULL,
    metrics_json        TEXT NOT NULL,
    report_json         TEXT NOT NULL,
    artifact_path       TEXT,
    dataset_fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_game ON model_runs (game);
"""


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """每个请求/调用独立连接（线程安全），WAL 提升并发。"""
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ---------------------------------------------------------------- 开奖数据

def _row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "game": r["game"],
        "issue": r["issue"],
        "draw_date": r["draw_date"],
        "reds": json.loads(r["reds"]),
        "blues": json.loads(r["blues"]),
        "source": r["source"],
        "fetched_at": r["fetched_at"],
    }


def upsert_draws(conn: sqlite3.Connection, rows: list[dict]) -> tuple[int, int]:
    """按 (game, issue) 幂等写入。返回 (新增数, 更新数)。

    同一期重复拉取时只更新字段，不产生第二行——这是“增量更新 + 去重”的核心。
    完全相同的记录也计一次“更新”（幂等语义，开销可忽略）。
    """
    inserted = updated = 0
    for r in rows:
        cur = conn.execute(
            "SELECT id FROM draws WHERE game=? AND issue=?", (r["game"], r["issue"])
        )
        exist = cur.fetchone()
        if exist is None:
            conn.execute(
                "INSERT INTO draws(game,issue,draw_date,reds,blues,source,fetched_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (r["game"], r["issue"], r["draw_date"],
                 json.dumps(r["reds"]), json.dumps(r["blues"]),
                 r["source"], now()),
            )
            inserted += 1
        else:
            conn.execute(
                "UPDATE draws SET draw_date=?, reds=?, blues=?, source=?, fetched_at=?"
                " WHERE id=?",
                (r["draw_date"], json.dumps(r["reds"]), json.dumps(r["blues"]),
                 r["source"], now(), exist["id"]),
            )
            updated += 1
    conn.commit()
    return inserted, updated


def get_draws_page(conn: sqlite3.Connection, game: str, page: int, page_size: int) -> tuple[list[dict], int]:
    total = conn.execute("SELECT COUNT(*) AS c FROM draws WHERE game=?", (game,)).fetchone()["c"]
    rows = conn.execute(
        "SELECT * FROM draws WHERE game=? ORDER BY draw_date DESC, issue DESC LIMIT ? OFFSET ?",
        (game, page_size, (page - 1) * page_size),
    ).fetchall()
    return [_row_to_dict(r) for r in rows], total


def get_draws_asc(conn: sqlite3.Connection, game: str) -> list[dict]:
    """全量按时间升序（模型/统计使用；个人数据量 ≤ 数千期，全量可接受）。"""
    rows = conn.execute(
        "SELECT * FROM draws WHERE game=? ORDER BY draw_date ASC, issue ASC", (game,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_draws(conn: sqlite3.Connection, game: str) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM draws WHERE game=?", (game,)).fetchone()["c"]


def add_sync_log(conn: sqlite3.Connection, game: str, source: str, ok: bool,
                 message: str, fetched: int = 0, inserted: int = 0, updated: int = 0) -> None:
    conn.execute(
        "INSERT INTO sync_log(ts,game,source,ok,message,fetched,inserted,updated)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (now(), game, source, 1 if ok else 0, message, fetched, inserted, updated),
    )
    conn.commit()


def list_sync_log(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 刮刮乐样本

SAMPLE_FIELDS = ("id", "created_at", "image_path", "roi_path", "ticket_type",
                 "ticket_type_conf", "ocr_engine", "ocr_text", "predicted_rank",
                 "predicted_amount", "confidence", "needs_review", "review_reason",
                 "actual_rank", "actual_amount", "match_status", "verified_at",
                 "device", "note")


def _sample_to_dict(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in SAMPLE_FIELDS}
    d["needs_review"] = bool(d["needs_review"])
    return d


def insert_sample(conn: sqlite3.Connection, d: dict) -> int:
    cur = conn.execute(
        "INSERT INTO scratch_samples(created_at,image_path,roi_path,ticket_type,"
        "ticket_type_conf,ocr_engine,ocr_text,predicted_rank,predicted_amount,"
        "confidence,needs_review,review_reason,actual_rank,actual_amount,"
        "match_status,verified_at,device,note)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.get("created_at", now()), d["image_path"], d.get("roi_path"),
         d.get("ticket_type"), d.get("ticket_type_conf"), d.get("ocr_engine"),
         d.get("ocr_text", ""), d.get("predicted_rank"), d.get("predicted_amount"),
         d.get("confidence"), 1 if d.get("needs_review", True) else 0,
         d.get("review_reason", ""), d.get("actual_rank"), d.get("actual_amount"),
         d.get("match_status", "pending"), d.get("verified_at"),
         d.get("device", ""), d.get("note", "")),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_sample(conn: sqlite3.Connection, sample_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM scratch_samples WHERE id=?", (sample_id,)).fetchone()
    return _sample_to_dict(r) if r else None


def list_samples(conn: sqlite3.Connection, status: Optional[str] = None, limit: int = 100) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM scratch_samples WHERE match_status=? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM scratch_samples ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_sample_to_dict(r) for r in rows]


def set_sample_verification(conn: sqlite3.Connection, sample_id: int,
                            actual_rank: Optional[str], actual_amount: Optional[int],
                            match_status: str, note: Optional[str] = None) -> None:
    conn.execute(
        "UPDATE scratch_samples SET actual_rank=?, actual_amount=?, match_status=?,"
        " verified_at=?, note=CASE WHEN ? IS NULL THEN note ELSE ? END WHERE id=?",
        (actual_rank, actual_amount, match_status, now(), note, note, sample_id),
    )
    conn.commit()


def sample_accuracy(conn: sqlite3.Connection) -> dict:
    """识别准确率统计（约束：验证闭环可量化）。

    auto_verified = 系统给出过奖级预测、且用户已录入实际结果的样本；
    accuracy = match / auto_verified。
    """
    total = conn.execute("SELECT COUNT(*) AS c FROM scratch_samples").fetchone()["c"]
    by_status = {
        r["match_status"]: r["c"]
        for r in conn.execute(
            "SELECT match_status, COUNT(*) AS c FROM scratch_samples GROUP BY match_status"
        ).fetchall()
    }
    auto = conn.execute(
        "SELECT COUNT(*) AS c, SUM(CASE WHEN match_status='match' THEN 1 ELSE 0 END) AS m"
        " FROM scratch_samples WHERE predicted_rank IS NOT NULL"
        " AND match_status IN ('match','mismatch')"
    ).fetchone()
    auto_total = auto["c"] or 0
    auto_match = auto["m"] or 0
    by_type = []
    for r in conn.execute(
        "SELECT COALESCE(ticket_type,'unknown') AS t, COUNT(*) AS c,"
        " SUM(CASE WHEN match_status='match' THEN 1 ELSE 0 END) AS m,"
        " SUM(CASE WHEN match_status='mismatch' THEN 1 ELSE 0 END) AS x"
        " FROM scratch_samples WHERE match_status IN ('match','mismatch')"
        " GROUP BY t ORDER BY c DESC"
    ).fetchall():
        judged = (r["m"] or 0) + (r["x"] or 0)
        by_type.append({
            "ticket_type": r["t"], "judged": judged, "match": r["m"] or 0, "mismatch": r["x"] or 0,
            "accuracy": round((r["m"] or 0) / judged, 4) if judged else None,
        })
    return {
        "total": total,
        "by_status": by_status,
        "auto_verified": {
            "total": auto_total, "match": auto_match, "mismatch": auto_total - auto_match,
            "accuracy": round(auto_match / auto_total, 4) if auto_total else None,
        },
        "by_ticket_type": by_type,
    }


# ---------------------------------------------------------------- 模型运行

def insert_model_run(conn: sqlite3.Connection, d: dict) -> int:
    cur = conn.execute(
        "INSERT INTO model_runs(created_at,game,model_name,feature_version,seed,"
        "test_ratio,window,train_samples,test_samples,metrics_json,report_json,"
        "artifact_path,dataset_fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d["created_at"], d["game"], d["model_name"], d["feature_version"], d["seed"],
         d["test_ratio"], d["window"], d["train_samples"], d["test_samples"],
         json.dumps(d["metrics"]), json.dumps(d["report"]), d.get("artifact_path"),
         d["dataset_fingerprint"]),
    )
    conn.commit()
    return int(cur.lastrowid)


def finalize_model_run(conn: sqlite3.Connection, run_id: int,
                       report: dict, artifact_path: str) -> None:
    """回填含 run_id 的完整报告与 artifact 路径（insert 时 run_id 尚未生成）。"""
    conn.execute(
        "UPDATE model_runs SET report_json=?, artifact_path=? WHERE id=?",
        (json.dumps(report, ensure_ascii=False), artifact_path, run_id),
    )
    conn.commit()


def get_model_run(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM model_runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["metrics"] = json.loads(d["metrics_json"])
    d["report"] = json.loads(d["report_json"])
    return d


def list_model_runs(conn: sqlite3.Connection, game: Optional[str] = None, limit: int = 50) -> list[dict]:
    if game:
        rows = conn.execute(
            "SELECT * FROM model_runs WHERE game=? ORDER BY id DESC LIMIT ?", (game, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM model_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["metrics"] = json.loads(d["metrics_json"])
        out.append(d)
    return out


def latest_model_run(conn: sqlite3.Connection, game: str) -> Optional[dict]:
    r = conn.execute(
        "SELECT * FROM model_runs WHERE game=? ORDER BY id DESC LIMIT 1", (game,)
    ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["metrics"] = json.loads(d["metrics_json"])
    d["report"] = json.loads(d["report_json"])
    return d
