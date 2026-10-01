"""开发/部署入口：python run_server.py
可选参数通过环境变量：LOTTERY_HOST / LOTTERY_PORT / LOTTERY_DATA / LOTTERY_DB（见 config.py）。
"""
from lottery_server import http_api

if __name__ == "__main__":
    http_api.main()
