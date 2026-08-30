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


class TestAircraftSyncApi:
    """Task 4: 飞机同步路由（前置检查/后台线程/状态轮询/防重复）"""

    def test_sync_requires_session(self, client, ajax_headers, monkeypatch):
        import reqman.blueprints.cards_bp as cb_mod
        monkeypatch.setattr(cb_mod, "_require_amro_session", lambda: False)
        resp = client.post("/card/aircraft/amro-sync", headers=ajax_headers)
        assert resp.status_code == 401
        assert "登录已失效" in resp.get_json()["message"]

    def test_sync_start_and_status(self, client, app, ajax_headers, monkeypatch):
        import time as _time

        import reqman.blueprints.cards_bp as cb_mod
        from reqman.services import amro_sync
        monkeypatch.setattr(cb_mod, "_require_amro_session", lambda: True)

        def fake_sync(store, client_, cookies):
            async def _c():
                return {"added": 1, "updated": 2, "removed": [], "total_amro": 3}
            return _c()
        monkeypatch.setattr(amro_sync, "sync_aircraft", fake_sync)

        resp = client.post("/card/aircraft/amro-sync", headers=ajax_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["started"] is True

        meta = {}
        deadline = _time.time() + 5
        while _time.time() < deadline:
            meta = client.get("/card/aircraft/amro-status").get_json()["data"]
            if meta.get("status") == "done":
                break
            _time.sleep(0.05)
        assert meta.get("status") == "done", meta
        assert meta["report"]["added"] == 1 and meta["report"]["updated"] == 2
        # 飞机列表页渲染同步报告
        html = client.get("/card/aircraft").get_data(as_text=True)
        assert "同步报告" in html

    def test_sync_duplicate_start_conflict(self, client, app, ajax_headers, monkeypatch):
        import reqman.blueprints.cards_bp as cb_mod
        monkeypatch.setattr(cb_mod, "_require_amro_session", lambda: True)
        app.extensions["store"].set_amro_sync_meta("aircraft", {"status": "running"})
        resp = client.post("/card/aircraft/amro-sync", headers=ajax_headers)
        assert resp.status_code == 409
        app.extensions["store"].set_amro_sync_meta("aircraft", {"status": "done"})
