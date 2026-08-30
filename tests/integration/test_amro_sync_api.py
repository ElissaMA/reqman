"""AMRO 三域同步集成测试 — Task 2: 表头登录三件套 + /inventory 简化"""
import io
import zipfile

import pytest


@pytest.fixture(autouse=True)
def isolated_inventory(app, tmp_path, monkeypatch):
    """隔离登录凭证缓存与输出目录到临时目录，避免污染 data/cookie/ 与 output/。"""
    from reqman.services.connectors.session import LoginSessionStore
    from reqman.services.inventory_service import InventoryService

    app.extensions["inventory_service"] = InventoryService(
        LoginSessionStore(tmp_path / "session.json", ttl_seconds=7200)
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    import reqman.blueprints.inventory_bp as bp_mod
    monkeypatch.setattr(bp_mod, "OUTPUT_DIR", out_dir)
    import reqman.services.inventory_service as inv_mod
    monkeypatch.setattr(inv_mod, "OUTPUT_DIR", out_dir)
    yield out_dir


class TestHeaderLogin:
    """Task 2: AMRO 登录三件套迁表头，库存查询页只留查询"""

    def test_setup_package_contains_protocol_bat(self, client):
        resp = client.get("/inventory/setup-package")
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            assert "register_protocol.bat" in zf.namelist()
            bat = zf.read("register_protocol.bat").decode("utf-8")
            assert "ReqManLogin" in bat          # 协议名
            assert "reg add" in bat              # 注册动作
            assert "Desktop" in bat              # 桌面路径检测

    def test_session_endpoint_unchanged(self, client):
        resp = client.get("/inventory/session")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "ready" in body["data"]

    def test_inventory_page_moves_login_to_header(self, client):
        """登录区块迁表头后，库存查询页不再含状态卡与配置按钮，表头三件套就位"""
        html = client.get("/inventory").get_data(as_text=True)
        assert 'id="sessionCard"' not in html        # ① 状态卡移除
        assert 'id="checkConfigBtn"' not in html     # ② 检查配置按钮移除
        assert 'id="guideBtn"' not in html           # ③ 使用指引按钮移除
        assert 'id="amroStatus"' in html             # 表头状态徽章
        assert "ReqManLogin://" in html              # 一键登录协议入口
        assert 'id="zoneDemand"' in html             # 查询区保留
