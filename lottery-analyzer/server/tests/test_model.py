"""model.py 单元测试：可分合成数据、确定性、偏置数据的训练/回测结构、predict_next。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lottery_server.config as config  # noqa: E402
from lottery_server import db, model  # noqa: E402


def biased_draws(n=120):
    """确定性偏置数据：号码 1 每期必开（freq=1.0），其余由互不重叠区间轮换生成。"""
    out = []
    for i in range(n):
        front = sorted({1,
                        10 + (i % 8),
                        18 + ((i + 1) % 7),
                        25 + ((i * 2) % 6),
                        31 + (i % 4),
                        2 + ((i * 3) % 7) - 1})
        blues = [1 + (i % 6), 7 + (i % 6)]
        out.append({"game": "dlt", "issue": str(24000 + i),
                    "draw_date": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                    "reds": front, "blues": blues, "source": "test"})
    return out


class MetricTest(unittest.TestCase):
    def test_fit_and_metrics_separable(self):
        # 两个线性可分高斯团：训练后 AUC 应接近 1
        import numpy as np
        rng = np.random.default_rng(0)
        xa = rng.normal(0.0, 0.4, size=(200, 2))
        xb = rng.normal(3.0, 0.4, size=(200, 2))
        X = np.vstack([xa, xb]).tolist()
        y = [0] * 200 + [1] * 200
        m = model.fit_logistic(X, y)
        p = model.predict_proba(m, X)
        a = model.auc(y, p)
        self.assertGreater(a, 0.95)
        # 确定性：零初始化全批量 GD，两次训练逐位一致
        m2 = model.fit_logistic(X, y)
        self.assertEqual(m, m2)

    def test_auc_degenerate_none(self):
        self.assertIsNone(model.auc([1, 1, 1], model.predict_proba(
            model.fit_logistic([[0.0, 1.0], [1.0, 1.0]], [1, 1]), [[0.0, 1.0], [1.0, 1.0]])))


class BacktestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config.MODEL_DIR = os.path.join(self.tmp.name, "models")
        os.makedirs(config.MODEL_DIR, exist_ok=True)
        self.conn = db.connect(os.path.join(self.tmp.name, "t.db"))
        db.init_db(self.conn)
        db.upsert_draws(self.conn, biased_draws(120))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_insufficient_data(self):
        conn2 = db.connect(os.path.join(self.tmp.name, "t2.db"))
        db.init_db(conn2)
        with self.assertRaises(ValueError):
            model.train_and_backtest(conn2, "dlt", window=30)
        conn2.close()

    def test_param_validation(self):
        with self.assertRaises(ValueError):
            model.train_and_backtest(self.conn, "dlt", test_ratio=0.9)
        with self.assertRaises(ValueError):
            model.train_and_backtest(self.conn, "dlt", window=3)

    def test_train_backtest_reproducible_and_report(self):
        r1 = model.train_and_backtest(self.conn, "dlt", window=10, test_ratio=0.2)
        r2 = model.train_and_backtest(self.conn, "dlt", window=10, test_ratio=0.2)
        self.assertEqual(r1["run_id"], 1)
        self.assertEqual(r2["run_id"], 2)
        for k in ("metrics", "simulation", "dataset_fingerprint"):
            self.assertEqual(r1[k], r2[k])  # 算法无随机成分：指标完全一致
        self.assertEqual(r1["total_draws"], 120)
        self.assertEqual(r1["test_draws"], 22)  # max(3, round((120-10)*0.2))
        self.assertEqual(r1["metrics"]["auc"] is not None, True)
        self.assertEqual(len(r1["dataset_fingerprint"]), 64)
        self.assertIn("disclaimer", r1)
        sim = r1["simulation"]
        # 号码 1 每期必开且频率特征为 1.0：Top-5 至少命中它 → 命中率=1.0
        self.assertEqual(sim["hit_rate_at_least_1"], 1.0)
        self.assertGreaterEqual(sim["avg_hits"], 1.0)
        # artifact 落盘
        art = os.path.join(config.MODEL_DIR, f"run_{r2['run_id']}.json")
        self.assertTrue(os.path.isfile(art))

    def test_predict_next(self):
        model.train_and_backtest(self.conn, "dlt", window=10)
        out = model.predict_next(self.conn, "dlt")
        self.assertEqual(out["game"], "dlt")
        self.assertEqual(out["based_on_run_id"], 1)
        self.assertEqual(len(out["top_k"]), 5)  # dlt front_count=5
        self.assertIn("仅供", out["disclaimer"])
        with self.assertRaises(ValueError):
            model.predict_next(self.conn, "ssq")  # 无 ssq 模型运行

    def test_build_dataset_shape(self):
        X, y, meta, names = model.build_dataset(self.conn, "dlt", window=10)
        self.assertEqual(names, model.FEATURE_NAMES)
        self.assertEqual(len(X), (120 - 10) * 35)  # 每个目标期 × 前区 35 个号码
        # 号码 1 每期开出：每个目标期恰有一个正样本
        self.assertEqual(sum(y), len(meta) // 35)


if __name__ == "__main__":
    unittest.main()
