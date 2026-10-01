"""统计分析：频率、遗漏、走势。每项计算方法在函数 docstring 给出（约束：统计结果附计算方法说明）。"""
from __future__ import annotations

from . import config, db


def frequency(conn, game: str, window: int = 0) -> dict:
    """频率统计。

    计算方法：取最近 window 期（window=0 表示全部入库期数），
    某号码频率 count = 该号码在统计区间内的出现期数；
    rate = count / draw_count（理论期望 = 出现个数/号码总数，如双色球红球 6/33≈0.1818）。
    """
    if game not in config.GAMES:
        raise ValueError(f"未知彩种 {game}")
    g = config.GAMES[game]
    draws = db.get_draws_asc(conn, game)
    if window and int(window) > 0:
        draws = draws[-int(window):]
    n = len(draws)
    fc = {k: 0 for k in range(1, g["front_max"] + 1)}
    bc = {k: 0 for k in range(1, g["back_max"] + 1)}
    for d in draws:
        for x in d["reds"]:
            fc[x] += 1
        for x in d["blues"]:
            bc[x] += 1
    front = [{"num": k, "count": fc[k], "rate": round(fc[k] / n, 4) if n else None}
             for k in range(1, g["front_max"] + 1)]
    back = [{"num": k, "count": bc[k], "rate": round(bc[k] / n, 4) if n else None}
            for k in range(1, g["back_max"] + 1)]
    return {"game": game, "game_name": g["name"], "window": int(window or 0),
            "draw_count": n, "front": front, "back": back}


def omission(conn, game: str) -> dict:
    """遗漏统计。

    定义（期序按时间升序，0 起）：
    - current（当前遗漏）：自最新一期起该号码连续未开出的期数；最新一期开出则为 0；从未开出则=总期数。
    - max（历史最大遗漏）：任意两次开出之间间隔期数的最大值，含首段（从库内最早一期到首次开出前的期数）与尾段（=current）。
    - avg（平均遗漏）：首段与各间隔期数的算术平均（不含进行中的尾段），保留 2 位；从未开出为 None。
    """
    if game not in config.GAMES:
        raise ValueError(f"未知彩种 {game}")
    g = config.GAMES[game]
    draws = db.get_draws_asc(conn, game)
    n = len(draws)
    front_sets = [set(d["reds"]) for d in draws]
    back_sets = [set(d["blues"]) for d in draws]

    def compute(sets: list[set], max_num: int) -> list[dict]:
        out = []
        for k in range(1, max_num + 1):
            pos = [i for i, s in enumerate(sets) if k in s]
            if not pos:
                out.append({"num": k, "current": n, "max": n, "avg": None})
                continue
            gaps = [pos[0]] + [pos[i] - pos[i - 1] - 1 for i in range(1, len(pos))]
            current = n - 1 - pos[-1]
            out.append({
                "num": k,
                "current": current,
                "max": max(gaps + [current]),
                "avg": round(sum(gaps) / len(gaps), 2),
            })
        return out

    return {"game": game, "game_name": g["name"], "draw_count": n,
            "front": compute(front_sets, g["front_max"]),
            "back": compute(back_sets, g["back_max"])}


def trend(conn, game: str, last_n: int = 30) -> dict:
    """走势：最近 last_n 期开奖记录，时间倒序（最新在前），供走势表/网格渲染。"""
    if game not in config.GAMES:
        raise ValueError(f"未知彩种 {game}")
    g = config.GAMES[game]
    draws = db.get_draws_asc(conn, game)[-int(last_n):]
    draws.reverse()
    return {"game": game, "game_name": g["name"], "last_n": int(last_n),
            "front_max": g["front_max"], "back_max": g["back_max"],
            "rows": [{"issue": d["issue"], "draw_date": d["draw_date"],
                      "reds": d["reds"], "blues": d["blues"]} for d in draws]}
