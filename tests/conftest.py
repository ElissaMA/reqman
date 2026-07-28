"""pytest 测试配置文件 — Fixtures & 测试数据工厂"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from reqman.models.json_store import JsonStore
from reqman.services.card_service import CardService

# ============================================================
# JSON Store Fixtures
# ============================================================


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """返回一个临时 JSON 数据库文件路径"""
    return str(tmp_path / "test_reqman.json")


@pytest.fixture
def json_store(tmp_db_path: str) -> JsonStore:
    """创建一个使用临时文件的空 JsonStore 实例"""
    return JsonStore(tmp_db_path)


@pytest.fixture
def prefilled_store(json_store: JsonStore) -> JsonStore:
    """创建一个预填充了测���数据的 JsonStore 实例"""
    store = json_store

    # 添加测试飞机
    store.add_aircraft(reg="B-1234", model="A320", engine="CFM56", fsn="1234", msn="5678", apu="APU-001")

    # 添加测试工卡组
    store.add_set(name="测试工卡组", description="测试用工卡组", category="发动机")

    # 添加测试工卡
    store.add(task_code="A320-TEST-001",
              task_name="���试工卡",
              category="发动机",
              task_type="A",
              remark="")

    return store


@pytest.fixture
def card_service(json_store: JsonStore) -> CardService:
    """创建一个绑定空 JsonStore 的 CardService 实例"""
    return CardService(store=json_store)


@pytest.fixture
def prefilled_service(prefilled_store: JsonStore) -> CardService:
    """创建一个绑定预填充 JsonStore 的 CardService 实例"""
    return CardService(store=prefilled_store)


# ============================================================
# 测试数据工厂
# ============================================================

def _ts() -> str:
    """返回当前时间戳字符串"""
    return datetime.now(timezone.utc).isoformat()


def make_card(**overrides: Any) -> dict:
    """创建工卡测试数据"""
    card = {
        "task_code": "TEST-001",
        "task_name": "测试工卡",
        "category": "发动机",
        "task_type": "A",
        "remark": "",
    }
    card.update(overrides)
    return card


def make_card_set(**overrides: Any) -> dict:
    """创建工卡组测试数据"""
    card_set = {
        "name": "测试工卡组",
        "description": "测试用",
        "category": "发动机",
    }
    card_set.update(overrides)
    return card_set


def make_form(**fields) -> dict:
    """创建模拟 Flask request.form 对象"""
    class MockForm:
        def getlist(self, key, default=None):
            return fields.get(key, default or [])

        def get(self, key, default=None):
            val = fields.get(key, default)
            if isinstance(val, list):
                return val[0] if val else default
            return val

    return MockForm()
