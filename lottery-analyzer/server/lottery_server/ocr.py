"""刮刮乐识别管线：票种识别 → ROI 裁剪 → OCR（服务端可选）→ 模板匹配 → 置信度与人工复核。

诚实性设计（约束：置信度不足须提示人工复核）：
- 票种模板（DEFAULT_PROFILES）为初始预设，票面样式因地区/批次而异，必须用真实票据校准后
  才能提高识别率；confidence 低于 config.CONFIDENCE_THRESHOLD(0.60) 一律标记 needs_review。
- 服务端 OCR 依赖 pytesseract + Tesseract 可执行文件（中文简体语言包）；二者任一缺失时
  OCR 环节降级为“unavailable”，样本照常入库并标记人工复核（移动端由 ML Kit 承担 OCR）。
"""
from __future__ import annotations

import os
import re
import shutil
from typing import Optional

from PIL import Image

from . import config, db


class OcrUnavailable(Exception):
    """服务端 OCR 组件缺失。"""


class TicketProfile:
    """一种刮刮乐票种的模板描述。amount_roi 为相对坐标 [x, y, w, h]（0–1）。"""

    def __init__(self, pid: str, name: str, aspect_min: float, aspect_max: float,
                 ref_rgb: tuple, color_tol: int, amount_roi: list,
                 prize_table: dict):
        self.id = pid
        self.name = name
        self.aspect_min = aspect_min
        self.aspect_max = aspect_max
        self.ref_rgb = tuple(int(c) for c in ref_rgb)
        self.color_tol = int(color_tol)
        self.amount_roi = [float(v) for v in amount_roi]
        self.prize_table = {str(k): v for k, v in prize_table.items()}

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "aspect_min": self.aspect_min,
                "aspect_max": self.aspect_max, "ref_rgb": list(self.ref_rgb),
                "color_tol": self.color_tol, "amount_roi": self.amount_roi,
                "prize_table": self.prize_table}

    @classmethod
    def from_dict(cls, d: dict) -> "TicketProfile":
        return cls(d["id"], d["name"], d["aspect_min"], d["aspect_max"],
                   d["ref_rgb"], d["color_tol"], d["amount_roi"], d["prize_table"])


# 初始预设：示例校准值。实际使用前请用真实票据照片核对宽高比/主色/奖区位置并保存覆盖。
DEFAULT_PROFILES = [
    TicketProfile("ggl_default_a", "示例票种A（红底）",
                  0.42, 0.58, (190, 40, 40), 80,
                  [0.10, 0.62, 0.80, 0.18],
                  {"10": "10元档", "20": "20元档", "50": "50元档",
                   "100": "100元档", "500": "500元档"}),
    TicketProfile("ggl_default_b", "示例票种B（黄底）",
                  0.60, 0.85, (240, 170, 30), 80,
                  [0.12, 0.55, 0.76, 0.22],
                  {"5": "5元档", "15": "15元档", "30": "30元档",
                   "60": "60元档", "150": "150元档"}),
]


