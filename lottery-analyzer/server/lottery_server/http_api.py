"""HTTP API：标准库 ThreadingHTTPServer 实现，同源托管 Web 静态页与 /media 静态资源。

约定：
- 所有 /api/* 返回 JSON；错误统一 {"error": "..."}（ValueError→400，SourceError→502 上游不可用，其余 404/405/500）；
- 无第三方 Web 依赖（部署仅需 Python3 + numpy + Pillow）；
- config 在“请求时”读取（便于测试替换 DB/目录），路由表集中在 do_GET/do_POST/do_PUT。
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, db, sources, stats, model, ocr

MAX_BODY = 20 * 1024 * 1024  # 上传图片上限 20MB


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- multipart 解析

def parse_multipart(body: bytes, content_type: str) -> dict:
    """极简 multipart/form-data 解析：返回 {field: {"filename":str|None, "value":bytes}}。"""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise ApiError(400, "缺少 multipart boundary")
    boundary = ("--" + m.group(1)).encode()
    fields: dict[str, dict] = {}
    for part in body.split(boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        head, _, value = part.partition(b"\r\n\r\n")
        headers = head.decode("utf-8", "replace")
        nm = re.search(r'name="([^"]*)"', headers)
        if not nm:
            continue
        name = nm.group(1)
        fn = re.search(r'filename="([^"]*)"', headers)
        fields[name] = {"filename": fn.group(1) if fn else None, "value": value}
    return fields


# ---------------------------------------------------------------- 处理器

class Handler(BaseHTTPRequestHandler):
    server_version = "LotteryAnalyzer/1.0"

    # ---- 基础设施
    def log_message(self, fmt, *args):  # 简洁日志
        pass

    def _json(self, status: int, payload) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _query(self) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "请求体过大")
        if n == 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            raise ApiError(400, f"JSON 解析失败：{e}")

    def _conn(self):
        return db.connect()

    def _static(self, rel: str, base_dir: str) -> None:
        """静态文件（含 /media），防止路径穿越：解析后必须仍在 base_dir 内。"""
        rel = rel.lstrip("/")
        full = os.path.normpath(os.path.join(base_dir, rel))
        if not full.startswith(os.path.normpath(base_dir)):
            self._json(403, {"error": "非法路径"})
            return
        if not os.path.isfile(full):
            self._json(404, {"error": "未找到资源"})
            return
        ctype = "application/octet-stream"
        if full.endswith((".html", ".htm")):
            ctype = "text/html; charset=utf-8"
        elif full.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".png"):
            ctype = "image/png"
        elif full.endswith((".jpg", ".jpeg")):
            ctype = "image/jpeg"
        elif full.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        with open(full, "rb") as f:
            raw = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # ---- 路由
    def do_OPTIONS(self):
        self._json(204, None)

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            q = self._query()
            if path == "/api/health":
                self._json(200, {"ok": True, "games": list(config.GAMES.keys())})
            elif path == "/api/draws":
                game = q.get("game", "")
                if game not in config.GAMES:
                    raise ValueError(f"未知彩种 {game}（可选：{list(config.GAMES)}）")
                page = max(1, int(q.get("page", 1)))
                size = min(config.MAX_PAGE_SIZE, max(1, int(q.get("page_size", 20))))
                conn = self._conn()
                try:
                    rows, total = db.get_draws_page(conn, game, page, size)
                    self._json(200, {"game": game, "page": page, "page_size": size,
                                     "total": total, "rows": rows})
                finally:
                    conn.close()
            elif path == "/api/draws/synclog":
                conn = self._conn()
                try:
                    self._json(200, {"rows": db.list_sync_log(conn)})
                finally:
                    conn.close()
            elif path in ("/api/stats/frequency", "/api/stats/omission", "/api/stats/trend"):
                game = q.get("game", "")
                conn = self._conn()
                try:
                    if path.endswith("frequency"):
                        out = stats.frequency(conn, game, int(q.get("window", 0)))
                    elif path.endswith("omission"):
                        out = stats.omission(conn, game)
                    else:
                        out = stats.trend(conn, game, int(q.get("last_n", 30)))
                    self._json(200, out)
                finally:
                    conn.close()
            elif path == "/api/model/runs":
                conn = self._conn()
                try:
                    self._json(200, {"rows": db.list_model_runs(conn, q.get("game") or None,
                                                                int(q.get("limit", 50)))})
                finally:
                    conn.close()
            elif path.startswith("/api/model/runs/"):
                run_id = int(path.rsplit("/", 1)[-1])
                conn = self._conn()
                try:
                    run = db.get_model_run(conn, run_id)
                    if run is None:
                        raise ApiError(404, f"运行不存在：{run_id}")
                    self._json(200, run)
                finally:
                    conn.close()
            elif path == "/api/scratch/samples":
                conn = self._conn()
                try:
                    rows = db.list_samples(conn, q.get("status") or None, int(q.get("limit", 100)))
                    for d in rows:
                        d["image_url"] = "/media/" + d["image_path"]
                        if d["roi_path"]:
                            d["roi_url"] = "/media/" + d["roi_path"]
                    self._json(200, {"rows": rows})
                finally:
                    conn.close()
            elif path == "/api/scratch/accuracy":
                conn = self._conn()
                try:
                    self._json(200, db.sample_accuracy(conn))
                finally:
                    conn.close()
            elif path == "/api/scratch/profiles":
                profiles = [p.to_dict() for p in ocr.load_profiles()]
                self._json(200, {"profiles": profiles})
            elif path.startswith("/media/"):
                self._static(path[len("/media/"):], config.DATA_DIR)
            else:
                if path in ("/", "/index.html"):
                    self._static("index.html", config.WEB_DIR)
                else:
                    self._static(path, config.WEB_DIR)
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except sources.SourceError as e:
            self._json(502, {"error": str(e)})
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except BrokenPipeError:
            pass
        except Exception as e:  # 最后防线：记录并返回 500
            self._json(500, {"error": f"服务器内部错误：{type(e).__name__}: {e}"})

    def do_PUT(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/scratch/profiles":
                body = self._body_json()
                profiles = [ocr.TicketProfile.from_dict(d) for d in body.get("profiles", [])]
                if not profiles:
                    raise ValueError("profiles 不能为空")
                ocr.save_profiles(profiles)
                self._json(200, {"profiles": [p.to_dict() for p in profiles]})
            else:
                raise ApiError(404, "未知接口")
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except Exception as e:
            self._json(500, {"error": f"服务器内部错误：{type(e).__name__}: {e}"})

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/draws/sync":
                body = self._body_json()
                conn = self._conn()
                try:
                    out = sources.sync_official(conn, body.get("game", ""),
                                                mode=body.get("mode", "incremental"),
                                                limit=body.get("limit"))
                    self._json(200, out)
                finally:
                    conn.close()
            elif path == "/api/model/train":
                body = self._body_json()
                conn = self._conn()
                try:
                    report = model.train_and_backtest(
                        conn, body.get("game", ""), seed=int(body.get("seed", 7)),
                        test_ratio=float(body.get("test_ratio", 0.2)),
                        window=int(body.get("window", 30)))
                    slim = {k: report[k] for k in report if k != "weights"}
                    self._json(200, slim)  # 权重见 GET /api/model/runs/{id} 或 artifact 文件
                finally:
                    conn.close()
            elif path == "/api/model/predict":
                body = self._body_json()
                conn = self._conn()
                try:
                    self._json(200, model.predict_next(
                        conn, body.get("game", ""),
                        run_id=body.get("run_id"), top_k=body.get("top_k")))
                finally:
                    conn.close()
            elif path == "/api/scratch/samples":
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise ApiError(413, "上传图片过大（>20MB）")
                body = self.rfile.read(n)
                fields = parse_multipart(body, self.headers.get("Content-Type", ""))
                if "image" not in fields or not fields["image"]["value"]:
                    raise ValueError("缺少 image 文件字段")
                conn = self._conn()
                try:
                    out = ocr.process_upload(
                        conn, fields["image"]["value"],
                        fields["image"]["filename"] or "upload.jpg",
                        hint=(fields.get("ticket_type_hint", {}) or {}).get("value"),
                        device=((fields.get("device", {}) or {}).get("value") or b"").decode("utf-8", "replace") if fields.get("device") else "",
                        note=((fields.get("note", {}) or {}).get("value") or b"").decode("utf-8", "replace") if fields.get("note") else "")
                    self._json(200, out)
                finally:
                    conn.close()
            elif re.fullmatch(r"/api/scratch/samples/\d+/verify", path):
                sample_id = int(path.split("/")[4])
                body = self._body_json()
                conn = self._conn()
                try:
                    self._json(200, ocr.verify_sample(
                        conn, sample_id, body.get("actual_rank"),
                        body.get("actual_amount"), body.get("note")))
                finally:
                    conn.close()
            else:
                raise ApiError(404, "未知接口")
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except sources.SourceError as e:
            self._json(502, {"error": str(e)})
        except ocr.OcrUnavailable:
            self._json(503, {"error": "服务端OCR不可用"})  # 正常流程内已降级处理，不应到达
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except BrokenPipeError:
            pass
        except Exception as e:
            self._json(500, {"error": f"服务器内部错误：{type(e).__name__}: {e}"})


def create_server(host: str = None, port: int = None) -> ThreadingHTTPServer:
    host = host or config.HOST
    port = int(port or config.PORT)
    for d in (config.DATA_DIR, config.IMAGE_DIR, config.ROI_DIR, config.MODEL_DIR):
        os.makedirs(d, exist_ok=True)
    conn = db.connect()
    try:
        db.init_db(conn)
    finally:
        conn.close()
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    srv = create_server()
    print(f"彩票分析服务已启动: http://{config.HOST}:{config.PORT}")
    print(f"数据目录: {config.DATA_DIR}")
    print(f"Web 页面: {config.WEB_DIR}（同源托管于 /）")
    print("按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
