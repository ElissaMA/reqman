"""应用配置管理 — 环境变量驱动 + .env 文件加载"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Config:
    """全局配置类，所有配置从环境变量读取，提供默认值"""
    HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
    PORT: int = int(os.getenv("SERVER_PORT", "5001"))
    DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"

    BASE_DIR: Path = Path(__file__).resolve().parents[2]
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

    def __call__(self) -> None:
        self.DB_FILE.parent.mkdir(parents=True, exist_ok=True)


# 模块级常量 — 供蓝图直接从 config 导入
_cfg = Config()

BASE_DIR: Path = _cfg.BASE_DIR
DB_FILE: Path = _cfg.DB_FILE
TEMPLATE_FILE: Path = _cfg.TEMPLATE_FILE
CATEGORIES: list[str] = _cfg.CATEGORIES
TASK_TYPES: list[str] = _cfg.TASK_TYPES
USAGE_TYPES: list[str] = _cfg.USAGE_TYPES
CONDITIONS: list[str] = _cfg.CONDITIONS
