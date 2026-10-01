"""http_api 集成测试：起真实线程服务（端口 0），打补丁隔离网络与文件系统，全链路验证。

覆盖：健康检查、同步（假 fetcher）、开奖列表、统计、训练、回测运行详情、预测、
刮刮乐上传（OCR 不可用→人工复核）、录入验证→review、带预测样本→match、准确率、
静态页、错误码。
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lottery_server.config as config  # noqa: E402
from lottery_server import db, http_api, sources  # noqa: E402

SYNC_ROWS = [
    {"game": "dlt", "issue": "24001", "draw_date": "2024-01-01",
     "reds": [1, 5, 12, 22, 33], "blues": [3, 9], "source": "test"},
    {"game": "dlt", "issue": "24002", "draw_date": "2024-01-03",
     "reds": [3, 11, 17, 24, 30], "blues": [2, 11], "source": "test"},
]


def req(method, url, payload=None, raw=None, headers=None, timeout=15):
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    r = urllib.request.Request(url, data=data, method=method,
                               headers=headers or ({"Content-Type": "application/json"} if data else {}))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, body


def multipart(fields: dict, boundary="testbnd789") -> bytes:
    """fields: name -> (filename|None, bytes)"""
    out = b""
    for name, (fn, val) in fields.items():
        out += f"--{boundary}\r\n".encode()
        if fn is not None:
            out += (f'Content-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                    "Content-Type: image/png\r\n\r\n").encode()
        else:
            out += (f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode()
        out += val + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out


def biased_draws(n=120):
    rows = []
    for i in range(n):
        front = sorted({1, 10 + (i % 8), 18 + ((i + 1) % 7),
                        25 + ((i * 2) % 6), 31 + (i % 4)})
        rows.append({"game": "dlt", "issue": str(25000 + i),
                     "draw_date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}",
                     "reds": front, "blues": [1 + (i % 6), 7 + (i % 6)], "source": "test"})
    return rows


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = cls.tmp.name
        cls._patch = []
        for attr, val in [
            ("DB_PATH", os.path.join(base, "api.db")),
            ("DATA_DIR", base),
            ("IMAGE_DIR", os.path.join(base, "scratch_images")),
            ("ROI_DIR", os.path.join(base, "scratch_roi")),
            ("MODEL_DIR", os.path.join(base, "models")),
            ("PROFILES_PATH", os.path.join(base, "profiles.json")),
            ("WEB_DIR", base),
        ]:
            cls._patch.append((attr, getattr(config, attr)))
            setattr(config, attr, val)
        with open(os.path.join(base, "index.html"), "w", encoding="utf-8") as f:
            f.write("<html><body><h1>彩票分析</h1></body></html>")
        cls._orig_fetch = sources.fetch_official
        sources.fetch_official = lambda game, limit, fetcher=None: (SYNC_ROWS, [])
        cls.srv = http_api.create_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        sources.fetch_official = cls._orig_fetch
        for attr, val in cls._patch:
            setattr(config, attr, val)
        cls.tmp.cleanup()

    def _upload_png(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (100, 200), (190, 40, 40)).save(buf, format="PNG")
        return buf.getvalue()

    def test_full_chain(self):
        # 1) 健康
        st, out = req("GET", f"{self.base_url}/api/health")
        self.assertEqual(st, 200)
        self.assertTrue(out["ok"])
        # 2) 同步（假 fetcher，不触网）
        st, out = req("POST", f"{self.base_url}/api/draws/sync", {"game": "dlt"})
        self.assertEqual(st, 200)
        self.assertEqual(out["inserted"], 2)
        # 3) 列表 + 分页
        st, out = req("GET", f"{self.base_url}/api/draws?game=dlt&page=1&page_size=1")
        self.assertEqual((st, out["total"], len(out["rows"])), (200, 2, 1))
        self.assertEqual(out["rows"][0]["issue"], "24002")  # 倒序
        # 4) 统计三件套
        st, out = req("GET", f"{self.base_url}/api/stats/frequency?game=dlt")
        self.assertEqual((st, out["draw_count"]), (200, 2))
        st, out = req("GET", f"{self.base_url}/api/stats/omission?game=dlt")
        self.assertEqual(st, 200)
        st, out = req("GET", f"{self.base_url}/api/stats/trend?game=dlt&last_n=1")
        self.assertEqual((st, len(out["rows"])), (200, 1))
        # 5) 彩种校验 → 400
        st, out = req("GET", f"{self.base_url}/api/draws?game=xxx")
        self.assertEqual(st, 400)
        # 6) 训练 + 运行详情 + 预测（直接灌入 120 期确定性偏置数据）
        conn = db.connect()
        try:
            db.init_db(conn)
            db.upsert_draws(conn, biased_draws(120))
        finally:
            conn.close()
        st, out = req("POST", f"{self.base_url}/api/model/train",
                      {"game": "dlt", "window": 10, "test_ratio": 0.2})
        self.assertEqual(st, 200)
        run_id = out["run_id"]
        self.assertEqual(out["test_draws"], 22)
        self.assertNotIn("weights", out)  # 列表不带权重
        st, out = req("GET", f"{self.base_url}/api/model/runs/{run_id}")
        self.assertEqual((st, "weights" in out["report"]), (200, True))
        st, out = req("GET", f"{self.base_url}/api/model/runs?game=dlt")
        self.assertEqual((st, len(out["rows"])), (200, 1))
        st, out = req("POST", f"{self.base_url}/api/model/predict", {"game": "dlt"})
        self.assertEqual((st, len(out["top_k"])), (200, 5))
        # 7) 上传（测试环境无 pytesseract → needs_review=True, status=pending）
        body = multipart({"image": ("ticket.png", self._upload_png()),
                          "device": (None, b"unittest"),
                          "note": (None, "集成测试".encode("utf-8"))})
        st, out = req("POST", f"{self.base_url}/api/scratch/samples", raw=body,
                      headers={"Content-Type": f"multipart/form-data; boundary=testbnd789"})
        self.assertEqual(st, 200)
        sample_id = out["id"]
        self.assertTrue(out["needs_review"])
        self.assertEqual(out["match_status"], "pending")
        self.assertIn("needs_review", out)
        self.assertTrue(out["image_url"].startswith("/media/"))
        # 图片确实落盘且可经 /media 访问
        self.assertTrue(os.path.isfile(os.path.join(config.DATA_DIR, out["image_path"])))
        st, out2 = req("GET", self.base_url + out["image_url"])
        self.assertEqual(st, 200)
        # 8) 无预测样本录入实际结果 → review
        st, out = req("POST", f"{self.base_url}/api/scratch/samples/{sample_id}/verify",
                      {"actual_rank": "10元档", "actual_amount": 10})
        self.assertEqual((st, out["match_status"]), (200, "review"))
        # 9) 缺参 → 400
        st, out = req("POST", f"{self.base_url}/api/scratch/samples/{sample_id}/verify", {})
        self.assertEqual(st, 400)
        # 10) 直接构造带预测的样本 → verify → match
        conn = db.connect()
        try:
            sid2 = db.insert_sample(conn, {
                "image_path": "scratch_images/fake.png",
                "ticket_type": "ggl_default_a", "ticket_type_conf": 0.9,
                "ocr_engine": "tesseract", "ocr_text": "100元",
                "predicted_rank": "100元档", "predicted_amount": 100,
                "confidence": 0.8, "needs_review": False})
            with open(os.path.join(config.DATA_DIR, "scratch_images", "fake.png"), "wb") as f:
                f.write(self._upload_png())
        finally:
            conn.close()
        st, out = req("POST", f"{self.base_url}/api/scratch/samples/{sid2}/verify",
                      {"actual_rank": "100元档", "actual_amount": 100})
        self.assertEqual((st, out["match_status"]), (200, "match"))
        # 录入错误金额 → mismatch
        st, out = req("POST", f"{self.base_url}/api/scratch/samples/{sid2}/verify",
                      {"actual_amount": 20})
        self.assertEqual((st, out["match_status"]), (200, "mismatch"))
        # 11) 准确率
        st, out = req("GET", f"{self.base_url}/api/scratch/accuracy")
        self.assertEqual((st, out["auto_verified"]), (200, {"total": 1, "match": 0, "mismatch": 1, "accuracy": 0.0}))
        # 12) 样本列表
        st, out = req("GET", f"{self.base_url}/api/scratch/samples")
        self.assertEqual((st, len(out["rows"])), (200, 2))
        # 13) 票种 profiles 读写
        st, out = req("GET", f"{self.base_url}/api/scratch/profiles")
        self.assertEqual((st, len(out["profiles"])), (200, 2))
        prof = out["profiles"][0]
        prof["name"] = "改名票种"
        st, out = req("PUT", f"{self.base_url}/api/scratch/profiles", {"profiles": [prof]})
        self.assertEqual((st, out["profiles"][0]["name"]), (200, "改名票种"))
        # 14) 静态页
        st, raw = req("GET", f"{self.base_url}/")
        self.assertEqual(st, 200)
        # 15) 未知接口 → 404
        st, out = req("POST", f"{self.base_url}/api/nothing", {})
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
