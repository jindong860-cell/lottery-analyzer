"""db.py 单元测试：去重、样本闭环、模型运行读写。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lottery_server import db  # noqa: E402


def row(game="dlt", issue="1", date="2024-01-01", reds=None, blues=None):
    return {"game": game, "issue": issue, "draw_date": date,
            "reds": reds or [1, 2, 3, 4, 5], "blues": blues or [1, 2],
            "source": "test"}


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(os.path.join(self.tmp.name, "t.db"))
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_upsert_dedup(self):
        ins, upd = db.upsert_draws(self.conn, [row(issue="1"), row(issue="2")])
        self.assertEqual((ins, upd), (2, 0))
        # 同期重复拉取：不新增行，计为更新（幂等去重核心语义）
        ins, upd = db.upsert_draws(self.conn, [row(issue="2", reds=[9, 8, 3, 4, 5]), row(issue="3")])
        self.assertEqual((ins, upd), (1, 1))
        self.assertEqual(db.count_draws(self.conn, "dlt"), 3)
        rows, total = db.get_draws_page(self.conn, "dlt", 1, 10)
        self.assertEqual(total, 3)
        self.assertEqual(rows[0]["issue"], "3")  # 按日期倒序
        changed = next(r for r in rows if r["issue"] == "2")
        self.assertEqual(changed["reds"], [3, 4, 5, 8, 9])  # 存储时已升序

    def test_sample_lifecycle_and_accuracy(self):
        sid = db.insert_sample(self.conn, {
            "image_path": "scratch_images/a.png", "ticket_type": "ggl_default_a",
            "ticket_type_conf": 0.9, "ocr_engine": "tesseract", "ocr_text": "100元",
            "predicted_rank": "100元档", "predicted_amount": 100, "confidence": 0.8,
            "needs_review": False, "review_reason": "识别完成"})
        self.assertEqual(db.get_sample(self.conn, sid)["match_status"], "pending")
        db.set_sample_verification(self.conn, sid, "100元档", 100, "match", "ok")
        d = db.get_sample(self.conn, sid)
        self.assertEqual(d["match_status"], "match")
        self.assertTrue(d["verified_at"])
        self.assertFalse(d["needs_review"])
        acc = db.sample_accuracy(self.conn)
        self.assertEqual(acc["auto_verified"], {"total": 1, "match": 1, "mismatch": 0, "accuracy": 1.0})
        self.assertEqual(acc["by_status"], {"match": 1})
        self.assertEqual(acc["by_ticket_type"][0]["ticket_type"], "ggl_default_a")

    def test_model_runs_roundtrip(self):
        rid = db.insert_model_run(self.conn, {
            "created_at": db.now(), "game": "dlt", "model_name": "m",
            "feature_version": "v1", "seed": 7, "test_ratio": 0.2, "window": 30,
            "train_samples": 100, "test_samples": 30,
            "metrics": {"auc": 0.5}, "report": {"run_id": None, "k": "v"},
            "dataset_fingerprint": "ab" * 32})
        db.finalize_model_run(self.conn, rid, {"run_id": rid, "k": "v"}, "models/x.json")
        got = db.get_model_run(self.conn, rid)
        self.assertEqual(got["report"]["run_id"], rid)
        self.assertEqual(got["artifact_path"], "models/x.json")
        self.assertEqual(db.latest_model_run(self.conn, "dlt")["id"], rid)
        self.assertEqual(len(db.list_model_runs(self.conn, "ssq")), 0)

    def test_sync_log(self):
        db.add_sync_log(self.conn, "dlt", "src", True, "ok", 3, 2, 1)
        rows = db.list_sync_log(self.conn)
        self.assertEqual(rows[0]["inserted"], 2)
        self.assertTrue(rows[0]["ok"])


if __name__ == "__main__":
    unittest.main()
