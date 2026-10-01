"""模型训练与回测：numpy 自实现逻辑回归 + 时间序切分回测（可复现）。

诚实性说明（约束：模型与回测结论须附数据依据并注明随机性）：
- 彩票开奖为独立随机事件，任何基于历史数据的模型理论上都无法超越随机基线。
  本模块的价值在于把“方法论”完整、可复现地落地：特征工程 → 时间序切分 → 训练 →
  回测指标（AUC/LogLoss/Brier）→ Top-K 命中模拟 vs 随机基线对照。
- 可复现设计：全批量梯度下降 + 零初始化，算法本身无任何随机成分；
  seed 仍记录在报告中作为审计字段；数据集指纹（sha256）锁定训练数据范围；
  每次训练落库完整报告与权重（weights），可离线复算。
"""
from __future__ import annotations

import hashlib
import json
import platform
from typing import Optional

import numpy as np

from . import config, db

FEATURE_VERSION = "freq_omit_v1"
MODEL_NAME = "logreg_l2_gd"

FEATURE_NAMES = ["freq_window", "omit_norm", "hot3", "bias"]

DISCLAIMER = ("彩票开奖为独立随机事件，历史统计与模型回测不改变未来开奖的随机性；"
              "预测结果仅供方法学习与数据参考，不构成投注建议。")

METHOD_NOTE = {
    "features": {
        "freq_window": "目标期之前 window 期内该号码出现次数 / window",
        "omit_norm": "目标期之前的当前遗漏期数 / window（从未开出记 window）",
        "hot3": "目标期之前 3 期内该号码出现次数 / 3",
        "bias": "常数 1（截距）",
    },
    "split": "按开奖时间升序排列后，取时间上最后 test_ratio 比例的期数作为测试集（时间序切分，不做随机打散，避免未来信息泄漏）",
    "model": "逻辑回归，L2 正则，全批量梯度下降 300 轮，学习率 0.5，零初始化（无随机成分，结果确定）",
    "metrics": "AUC（含并列的平均秩法）、LogLoss、Brier 分数；均为测试集上的二分类指标（样本=期×号码）",
    "simulation": "对测试集每期：按模型概率取前 front_count 个号码，统计每期命中个数；"
                  "随机基线期望 E = top_k × front_count / front_max（超几何分布均值）；"
                  "同时给出命中率(≥1个)与命中分布",
}


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def fit_logistic(X: list[list[float]], y: list[int], l2: float = 1e-4,
                 lr: float = 0.5, epochs: int = 300, seed: int = 7) -> dict:
    """训练逻辑回归，返回可 JSON 序列化的权重（含标准化参数）。确定性：两次调用结果逐位一致。"""
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    mean = Xa.mean(axis=0)
    std = Xa.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    Xs = (Xa - mean) / std
    m, d = Xs.shape
    w = np.zeros(d)
    b = 0.0
    _ = seed  # 当前算法无随机成分；seed 仅作为审计字段记录于报告
    for _ in range(epochs):
        p = _sigmoid(Xs @ w + b)
        gw = Xs.T @ (p - ya) / m + l2 * w
        gb = float((p - ya).mean())
        w -= lr * gw
        b -= lr * gb
    return {"mean": [round(v, 8) for v in mean.tolist()],
            "std": [round(v, 8) for v in std.tolist()],
            "w": [round(v, 8) for v in w.tolist()],
            "b": round(b, 8)}


def predict_proba(model: dict, X: list[list[float]]) -> np.ndarray:
    Xa = np.asarray(X, dtype=float)
    Xs = (Xa - np.asarray(model["mean"])) / np.asarray(model["std"])
    return _sigmoid(Xs @ np.asarray(model["w"]) + model["b"])


# ---------------------------------------------------------------- 指标

def _rankdata(p: np.ndarray) -> np.ndarray:
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sorted_p = p[order]
    i = 0
    r = 1
    while i < len(p):
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        avg = r + (j - i) / 2.0
        ranks[order[i:j + 1]] = avg
        r += (j - i + 1)
        i = j + 1
    return ranks


