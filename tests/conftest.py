"""pytest 测试配置文件 — Fixtures & 测试数据工厂"""

from pathlib import Path

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
    store.add(task_code="A320-TEST-002",
              task_name="测试工卡二",
              category="机体",
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
