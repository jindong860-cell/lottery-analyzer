"""sources.py 单元测试：解析官方返回结构（内联夹具，不访问网络）、严格校验、幂等同步与错误传播。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lottery_server import db, sources  # noqa: E402

# 夹具结构对照官方实测：双色球 findDrawNotice 与大乐透 getHistoryPageListV1.qry
SSQ_FIXTURE = {
    "result": {"result": [
        {"code": "2024001", "date": "2024-01-02", "red": "01,09,16,22,25,33", "blue": "07"},
        {"code": "2024002", "date": "2024-01-04", "red": "02,11,17,20,28,32", "blue": "12"},
    ]},
}
DLT_FIXTURE = {
    "value": {"pages": 2, "list": [
        {"lotteryDrawNum": "24001", "lotteryDrawTime": "2024-01-01",
         "lotteryDrawResult": "01 05 12 22 33 03 09"},
        {"lotteryDrawNum": "24002", "lotteryDrawTime": "2024-01-03",
         "lotteryDrawResult": "03 11 17 24 30 02 11"},
        {"lotteryDrawNum": "24003", "lotteryDrawTime": "2024-01-05",
         "lotteryDrawResult": "bad data"},   # 一条坏数据：应进 errors 而非中断
    ]},
}


class ParseTest(unittest.TestCase):
    def test_parse_ssq(self):
        rows, errors = sources.parse_ssq(SSQ_FIXTURE)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["reds"], [1, 9, 16, 22, 25, 33])
        self.assertEqual(rows[0]["blues"], [7])
        self.assertIn("www.cwl.gov.cn", rows[0]["source"])

    def test_parse_dlt_with_bad_record(self):
        rows, errors = sources.parse_dlt(DLT_FIXTURE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["reds"], [1, 5, 12, 22, 33])
        self.assertEqual(rows[0]["blues"], [3, 9])
        self.assertEqual(len(errors), 1)

    def test_make_row_validation(self):
        with self.assertRaises(ValueError):
            sources.make_row("dlt", "1", "2024-01-01", [1, 2, 3], [1, 2])      # 个数
        with self.assertRaises(ValueError):
            sources.make_row("dlt", "1", "2024-01-01", [1, 1, 3, 4, 5], [1, 2])  # 重复
        with self.assertRaises(ValueError):
            sources.make_row("dlt", "1", "2024-01-01", [1, 2, 3, 4, 36], [1, 2])  # 越界
        with self.assertRaises(ValueError):
            sources.make_row("dlt", "1", "bad-date", [1, 2, 3, 4, 5], [1, 2])   # 日期


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(os.path.join(self.tmp.name, "t.db"))
        db.init_db(self.conn)
        self.calls = []

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def fake_fetcher(self, url, headers):
        self.calls.append(url)
        if "sporttery" in url:
            page = int(url.split("pageNo=")[1])
            if page == 1:
                return DLT_FIXTURE
            return {"value": {"pages": 2, "list": []}}
        return SSQ_FIXTURE

    def test_sync_dlt_incremental_and_dedup(self):
        out = sources.sync_official(self.conn, "dlt", "incremental", fetcher=self.fake_fetcher)
        self.assertEqual(out["inserted"], 2)
        self.assertEqual(out["errors"], [])   # 坏数据只警告不入库？——errors 记录但同步成功
        self.assertEqual(out["total_in_db"], 2)
        # 第二次同步：同样数据 → 全部计入 updated，库内不膨胀
        out2 = sources.sync_official(self.conn, "dlt", "incremental", fetcher=self.fake_fetcher)
        self.assertEqual(out2["inserted"], 0)
        self.assertEqual(out2["updated"], 2)
        self.assertEqual(db.count_draws(self.conn, "dlt"), 2)
        log = db.list_sync_log(self.conn)
        self.assertEqual(len(log), 2)
        self.assertTrue(log[0]["ok"])

    def test_sync_failure_writes_log_and_raises(self):
        def bad(url, headers):
            raise sources.SourceError("网络不可达")
        with self.assertRaises(sources.SourceError):
            sources.sync_official(self.conn, "dlt", "incremental", fetcher=bad)
        log = db.list_sync_log(self.conn)
        self.assertFalse(log[0]["ok"])
        self.assertIn("网络不可达", log[0]["message"])

    def test_unknown_game(self):
        with self.assertRaises(sources.SourceError):
            sources.sync_official(self.conn, "xxx", fetcher=self.fake_fetcher)


if __name__ == "__main__":
    unittest.main()
