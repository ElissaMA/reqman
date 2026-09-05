"""工卡管理蓝图 — 工卡 CRUD + 工卡组管理 + 飞机信息 + AMRO 版本检查

包拆分：子模块按职责划分（card_routes / set_routes / aircraft_routes / helpers），
路由统一注册到本模块创建的 cards_bp 蓝图实例；OUTPUT_DIR 经包级属性运行时取值，
以便测试 monkeypatch reqman.blueprints.cards_bp.OUTPUT_DIR 生效。
"""
from flask import Blueprint

from ...config import OUTPUT_DIR

cards_bp = Blueprint("cards", __name__)

from . import (  # noqa: F401  (仅触发子模块路由注册，无需直接使用)
    aircraft_routes,
    card_routes,
    set_routes,
)

__all__ = ["OUTPUT_DIR", "cards_bp"]
