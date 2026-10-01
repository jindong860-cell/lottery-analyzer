# -*- coding: utf-8 -*-
"""全局配置：路径、彩种定义、服务参数。所有路径可被环境变量覆盖，便于部署与测试。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # server/
ROOT_DIR = os.path.dirname(BASE_DIR)                        # 工程根
DATA_DIR = os.environ.get("LOTTERY_DATA") or os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("LOTTERY_DB") or os.path.join(DATA_DIR, "lottery.db")
IMAGE_DIR = os.path.join(DATA_DIR, "scratch_images")
ROI_DIR = os.path.join(DATA_DIR, "scratch_roi")
MODEL_DIR = os.path.join(DATA_DIR, "models")
PROFILES_PATH = os.path.join(DATA_DIR, "profiles.json")
WEB_DIR = os.path.join(ROOT_DIR, "web")

HOST = os.environ.get("LOTTERY_HOST", "0.0.0.0")
PORT = int(os.environ.get("LOTTERY_PORT", "8000"))

HTTP_TIMEOUT = 20          # 官方接口超时（秒）
CONFIDENCE_THRESHOLD = 0.60  # 刮刮乐识别置信度阈值，低于则提示人工复核
MAX_PAGE_SIZE = 200

# 彩种定义（官方规则口径）
GAMES = {
    "ssq": {
        "name": "双色球",
        "front_count": 6, "front_max": 33, "front_name": "红球",
        "back_count": 1, "back_max": 16, "back_name": "蓝球",
        "draw_days": "每周二、四、日 21:15 开奖",
    },
    "dlt": {
        "name": "大乐透",
        "front_count": 5, "front_max": 35, "front_name": "前区",
        "back_count": 2, "back_max": 12, "back_name": "后区",
        "draw_days": "每周一、三、六 21:25 开奖",
    },
}
