# 彩票分析助手（个人版）

个人使用的彩票数据分析与刮刮乐验证工具：**Python 后端 + Web 端 + Android 端**，三端共用同一套 HTTP 接口与同一份 SQLite 数据。

> **免责声明**：彩票开奖为独立随机事件。本项目的一切统计、回测与"预测"输出仅用于方法学习与数据记录，不构成任何投注建议；请理性购彩。

## 功能（冻结清单 F1–F8，详见 docs/01）

- F1 开奖数据库：双色球 + 大乐透官方公开接口，历史入库、增量/全量同步、`UNIQUE(game,issue)` 幂等去重、同步审计日志
- F2 统计分析：频率 / 遗漏（当前、最大、平均）/ 走势
- F3 轻量模型：逻辑回归（L2，梯度下降，固定随机种子），特征 `freq_omit_v1`
- F4 回测：按时间切分训练/测试集，AUC / LogLoss / Brier + Top-K 模拟对比随机基线，全参数可复现（seed + 数据集指纹）
- F5 下期参考：基于最新运行输出 Top-K 概率（附带免责声明）
- F6 刮刮乐闭环：上传照片 → 票种识别 → ROI 裁剪 → OCR → 模板匹配 → 人工录入实际结果 → 准确率统计（置信度 <0.60 或环节缺失强制人工复核）
- F7 三端一致：Web（零构建原生 JS）与 Android（Kotlin + Compose + Room + ML Kit）调用同一后端
- F8 可追溯：所有样本、验证结果、训练档案落库并落盘（含权重归档 `models/run_{id}.json`）

## 目录结构

```
lottery-analyzer/
├── server/                     # Python 后端（标准库 http.server + sqlite3）
│   ├── run_server.py           # 启动入口（默认 0.0.0.0:8000）
│   ├── requirements.txt        # numpy、Pillow 必装；pytesseract 可选
│   ├── scripts/sync_official.py# CLI 手动同步
│   ├── lottery_server/
│   │   ├── config.py           # 路径/阈值/彩种配置（环境变量可覆盖）
│   │   ├── db.py               # 表结构 + 数据访问（WAL 单文件库）
│   │   ├── sources.py          # 官方数据源接入（仅官方，不伪造）
│   │   ├── stats.py            # 频率 / 遗漏 / 走势
│   │   ├── model.py            # 特征工程、训练、回测、预测
│   │   ├── ocr.py              # 票种模板、ROI、OCR、验证闭环
│   │   └── http_api.py         # REST API + 静态托管（Web/媒体）
│   ├── tests/                  # 5 个 unittest 文件（离线夹具，见 docs/03 §4）
│   └── data/ models/ profiles.json   # 运行期生成
├── web/                        # 原生 HTML/JS/CSS 单页（由后端同源托管）
├── android/                    # Kotlin + Compose 客户端（Android Studio 打开即构建）
│   └── app/src/main/java/com/luckylab/app/
│       ├── data/               # Retrofit DTO/API、Room 缓存、依赖图
│       ├── ml/ModelMath.kt     # 纯 Kotlin 推理（镜像服务端特征与权重）
│       ├── ocr/                # 端侧票种识别 + ML Kit 流水线
│       └── ui/                 # 五页签界面
└── docs/                       # 01 功能冻结与技术选型 · 02 表结构/接口/数据流 · 03 安装测试验证
```

## 快速开始

```bash
cd lottery-analyzer/server
python -m venv .venv && .venv\Scripts\activate   # Windows（bash: source .venv/bin/activate）
pip install -r requirements.txt
python -m unittest discover -s tests -v          # 先跑测试（无网络依赖）
python run_server.py                             # 打开 http://127.0.0.1:8000/
```

Windows 一键启动：双击 `server/启动后端.bat`（自动建环境、装依赖、起服务、开网页）。
注意：页面必须经 `http://127.0.0.1:8000/` 访问，直接双击 `web/index.html`（file://）无法调用接口。

Android：Android Studio 打开 `android/`，同步后 `Build APK(s)`；或双击 `android/build_apk.bat`；本机无 SDK 时可用仓库自带的 GitHub Actions 工作流（`.github/workflows/build-apk.yml`）云端构建。模拟器默认连 `http://10.0.2.2:8000/`，真机在 App「设置」页改局域网 IP。详见 `docs/03`。

## 数据来源

- 双色球：中国福利彩票发行管理中心官网开奖公告（www.cwl.gov.cn）
- 大乐透：中国体育彩票官方接口（webapi.sporttery.cn，gameNo=85）

官方接口不可用时同步失败并记录日志，应用不会生成任何合成开奖数据。
