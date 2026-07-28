"""集成测试配置 — Flask 测试客户端、临时数据库、测试数据工厂"""

from pathlib import Path

import pytest
from flask.testing import FlaskClient

# ============================================================
# Flask App Fixtures
# ============================================================

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """创建一个使用临时数据库的 Flask 测试应用（模块级复用）"""
    tmp_dir = tmp_path_factory.mktemp("reqman_inttest")
    db_path = str(tmp_dir / "test_reqman.json")

    # 覆写配置后创建应用
    from reqman import config
    original_db = config.DB_FILE
    config.DB_FILE = Path(db_path)

    from reqman import create_app
    from reqman.models.json_store import JsonStore
    from reqman.services.card_service import CardService

    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    # 重建 store + card_service（指向临时文件）
    store = JsonStore(db_path)
    app.extensions['store'] = store
    app.extensions['card_service'] = CardService(store)

    yield app

    config.DB_FILE = original_db


@pytest.fixture
def client(app) -> FlaskClient:
    """Flask 测试客户端"""
    with app.test_client() as c:
        yield c


@pytest.fixture
def ajax_headers() -> dict:
    """模�� AJAX 请求头"""
    return {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def store(app):
    """获取应用中的 store 实例"""
    return app.extensions['store']


@pytest.fixture
def svc(app):
    """获取应用中的 card_service 实例"""
    return app.extensions['card_service']


# ============================================================
# 预填充数据 Fixtures
# ============================================================

@pytest.fixture
def prefilled_app(app, store, svc):
    """预填充基础数据到 store 并返回应用"""
    # 工卡
    store.add(task_code="ENG-001", task_name="发动机检查", category="发动机",
              task_type="A", remark="")
    store.add(task_code="ENG-002", task_name="发动机拆装", category="发动机",
              task_type="A", remark="")
    store.add(task_code="AIR-001", task_name="机身蒙皮检查", category="机体",
              task_type="A", remark="")
    store.add(task_code="AVN-001", task_name="电子设备测试", category="电子",
              task_type="A", remark="")
    store.add(task_code="SPECIAL-001", task_name="NDT 检查", category="特检",
              task_type="A", remark="")

    # 工卡���
    store.add_set(name="发动机定期检查", description="发动机定期检查组", category="发动机")
    store.update_set(store.get_all_sets()[0]["id"], tools=[
        {"device_name": "力矩扳手", "part_number": "TRQ-001", "quantity": "1"}
    ])

    # 飞机
    store.add_aircraft(reg="B-1234", model="A320", engine="CFM56",
                       fsn="1234", msn="5678", apu="APU-001")
    store.add_aircraft(reg="B-5678", model="B737", engine="CFM56-7B",
                       fsn="5678", msn="9012", apu="APU-002")

    return app


@pytest.fixture
def prefilled_client(prefilled_app) -> FlaskClient:
    """预填充数据的测试客户端"""
    with prefilled_app.test_client() as c:
        yield c


# ============================================================
# 测试数据工厂
# ============================================================

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


def make_card_form(task_code="TEST-001", task_name="测试工卡",
                   category="发动机", task_type="A",
                   tools=None, materials=None) -> dict:
    """生成模拟工卡表单数据"""
    data = {
        "task_code": task_code,
        "task_name": task_name,
        "category": category,
        "task_type": task_type,
    }
    if tools:
        for i, t in enumerate(tools):
            data.setdefault("tool_name[]", []).append(t.get("device_name", ""))
            data.setdefault("tool_pn[]", []).append(t.get("part_number", ""))
            data.setdefault("tool_qty[]", []).append(t.get("quantity", "1"))
            data.setdefault("tool_remark[]", []).append(t.get("remark", ""))
            data.setdefault("tool_type[]", []).append(t.get("usage_type", "必须使用"))
    if materials:
        for i, m in enumerate(materials):
            data.setdefault("mat_name[]", []).append(m.get("material_name", ""))
            data.setdefault("mat_pn[]", []).append(m.get("part_number", ""))
            data.setdefault("mat_qty[]", []).append(m.get("quantity", "1"))
            data.setdefault("mat_remark[]", []).append(m.get("remark", ""))
            data.setdefault("mat_type[]", []).append(m.get("usage_type", "必须使用"))
    return data
