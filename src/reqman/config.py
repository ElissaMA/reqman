"""应用配置管理 — 环境变量驱动 + .env 文件加载"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR: Path = Path(__file__).resolve().parents[2]

HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
PORT: int = int(os.getenv("SERVER_PORT", "5001"))
DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"

DB_FILE: Path = BASE_DIR / os.getenv("DB_FILE", "data/reqman_db.json")
TEMPLATE_FILE: Path = BASE_DIR / os.getenv("TEMPLATE_FILE", "assets/demand_template.xlsx")

CATEGORIES: list[str] = os.getenv(
    "CATEGORIES", "发动机,机体,电子,特检,支援"
).split(",")

TASK_TYPES: list[str] = os.getenv(
    "TASK_TYPES", "A,EO分段,DP项目,20MO,24MO"
).split(",")

USAGE_TYPES: list[str] = ["必须使用", "检查有问题领用"]

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
