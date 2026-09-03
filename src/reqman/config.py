"""应用配置管理 — 环境变量驱动 + .env 文件加载"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR: Path = Path(__file__).resolve().parents[2]

HOST: str = os.getenv(
    "SERVER_HOST",
    "0.0.0.0" if os.getenv("FLASK_ENV", "development") == "production" else "127.0.0.1",
)
PORT: int = int(os.getenv("SERVER_PORT", "5001"))
DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"

DB_FILE: Path = BASE_DIR / os.getenv("DB_FILE", "data/reqman_db.json")
# 作废工卡独立存储（与主库分离，降低主库读写体积；gitignore 已忽略 data/）
CANCELLED_CARDS_FILE: Path = BASE_DIR / os.getenv("CANCELLED_CARDS_FILE", "data/cancelled_cards.json")
TEMPLATE_FILE: Path = BASE_DIR / os.getenv("TEMPLATE_FILE", "assets/demand_template.xlsx")
REMINDER_TEMPLATE_FILE: Path = BASE_DIR / os.getenv("REMINDER_TEMPLATE_FILE", "assets/reminder_template.xlsx")
CHECK_TEMPLATE_FILE: Path = BASE_DIR / os.getenv("CHECK_TEMPLATE_FILE", "assets/check_template.xlsx")

CATEGORIES: list[str] = os.getenv(
    "CATEGORIES", "发动机,机体,电子,特检,支援"
).split(",")

# 专业排序优先级（越小越靠前）：报告分组/改版清单分专业共用单一来源
CATEGORY_ORDER: dict[str, int] = {"发动机": 0, "机体": 1, "电子": 2}

TASK_TYPES: list[str] = os.getenv(
    "TASK_TYPES", "A,EO分段,DP项目,20MO,24MO"
).split(",")

USAGE_TYPES: list[str] = ["必须使用", "检查有问题领用"]

REMINDER_TYPES: list[str] = os.getenv(
    "REMINDER_TYPES", "一般提醒,重点提醒"
).split(",")

CONDITIONS: list[str] = [
    "机位用电",
    "定检机位",
    "试大车机位",
    "试大车人员",
    "ELT测试",
    "ATC测试",
    "机库需求",
    "后续航班运行建议",
    "AOG带件情况",
]

SECRET_KEY: str = os.getenv("SECRET_KEY") or os.urandom(24).hex()
MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024

# 自动创建必要目录
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------- AMRO 库存查询 ----------
# 只读白名单与端点基座集中在 connectors/amro.py（READONLY_PLUGINS / AMRO_API_BASE），
# 库存实际调用经 query_plugin，此处仅保留配置项。
AMRO_COOKIE_FILE: Path = BASE_DIR / os.getenv("AMRO_COOKIE_FILE", "data/cookie/amro_cookies.json")
AMRO_MAX_CONCURRENT: int = int(os.getenv("AMRO_MAX_CONCURRENT", "10"))
AMRO_SESSION_TTL: int = int(os.getenv("AMRO_SESSION_TTL", "7200"))  # 2 小时
AMRO_LOGIN_VERSION: str = os.getenv("AMRO_LOGIN_VERSION", "3")
# 登录脚本 ZIP 注入的公网地址（服务器部署建议配置，保证多用户下载的 ZIP 注入地址一致可达；未配置回退当前访问地址）
AMRO_PUBLIC_URL: str = os.getenv("AMRO_PUBLIC_URL", "").rstrip("/")

# ---------- AMRO 三域同步（v3.5.0） ----------
AMRO_RATE_SECONDS: float = float(os.getenv("AMRO_RATE_SECONDS", "1"))  # 两次 AMRO 请求最小间隔（秒，2026-09-03 由 2 放宽至 1）
AMRO_AUDIT_FILE: Path = BASE_DIR / os.getenv("AMRO_AUDIT_FILE", "data/amro_audit.jsonl")  # 只读调用审计留痕
AMRO_AC_FLEET: str = os.getenv("AMRO_AC_FLEET", "A320")  # 飞机同步机族过滤（在册判定）
AMRO_BASE_DEFAULT: str = os.getenv("AMRO_BASE_DEFAULT", "KM01")  # 工作包默认基地代码
AMRO_CARD_FLEET: str = os.getenv("AMRO_CARD_FLEET", "A320")  # 工卡版本清单机队筛选（EOJC 已实测支持 fleet）

# 库存查询输出暂存目录（gitignore 已忽略）
OUTPUT_DIR: Path = BASE_DIR / os.getenv("OUTPUT_DIR", "output")

# 自动创建 cookie 目录
AMRO_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
