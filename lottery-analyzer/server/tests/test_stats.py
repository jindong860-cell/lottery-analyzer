"""stats.py 单元测试：固定 5 期开奖，手算频率/遗漏/走势逐项对照。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lottery_server import db, stats  # noqa: E402

# dlt: front 5/35, back 2/12
DRAWS = [
    ("1", "2024-01-01", [1, 2, 3, 4, 5], [1, 2]),
    ("2", "2024-01-03", [1, 6, 7, 8, 9], [1, 3]),
    ("3", "2024-01-05", [2, 3, 10, 11, 12], [4, 5]),
    ("4", "2024-01-07", [1, 3, 13, 14, 15], [2, 6]),
    ("5", "2024-01-09", [5, 7, 9, 11, 13], [1, 7]),
]


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(os.path.join(self.tmp.name, "t.db"))
        db.init_db(self.conn)
        db.upsert_draws(self.conn, [
            {"game": "dlt", "issue": i, "draw_date": d, "reds": r, "blues": b, "source": "test"}
            for i, d, r, b in DRAWS])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_frequency(self):
        out = stats.frequency(self.conn, "dlt")
        self.assertEqual(out["draw_count"], 5)
        f = {x["num"]: x for x in out["front"]}
        self.assertEqual(f[1], {"num": 1, "count": 3, "rate": 0.6})
        self.assertEqual(f[5], {"num": 5, "count": 2, "rate": 0.4})
        self.assertEqual(f[34], {"num": 34, "count": 0, "rate": 0.0})
        b = {x["num"]: x for x in out["back"]}
        self.assertEqual(b[1]["count"], 3)
        # 窗口：最近 2 期（期4、期5）
        w2 = stats.frequency(self.conn, "dlt", window=2)
        fw = {x["num"]: x for x in w2["front"]}
        self.assertEqual(w2["draw_count"], 2)
        self.assertEqual(fw[13]["count"], 2)
        self.assertEqual(fw[1]["count"], 1)

    def test_omission(self):
        out = stats.omission(self.conn, "dlt")
        f = {x["num"]: x for x in out["front"]}
        # num1 开在期序 0,1,3：gaps=[0,0,1]，current=1，max=1，avg=round(1/3,2)=0.33
        self.assertEqual(f[1], {"num": 1, "current": 1, "max": 1, "avg": 0.33})
        # num5 开在期序 0,4：gaps=[0,3]，current=0，max=3，avg=1.5
        self.assertEqual(f[5], {"num": 5, "current": 0, "max": 3, "avg": 1.5})
        # num35 从未开出：current=max=5，avg=None
        self.assertEqual(f[35], {"num": 35, "current": 5, "max": 5, "avg": None})
        b = {x["num"]: x for x in out["back"]}
        # back1 开在 0,1,4：gaps=[0,0,2]，current=0，max=2，avg=0.67
        self.assertEqual(b[1], {"num": 1, "current": 0, "max": 2, "avg": 0.67})

    def test_trend(self):
        out = stats.trend(self.conn, "dlt", last_n=2)
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["rows"][0]["issue"], "5")   # 最新在前
        self.assertEqual(out["rows"][1]["issue"], "4")
        self.assertEqual(out["rows"][0]["reds"], [5, 7, 9, 11, 13])

    def test_unknown_game_raises(self):
        with self.assertRaises(ValueError):
            stats.frequency(self.conn, "xxx")


if __name__ == "__main__":
    unittest.main()
