"""官方开奖数据接入（唯一数据来源，不伪造数据）。

数据来源声明（约束：仅使用官方公开接口与页面）：

- 双色球：中国福利彩票发行管理中心官网（www.cwl.gov.cn）“开奖公告”检索接口
    https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=双色球&issueCount=N
  页面入口：https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/
  注意：该接口对请求头敏感，必须携带浏览器 User-Agent 与 Referer，否则可能 403/404。

- 大乐透：中国体育彩票官方 webapi（webapi.sporttery.cn，gameNo=85）
    https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&provinceId=0&pageSize=N&isVerify=1&pageNo=P
  页面入口：https://static.sporttery.cn/drillDown/lottery_history/index.html
  开发期已实测可用；返回 value.list[].lotteryDrawResult 形如 "01 03 05 10 22 03 09"（前5区 + 后2区，空格分隔）。

接口变更/网络不可达时抛出 SourceError 并写入同步日志，绝不使用伪造数据填充数据库。
测试不访问网络：解析函数针对与官方结构一致的“内存夹具”验证（见 tests/test_sources.py）。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from . import config, db

SSQ_PAGE = "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"
SSQ_URL = ("https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
           "?name={name}&issueCount={count}")
DLT_PAGE = "https://static.sporttery.cn/drillDown/lottery_history/index.html"
DLT_URL = ("https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
           "?gameNo=85&provinceId=0&pageSize={size}&isVerify=1&pageNo={page}")

OFFICIAL_SOURCES = {
    "ssq": "中国福利彩票发行管理中心官网 www.cwl.gov.cn（开奖公告接口，页面入口 " + SSQ_PAGE + "）",
    "dlt": "中国体育彩票官方 webapi webapi.sporttery.cn（大乐透 gameNo=85，页面入口 " + DLT_PAGE + "）",
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
       " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
SSQ_HEADERS = {"User-Agent": _UA, "Referer": SSQ_PAGE,
               "Accept": "application/json, text/plain, */*"}
DLT_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*"}


class SourceError(Exception):
    """官方数据源不可用/返回异常。约束：此时不得用任何合成数据顶替。"""


# fetcher 契约：fetcher(url, headers) -> 已解析的 JSON 对象。默认走 urllib；测试注入假实现。
Fetcher = Callable[[str, dict], dict]


def _http_fetch(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            raw = resp.read()
    except Exception as e:  # urllib 异常族统一转译，附来源 URL 便于核对
        raise SourceError(f"请求官方接口失败：{e}（URL: {url}）") from e
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise SourceError(f"官方接口返回非 JSON（URL: {url}）：{e}") from e


# ---------------------------------------------------------------- 行构造与校验

def make_row(game: str, issue: str, draw_date: str, front: list[int], back: list[int]) -> dict:
    """构造并严格校验一期开奖记录；非法数据直接拒绝（宁缺毋假）。"""
    g = config.GAMES[game]
    issue = str(issue).strip()
    draw_date = str(draw_date).strip()[:10]
    front = sorted(int(x) for x in front)
    back = sorted(int(x) for x in back)
    if not issue:
        raise ValueError("期号为空")
    if len(front) != g["front_count"] or len(back) != g["back_count"]:
        raise ValueError(f"号码个数不符：front={len(front)} back={len(back)}")
    if len(set(front)) != len(front) or len(set(back)) != len(back):
        raise ValueError("同期内出现重复号码")
    if any(not (1 <= x <= g["front_max"]) for x in front):
        raise ValueError(f"前区号码越界 {front}")
    if any(not (1 <= x <= g["back_max"]) for x in back):
        raise ValueError(f"后区号码越界 {back}")
    if len(draw_date) != 10 or draw_date[4] != "-" or draw_date[7] != "-":
        raise ValueError(f"开奖日期格式异常 {draw_date}")
    return {"game": game, "issue": issue, "draw_date": draw_date,
            "reds": front, "blues": back, "source": OFFICIAL_SOURCES[game]}


def parse_ssq(payload: dict) -> tuple[list[dict], list[str]]:
    """解析双色球接口返回。结构（官方文档口径）：result.result[]，字段 code/date/red/blue。"""
    data = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        items = data.get("result") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    rows: list[dict] = []
    errors: list[str] = []
    for it in items:
        try:
            reds = [int(x) for x in str(it["red"]).replace("，", ",").split(",") if x.strip()]
            blues = [int(x) for x in str(it["blue"]).replace("，", ",").split(",") if x.strip()]
            rows.append(make_row("ssq", it["code"], it["date"], reds, blues))
        except Exception as e:
            errors.append(f"双色球记录解析失败 {it!r}: {e}")
    return rows, errors


def parse_dlt(payload: dict) -> tuple[list[dict], list[str]]:
    """解析大乐透接口返回（实测结构）：value.list[]，lotteryDrawResult="01 03 05 10 22 03 09"。"""
    items = (payload.get("value") or {}).get("list") or [] if isinstance(payload, dict) else []
    rows: list[dict] = []
    errors: list[str] = []
    for it in items:
        try:
            raw = str(it.get("lotteryDrawResult") or "").replace(",", " ").replace("-", " ").split()
            nums = [int(x) for x in raw]
            if len(nums) < 7:
                raise ValueError(f"号码数量不足：{raw}")
            rows.append(make_row("dlt", it.get("lotteryDrawNum"),
                                 it.get("lotteryDrawTime"), nums[:5], nums[5:7]))
        except Exception as e:
            errors.append(f"大乐透记录解析失败 {it!r}: {e}")
    return rows, errors


# ---------------------------------------------------------------- 拉取与同步

def fetch_official(game: str, limit: int, fetcher: Optional[Fetcher] = None) -> tuple[list[dict], list[str]]:
    """从官方接口拉取最近 limit 期。返回 (rows, errors)。"""
    fetch = fetcher or _http_fetch
    rows: list[dict] = []
    errors: list[str] = []
    if game == "ssq":
        url = SSQ_URL.format(name=urllib.request.quote("双色球"), count=max(1, min(limit, 500)))
        payload = fetch(url, SSQ_HEADERS)
        rows, errors = parse_ssq(payload)
    elif game == "dlt":
        size = max(1, min(limit, 100))
        page = 1
        while len(rows) < limit:
            url = DLT_URL.format(size=size, page=page)
            payload = fetch(url, DLT_HEADERS)
            got, errs = parse_dlt(payload)
            rows.extend(got)
            errors.extend(errs)
            pages_total = ((payload.get("value") or {}).get("pages") or 1) if isinstance(payload, dict) else 1
            if not got or page >= int(pages_total):
                break
            page += 1
        rows = rows[:limit]
    else:
        raise SourceError(f"未知彩种 {game}（可选：{list(config.GAMES)}）")
    if not rows and not errors:
        raise SourceError(f"官方接口返回空数据（{game}），请核对网络与接口：{OFFICIAL_SOURCES[game]}")
    return rows, errors


def sync_official(conn, game: str, mode: str = "incremental", limit: Optional[int] = None,
                  fetcher: Optional[Fetcher] = None) -> dict:
    """增量/全量同步：拉取官方最近数据并按 (game, issue) 幂等 UPSERT。

    incremental：默认拉最近 30 期（足以覆盖未同步的新开奖）；
    full       ：默认拉最近 1000 期（首次建库用）。
    """
    if game not in config.GAMES:
        raise SourceError(f"未知彩种 {game}（可选：{list(config.GAMES)}）")
    if mode not in ("incremental", "full"):
        raise SourceError(f"未知同步模式 {mode}")
    limit = int(limit) if limit else (30 if mode == "incremental" else 1000)
    try:
        rows, errors = fetch_official(game, limit, fetcher=fetcher)
    except SourceError as e:
        db.add_sync_log(conn, game, OFFICIAL_SOURCES[game], ok=False, message=str(e))
        raise
    inserted, updated = db.upsert_draws(conn, rows)
    db.add_sync_log(conn, game, OFFICIAL_SOURCES[game], ok=True,
                    message="同步成功" + ("；部分记录解析失败：" + "；".join(errors) if errors else ""),
                    fetched=len(rows), inserted=inserted, updated=updated)
    return {
        "game": game, "mode": mode, "source": OFFICIAL_SOURCES[game],
        "fetched": len(rows), "inserted": inserted, "updated": updated,
        "errors": errors,
        "total_in_db": db.count_draws(conn, game),
    }
