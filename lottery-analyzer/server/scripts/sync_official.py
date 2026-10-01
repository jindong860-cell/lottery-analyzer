"""命令行同步脚本：
    python scripts/sync_official.py ssq incremental
    python scripts/sync_official.py dlt full
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lottery_server import db, sources  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in sources.OFFICIAL_SOURCES:
        print(f"用法: python scripts/sync_official.py <{'|'.join(sources.OFFICIAL_SOURCES)}> [incremental|full]")
        sys.exit(2)
    game = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "incremental"
    conn = db.connect()
    try:
        db.init_db(conn)
        out = sources.sync_official(conn, game, mode=mode)
        print(f"[{game}] 拉取 {out['fetched']} 期，新增 {out['inserted']}，更新 {out['updated']}，"
              f"库内共 {out['total_in_db']} 期")
        if out["errors"]:
            print("解析警告：")
            for e in out["errors"]:
                print("  -", e)
    except sources.SourceError as e:
        print(f"同步失败（官方源不可用，未写入任何数据）：{e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