def load_profiles() -> list[TicketProfile]:
    """优先读 config.PROFILES_PATH（用户校准后的票种库），缺失/损坏时回退默认预设。"""
    if os.path.exists(config.PROFILES_PATH):
        try:
            import json
            with open(config.PROFILES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [TicketProfile.from_dict(d) for d in data.get("profiles", [])]
        except Exception:
            pass
    return list(DEFAULT_PROFILES)


def save_profiles(profiles: list[TicketProfile]) -> None:
    import json
    with open(config.PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump({"profiles": [p.to_dict() for p in profiles]}, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 票种识别 / ROI

def detect_ticket_type(img: Image.Image, profiles: list[TicketProfile]) -> tuple[Optional[TicketProfile], float, str]:
    """票种识别：宽高比窗口（±15%）+ 整图均值色与模板主色的欧氏距离。

    返回 (profile|None, confidence 0–1, reason)。识别失败返回 (None, 0.0, 原因)。
    """
    w, h = img.size
    if h <= 0:
        return None, 0.0, "图片尺寸异常"
    aspect = w / float(h)
    small = img.convert("RGB").resize((16, 16))
    px = list(small.getdata())
    mean_rgb = tuple(sum(c[i] for c in px) / len(px) for i in range(3))

    best: Optional[TicketProfile] = None
    best_score = 0.0
    best_reason = "无匹配票种（可编辑 profiles.json 校准）"
    for p in profiles:
        lo, hi = p.aspect_min * 0.85, p.aspect_max * 1.15
        if not (lo <= aspect <= hi):
            best_reason = f"宽高比 {aspect:.2f} 不在候选票种窗口内"
            continue
        dist = sum((mean_rgb[i] - p.ref_rgb[i]) ** 2 for i in range(3)) ** 0.5
        tol = max(p.color_tol, 1)
        score = max(0.0, 1.0 - dist / (tol * 2.236))  # 2.236=√5：三通道各差 tol 时的归一
        if score > best_score:
            best_score, best = score, p
    if best is None:
        return None, 0.0, best_reason
    return best, round(best_score, 4), "宽高比与主色匹配"


def crop_roi(img: Image.Image, profile: TicketProfile) -> Image.Image:
    """按票种模板的相对 ROI 裁出奖级区域。"""
    w, h = img.size
    x, y, rw, rh = profile.amount_roi
    box = (int(x * w), int(y * h), min(w, int((x + rw) * w)), min(h, int((y + rh) * h)))
    return img.crop(box)


# ---------------------------------------------------------------- 服务端 OCR（可选组件）

def server_ocr_available() -> tuple[bool, str]:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False, "未安装 pytesseract（服务端 OCR 降级，上传样本将标记人工复核；移动端请使用 ML Kit）"
    if shutil.which("tesseract") is None:
        return False, "未找到 tesseract 可执行文件（需安装并加入 PATH，且含 chi_sim 语言包）"
    return True, "tesseract"


def server_ocr(roi: Image.Image) -> tuple[str, float, str]:
    """对 ROI 图做 OCR。返回 (text, 平均置信度 0–1, engine)。组件缺失抛 OcrUnavailable。"""
    ok, why = server_ocr_available()
    if not ok:
        raise OcrUnavailable(why)
    import pytesseract
    from pytesseract import Output
    data = pytesseract.image_to_data(roi, lang="chi_sim+eng",
                                     config="--psm 6", output_type=Output.DICT)
    words = []
    confs = []
    for txt, conf in zip(data["text"], data["conf"]):
        t = (txt or "").strip()
        try:
            c = float(conf)
        except Exception:
            c = -1.0
        if t and c >= 0:
            words.append(t)
            confs.append(c / 100.0)
    text = " ".join(words)
    conf = round(sum(confs) / len(confs), 4) if confs else 0.0
    return text, conf, "tesseract"


# ---------------------------------------------------------------- 金额解析 / 模板匹配

_NUM_MAP = {"〇": "0", "零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
            "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
            "壹": "1", "贰": "2", "叁": "3", "肆": "4", "伍": "5", "陆": "6",
            "柒": "7", "捌": "8", "玖": "9", "拾": "10", "佰": "100", "仟": "1000"}


def parse_amounts(text: str) -> list[dict]:
    """从 OCR 文本提取金额候选。返回 [{amount:int, raw:str}]，按出现顺序。

    规则：阿拉伯数字+可选“元/¥”后缀（如 “100元”“¥30”）；同时把中文数字逐字
    映射后重扫一遍（覆盖“拾元”“伍拾”等简单写法；复杂文写不保证，属模板校准范畴）。
    """
    out: list[dict] = []
    for m in re.finditer(r"[¥￥]?\s*(\d{1,7})\s*元?", text or ""):
        out.append({"amount": int(m.group(1)), "raw": m.group(0).strip()})
    if text:
        buf = "".join(_NUM_MAP.get(ch, ch if ch.isdigit() else " ") for ch in text)
        for m in re.finditer(r"\d{1,7}", buf):
            if not any(o["amount"] == int(m.group(0)) for o in out):
                out.append({"amount": int(m.group(0)), "raw": m.group(0)})
    return out


def template_match(profile: TicketProfile, amounts: list[dict]) -> tuple[Optional[str], Optional[int], float]:
    """模板匹配：OCR 金额与票种奖级表求交。返回 (rank|None, amount|None, confidence)。

    - 命中唯一奖级：conf=1.0；命中多个不同奖级：取金额最大者，conf=0.5（需人工复核把关）；
    - 无命中：conf=0.0。
    """
    hits: dict[int, str] = {}
    for a in amounts:
        rank = profile.prize_table.get(str(a["amount"]))
        if rank is not None:
            hits[int(a["amount"])] = rank
    if not hits:
        return None, None, 0.0
    if len(hits) == 1:
        amount = next(iter(hits))
        return hits[amount], amount, 1.0
    amount = max(hits)
    return hits[amount], amount, 0.5


# ---------------------------------------------------------------- 上传处理主流程

def process_upload(conn, image_bytes: bytes, filename: str,
                   hint: Optional[str], device: str, note: str) -> dict:
    """上传 → 保存原图 → 票种识别 → ROI → OCR → 模板匹配 → 入库。

    返回样本 dict（附 image_url / roi_url，指向 /media/ 静态路由）。
    confidence = 0.4×票种置信 + 0.35×OCR置信 + 0.25×模板匹配置信（加权可解释）。
    """
    profiles = load_profiles()
    os.makedirs(config.IMAGE_DIR, exist_ok=True)
    os.makedirs(config.ROI_DIR, exist_ok=True)

    try:
        img = Image.open(__import__("io").BytesIO(image_bytes))
        img.load()
    except Exception as e:
        raise ValueError(f"无法解析图片：{e}")

    base = db.now().replace(":", "").replace("-", "")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "upload.jpg")[-60:]
    image_name = f"{base}_{safe}"
    image_path = os.path.join(config.IMAGE_DIR, image_name)
    img.save(image_path)

    profile, type_conf, type_reason = detect_ticket_type(img, profiles)
    if hint:
        hinted = next((p for p in profiles if p.id == hint), None)
        if hinted is not None:
            profile, type_conf, type_reason = hinted, 1.0, "用户指定票种"

    reasons: list[str] = []
    roi_path: Optional[str] = None
    roi_url: Optional[str] = None
    ocr_text, ocr_conf, ocr_engine = "", 0.0, "unavailable"
    rank = amount = None
    match_conf = 0.0

    if profile is None:
        reasons.append(f"票种识别失败：{type_reason}")
    else:
        roi = crop_roi(img, profile)
        roi_name = f"{base}_roi.png"
        roi_path = os.path.join(config.ROI_DIR, roi_name)
        roi.save(roi_path)
        try:
            ocr_text, ocr_conf, ocr_engine = server_ocr(roi)
        except OcrUnavailable as e:
            reasons.append(f"服务端OCR不可用：{e}")
        if ocr_text:
            amounts = parse_amounts(ocr_text)
            rank, amount, match_conf = template_match(profile, amounts)
            if rank is None:
                reasons.append("OCR未匹配到奖级表金额")

    confidence = round(0.4 * type_conf + 0.35 * ocr_conf + 0.25 * match_conf, 4)
    needs_review = False
    if profile is None:
        needs_review = True
    if ocr_engine == "unavailable":
        needs_review = True
    if confidence < config.CONFIDENCE_THRESHOLD:
        needs_review = True
        reasons.append(f"综合置信度 {confidence} < 阈值 {config.CONFIDENCE_THRESHOLD}")
    if rank is None and profile is not None and ocr_engine != "unavailable":
        needs_review = True

    sample_id = db.insert_sample(conn, {
        # 存相对 DATA_DIR 的路径：可随数据目录整体迁移，且 /media/ 路由可直接拼接
        "image_path": os.path.relpath(image_path, config.DATA_DIR).replace("\\", "/"),
        "roi_path": (os.path.relpath(roi_path, config.DATA_DIR).replace("\\", "/")
                     if roi_path else None),
        "ticket_type": profile.id if profile else None,
        "ticket_type_conf": type_conf,
        "ocr_engine": ocr_engine,
        "ocr_text": ocr_text,
        "predicted_rank": rank,
        "predicted_amount": amount,
        "confidence": confidence,
        "needs_review": needs_review,
        "review_reason": "；".join(reasons) if reasons else ("识别完成" if not needs_review else "待人工复核"),
        "device": device or "", "note": note or "",
    })
    d = db.get_sample(conn, sample_id)
    d["image_url"] = "/media/" + d["image_path"].replace("\\", "/")
    if d["roi_path"]:
        d["roi_url"] = "/media/" + d["roi_path"].replace("\\", "/")
    return d


def verify_sample(conn, sample_id: int, actual_rank: Optional[str],
                  actual_amount: Optional[int], note: Optional[str] = None) -> dict:
    """用户录入实际结果并闭环验证。状态判定：

    - 实际奖级与金额都为空 → ValueError（必须至少提供一项）；
    - 样本无系统预测（predicted_rank/amount 均空）→ review（无预测可比）；
    - 提供的字段与预测有交集 → 逐一比较：一致 match，否则 mismatch；
    - 提供字段与预测无交集（如预测只有 rank 而用户只录了金额）→ review。
    """
    d = db.get_sample(conn, sample_id)
    if d is None:
        raise ValueError(f"样本不存在：{sample_id}")
    actual_rank = (actual_rank or None)
    if actual_amount is not None:
        actual_amount = int(actual_amount)
    if actual_rank is None and actual_amount is None:
        raise ValueError("必须至少提供 actual_rank 或 actual_amount 之一")

    has_pred_rank = d["predicted_rank"] is not None
    has_pred_amount = d["predicted_amount"] is not None
    status = "review"
    if has_pred_rank or has_pred_amount:
        overlap = (has_pred_rank and actual_rank is not None) or \
                  (has_pred_amount and actual_amount is not None)
        if overlap:
            status = "match"
            if has_pred_rank and actual_rank is not None and d["predicted_rank"] != actual_rank:
                status = "mismatch"
            if has_pred_amount and actual_amount is not None and int(d["predicted_amount"]) != actual_amount:
                status = "mismatch"
        else:
            status = "review"
    db.set_sample_verification(conn, sample_id, actual_rank, actual_amount, status, note)
    out = db.get_sample(conn, sample_id)
    out["image_url"] = "/media/" + out["image_path"].replace("\\", "/")
    return out
