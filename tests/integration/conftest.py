"""集成测试配置 — Flask 测试客户端、临时数据库、测试数据工厂"""

import pytest
from flask.testing import FlaskClient

# ============================================================
# Flask App Fixtures
# ============================================================

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """创建一个使用临时数据库/临时凭证的 Flask 测试应用（模块级复用）。

    路径经 create_app(db_file=..., cookie_file=...) 显式注入——
    改 config 模块属性对包级 import 绑定的常量无效（旧写法曾导致
    app 先对真实 data/reqman_db.json 实例化再手工重注入救回）。
    """
    tmp_dir = tmp_path_factory.mktemp("reqman_inttest")

    from reqman import create_app

    app = create_app(db_file=str(tmp_dir / "test_reqman.json"),
                     cookie_file=str(tmp_dir / "amro_cookies.json"))
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    yield app


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
    """预填充基础数据到 store 并返回应用（幂等：飞机/工卡组已存在则跳过，防跨用例累积）"""
    # 工卡（add 对重复工卡号本身幂等返回 None）
    for code, name, category in [
        ("ENG-001", "发动机检查", "发动机"),
        ("ENG-002", "发动机拆装", "发动机"),
        ("AIR-001", "机身蒙皮检查", "机体"),
        ("AVN-001", "电子设备测试", "电子"),
        ("SPECIAL-001", "NDT 检查", "特检"),
    ]:
        store.add(task_code=code, task_name=name, category=category, task_type="A", remark="")

    # 工卡组（按名幂等）
    if not any(s.get("name") == "发动机定期检查" for s in store.get_all_sets()):
        store.add_set(name="发动机定期检查", description="发动机定期检查组", category="发动机")
        store.update_set(store.get_all_sets()[0]["id"], tools=[
            {"device_name": "力矩扳手", "part_number": "TRQ-001", "quantity": "1"}
        ])

    # 飞机（按机号幂等）
    for reg, model, engine, fsn, msn, apu in [
        ("B-1234", "A320", "CFM56", "1234", "5678", "APU-001"),
        ("B-5678", "B737", "CFM56-7B", "5678", "9012", "APU-002"),
    ]:
        if store.find_aircraft_by_reg(reg) is None:
            store.add_aircraft(reg=reg, model=model, engine=engine,
                               fsn=fsn, msn=msn, apu=apu)

    return app


@pytest.fixture
def prefilled_client(prefilled_app) -> FlaskClient:
    """预填充数据的测试客户端"""
    with prefilled_app.test_client() as c:
        yield c