def auc(y: list[int], p: np.ndarray) -> Optional[float]:
    yv = np.asarray(y, dtype=int)
    pv = np.asarray(p, dtype=float)
    n_pos = int(yv.sum())
    n_neg = len(yv) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = _rankdata(pv)
    return float((ranks[yv == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def logloss(y: list[int], p: np.ndarray) -> float:
    yv = np.asarray(y, dtype=float)
    pv = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return float(-(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)).mean())


def brier(y: list[int], p: np.ndarray) -> float:
    yv = np.asarray(y, dtype=float)
    return float(((np.asarray(p, dtype=float) - yv) ** 2).mean())


def metrics_of(y: list[int], p: np.ndarray) -> dict:
    a = auc(y, p)
    return {"auc": round(a, 4) if a is not None else None,
            "log_loss": round(logloss(y, p), 4),
            "brier": round(brier(y, p), 4)}


# ---------------------------------------------------------------- 特征工程

def build_dataset(conn, game: str, window: int = 30) -> tuple[list[list[float]], list[int], list[int], list[str]]:
    """样本 = （期, 号码）对。

    对每个目标期 t（t 从 window 起）：用 draws[:t] 的历史为前区每个号码 k 构造特征，
    标签 = k 是否在 draws[t] 前区开出。返回 (X, y, meta(目标期索引), feature_names)。
    """
    if game not in config.GAMES:
        raise ValueError(f"未知彩种 {game}")
    g = config.GAMES[game]
    draws = db.get_draws_asc(conn, game)
    n = len(draws)
    min_draws = window + 10
    if n < min_draws:
        raise ValueError(f"历史数据不足：库内仅 {n} 期，训练/回测至少需要 {min_draws} 期（请先同步开奖数据）")
    sets = [set(d["reds"]) for d in draws]

    X: list[list[float]] = []
    y: list[int] = []
    meta: list[int] = []
    last_seen: dict[int, int] = {}
    for i in range(window):
        for k in sets[i]:
            last_seen[k] = i
    for t in range(window, n):
        recent = sets[t - window:t]
        hot = sets[max(0, t - 3):t]
        for k in range(1, g["front_max"] + 1):
            freq = sum(1 for s in recent if k in s) / float(window)
            li = last_seen.get(k, -1)
            omit = (t - 1 - li) if li >= 0 else t
            hot3 = sum(1 for s in hot if k in s) / 3.0
            X.append([freq, omit / float(window), hot3, 1.0])
            y.append(1 if k in sets[t] else 0)
            meta.append(t)
        # 更新 last_seen 使其在下一轮代表“t 及之前”的最近一次出现
        for k in sets[t]:
            last_seen[k] = t
    return X, y, meta, FEATURE_NAMES


def _fingerprint(draws: list[dict]) -> str:
    canonical = json.dumps([[d["issue"], d["draw_date"], d["reds"], d["blues"]] for d in draws],
                           ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 训练 + 回测

def train_and_backtest(conn, game: str, seed: int = 7, test_ratio: float = 0.2,
                       window: int = 30) -> dict:
    """完整训练+回测，报告落库并写出 artifact JSON。相同参数重复执行指标完全一致（可复现）。"""
    g = config.GAMES[game]
    if not (0.05 <= test_ratio <= 0.5):
        raise ValueError("test_ratio 须在 [0.05, 0.5]")
    if not (5 <= window <= 200):
        raise ValueError("window 须在 [5, 200]")
    X, y, meta, names = build_dataset(conn, game, window)
    all_draws = db.get_draws_asc(conn, game)
    n = len(all_draws)

    test_draw_count = max(3, int(round((n - window) * test_ratio)))
    split_value = n - test_draw_count  # 目标期索引 >= split_value 的样本进入测试集
    train_idx = [i for i, t in enumerate(meta) if t < split_value]
    test_idx = [i for i, t in enumerate(meta) if t >= split_value]

    model = fit_logistic([X[i] for i in train_idx], [y[i] for i in train_idx], seed=seed)
    p_test = predict_proba(model, [X[i] for i in test_idx])
    y_test = [y[i] for i in test_idx]
    metrics = metrics_of(y_test, p_test)

    # Top-K 命中模拟 vs 随机基线
    top_k = g["front_count"]
    test_ts = sorted(set(t for t in meta if t >= split_value))
    p_by_t: dict[int, list[float]] = {t: [] for t in test_ts}
    for i, t in enumerate(meta):
        if t >= split_value:
            p_by_t[t].append(float(p_test[i]))
    hits_each = []
    for t in test_ts:
        scores = p_by_t[t]  # 按号码 1..front_max 顺序
        picks = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        actual = set(all_draws[t]["reds"])
        hits_each.append(sum(1 for i in picks if (i + 1) in actual))
    baseline = top_k * g["front_count"] / g["front_max"]  # 超几何分布均值
    hit_distribution = {str(k): hits_each.count(k) for k in range(0, top_k + 1)}
    simulation = {
        "top_k": top_k,
        "draws": len(hits_each),
        "avg_hits": round(sum(hits_each) / len(hits_each), 4) if hits_each else None,
        "random_baseline_avg_hits": round(baseline, 4),
        "hit_rate_at_least_1": round(sum(1 for h in hits_each if h >= 1) / len(hits_each), 4) if hits_each else None,
        "hit_distribution": hit_distribution,
        "note": "随机基线为理论期望（超几何均值），非模拟抽样；若 avg_hits ≈ baseline 则与“开奖随机”一致。",
    }

    fingerprint = _fingerprint(all_draws)
    created_at = db.now()
    report = {
        "run_id": None,  # 落库后回填
        "game": game, "game_name": g["name"],
        "model_name": MODEL_NAME, "feature_version": FEATURE_VERSION,
        "seed": int(seed), "test_ratio": float(test_ratio), "window": int(window),
        "feature_names": names,
        "train_samples": len(train_idx), "test_samples": len(test_idx),
        "total_draws": n, "train_draws": split_value, "test_draws": len(test_ts),
        "draw_range": [all_draws[0]["issue"], all_draws[-1]["issue"]],
        "test_draw_range": [all_draws[test_ts[0]]["issue"], all_draws[test_ts[-1]]["issue"]] if test_ts else None,
        "metrics": metrics,
        "simulation": simulation,
        "dataset_fingerprint": fingerprint,
        "method": METHOD_NOTE,
        "lib": {"python": platform.python_version(), "numpy": np.__version__},
        "disclaimer": DISCLAIMER,
        "weights": model,
        "created_at": created_at,
    }
    run_id = db.insert_model_run(conn, {
        "created_at": created_at, "game": game, "model_name": MODEL_NAME,
        "feature_version": FEATURE_VERSION, "seed": int(seed),
        "test_ratio": float(test_ratio), "window": int(window),
        "train_samples": len(train_idx), "test_samples": len(test_idx),
        "metrics": metrics, "report": report, "dataset_fingerprint": fingerprint,
    })
    report["run_id"] = run_id
    artifact_path = f"models/run_{run_id}.json"
    with open(__import__("os").path.join(config.MODEL_DIR, f"run_{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    db.finalize_model_run(conn, run_id, report, artifact_path)
    return report


def predict_next(conn, game: str, run_id: Optional[int] = None, top_k: Optional[int] = None) -> dict:
    """基于已训练运行对下一期做 Top-K 参考（附免责声明；仅供参考，不构成投注建议）。"""
    g = config.GAMES[game]
    run = db.get_model_run(conn, run_id) if run_id else db.latest_model_run(conn, game)
    if run is None or run["game"] != game:
        raise ValueError(f"彩种 {game} 尚无可用模型运行，请先调用 POST /api/model/train")
    weights = run["report"]["weights"]
    draws = db.get_draws_asc(conn, game)
    X, _, _, _ = build_features_for_next(draws, game, int(run["window"]))
    probs = predict_proba(weights, X)
    k = int(top_k) if top_k else g["front_count"]
    order = sorted(range(len(probs)), key=lambda i: -probs[i])[:k]
    return {
        "game": game, "game_name": g["name"],
        "based_on_run_id": run["id"], "trained_at": run["created_at"],
        "based_on_draws": len(draws), "latest_issue": draws[-1]["issue"],
        "top_k": [{"num": i + 1, "prob": round(float(probs[i]), 4)} for i in order],
        "all_probs": [{"num": i + 1, "prob": round(float(p), 4)} for i, p in enumerate(probs)],
        "disclaimer": DISCLAIMER,
    }


def build_features_for_next(draws: list[dict], game: str, window: int) -> tuple[list[list[float]], list[int], list[int], list[str]]:
    """对“下一期”（t = len(draws)）构造特征行，顺序为号码 1..front_max。"""
    g = config.GAMES[game]
    sets = [set(d["reds"]) for d in draws]
    n = len(draws)
    if n < window:
        raise ValueError(f"历史数据不足：{n} 期 < window {window}")
    last_seen: dict[int, int] = {}
    for i, s in enumerate(sets):
        for k in s:
            last_seen[k] = i
    t = n
    recent = sets[t - window:t]
    hot = sets[max(0, t - 3):t]
    X = []
    for k in range(1, g["front_max"] + 1):
        freq = sum(1 for s in recent if k in s) / float(window)
        li = last_seen.get(k, -1)
        omit = (t - 1 - li) if li >= 0 else t
        hot3 = sum(1 for s in hot if k in s) / 3.0
        X.append([freq, omit / float(window), hot3, 1.0])
    return X, [], [], FEATURE_NAMES
