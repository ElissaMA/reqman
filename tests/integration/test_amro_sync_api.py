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


class TestAmroPackageApi:
    """Task 5: 工作包直读（amro-fetch）与版本变动日志"""

    def test_fetch_imports_and_matches(self, client, app, ajax_headers, monkeypatch):
        import reqman.services.connectors.amro as amro_mod
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)

        base_row = {"REVNR": "66A", "ACNO": "B-1662", "ACTYPE": "A320-232", "ENGTYPE": "V2500",
                    "REVTITLE": "A320 4C检", "CHKTP": "4C", "PLANSTD": "2026-09-01"}

        async def fake_fetch(client_, cookies, plugin, base_form, **kw):
            if plugin == "BM_TSK_002_LIST":
                return [dict(base_row, JCNO="CSCA320-256652-01-1-X", TASK="RST",
                             ZY="机身", JCTITLE="检查救生衣", PPCBZSM="")]
            return [dict(base_row, JCNO="EOJC-A320-31-2026-007-A", TASK="EO",
                         ZY="电子", JCTITLE="实时数据改装", PPCBZSM="")]
        monkeypatch.setattr(amro_mod, "fetch_all_pages", fake_fetch)

        resp = client.post("/packages/amro-fetch", data={"revnr": "66A"}, headers=ajax_headers)
        assert resp.status_code == 200
        summary = resp.get_json()["data"]
        assert summary["routine"] == 1 and summary["other"] == 1

        pkg = app.extensions["store"].get_work_package(summary["package_id"])
        assert pkg["is_matched"] is True
        assert pkg["routine_count"] == 1 and pkg["other_count"] == 1
        # 机身→机体 映射与来源标注
        codes = {i["task_code"]: i for i in pkg["all_items"]}
        assert codes["CSCA320-256652-01-1-X"]["category"] == "机体"
        assert codes["EOJC-A320-31-2026-007-A"]["source"] == "其他"
        # 同 reg+description 重复导入覆盖（沿用现有幂等语义）
        resp2 = client.post("/packages/amro-fetch", data={"revnr": "66A"}, headers=ajax_headers)
        assert resp2.get_json()["data"]["package_id"] == summary["package_id"]

    def test_fetch_requires_session(self, client, ajax_headers, monkeypatch):
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: False)
        resp = client.post("/packages/amro-fetch", data={"revnr": "66A"}, headers=ajax_headers)
        assert resp.status_code == 401

    def test_version_logs_view(self, client, store):
        """版本变动日志：card_logs 筛选视图（JSON API + 页面区块）"""
        r = store.add("VLOG-1", "卡", "机体", "", "")
        store.update(r["id"], task_name="改名")                    # 非版本日志
        store.update(r["id"], write_date="2026-08-01 09:00:00")   # 版本日志
        data = client.get("/packages/amro-version-logs").get_json()["data"]
        assert len(data["logs"]) == 1
        row = data["logs"][0]
        assert row["task_code"] == "VLOG-1" and row["new"] == "2026-08-01 09:00:00"

        html = client.get("/upload").get_data(as_text=True)
        assert "工卡版本变动日志" in html and "VLOG-1" in html


class TestVersionCheckApi:
    """Task 6: 全库版本检查（后台线程 + 改版清单下载）"""

    def test_check_requires_session(self, client, ajax_headers, monkeypatch):
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: False)
        resp = client.post("/card/amro-version-check", headers=ajax_headers)
        assert resp.status_code == 401

    def test_check_start_status_and_report(self, client, app, ajax_headers, monkeypatch, tmp_path):
        import time as _time

        import reqman.blueprints.cards_bp as cb_mod
        import reqman.services.connectors.amro as amro_mod
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        monkeypatch.setattr(cb_mod, "OUTPUT_DIR", tmp_path)

        async def fake_fetch(client_, cookies, plugin, base_form, **kw):
            if plugin == "TD_JC_SMJC_LIST":
                return [_jcrow("CSCA320-256652-01-1-X", "2026-08-01 09:00:00")]
            return [_jcrow("EOJC-A320-31-2026-007-A", "2026-07-15 14:00:00", task="EO")]
        monkeypatch.setattr(amro_mod, "fetch_all_pages", fake_fetch)

        # 库内卡：1 张改版 + 1 张库内没有（作废）
        store_add(app, "CSCA320-256652-01-1-X", "检查救生衣")
        store_add(app, "EOJC-A320-57-2025-002-B", "旧EO卡")

        resp = client.post("/card/amro-version-check", headers=ajax_headers)
        assert resp.status_code == 200

        meta = {}
        deadline = _time.time() + 5
        while _time.time() < deadline:
            meta = client.get("/card/amro-version-status").get_json()["data"]
            if meta.get("status") == "done":
                break
            _time.sleep(0.05)
        assert meta.get("status") == "done", meta
        assert meta["report"]["revised"] and meta["report"]["cancelled"]
        fname = meta["report"]["filename"]

        dl = client.get(f"/card/amro-version-report/{fname.replace('amro_version_report_', '').replace('.xlsx', '')}")
        assert dl.status_code == 200
        # 非法 ts 被拒（防路径穿越）
        assert client.get("/card/amro-version-report/..%5Cevil").status_code in (400, 404)


def _jcrow(jcno, wd, **kw):
    row = {"JC_NO": jcno, "WRITE_DATE": wd}
    row.update(kw)
    return row


def store_add(app, code, name):
    return app.extensions["store"].add(code, name, "机体", "", "")


class TestReminderAsync:
    """Task 7: 提醒单异步版本检查（task 状态机 + 蓝底区块 + 旧同步路径保留）"""

    @staticmethod
    def _make_package(store):
        store.add(task_code="E-001", task_name="电子例行卡", category="电子")
        store.update(store.find_by_code("E-001")["id"], tools_confirmed=True,
                     materials_confirmed=True, reminder_type="重点提醒",
                     reminder_confirmed=True, card_ok=True)
        store.save_work_package({
            "reg": "B-1234", "description": "46A", "date": "2026.08.23",
            "aircraft_info": {"reg": "B-1234", "type": "A320", "description": "46A",
                              "date": "2026.08.23"},
            "matched": [{"task_code": "E-001", "task_name": "电子例行卡",
                         "category": "电子", "reminder_type": "重点提醒",
                         "card_ok": True, "reminder_confirmed": True,
                         "source": "例行", "tools": [], "materials": []}],
            "new_cards": [], "cancelled": [],
            "all_items": [{"task_code": "E-001", "task_name": "电子例行卡",
                           "category": "电子", "source": "例行"}],
            "routine_count": 1, "other_count": 0,
            "is_matched": True, "generated_at": "2026.08.23 10:00",
        })
        return store.get_work_packages()[0]["package_id"]

    def test_async_flow_done_and_download(self, client, store, app, ajax_headers,
                                          monkeypatch, tmp_path):
        import time as _time
        import reqman.blueprints.generate_bp as gb_mod
        monkeypatch.setattr(gb_mod, "OUTPUT_DIR", tmp_path)

        # mock 在 AMRO 层：真实 check_cards_against_amro 会更新卡的 write_date
        import reqman.services.connectors.amro as amro_mod

        async def fake_fetch(client_, cookies, plugin, base_form, **kw):
            return [{"JC_NO": "E-001", "WRITE_DATE": "2026-08-01 09:00:00", "ZY": "电子",
                     "JCTITLE": "电子例行卡", "TASK": "RST"}]
        monkeypatch.setattr(amro_mod, "fetch_all_pages", fake_fetch)

        pkg_id = self._make_package(store)
        resp = client.post("/generate/reminder",
                           data={"package_id": pkg_id, "version_check": "1"},
                           headers=ajax_headers)
        assert resp.status_code == 200
        task_id = resp.get_json()["data"]["task_id"]

        meta = {}
        deadline = _time.time() + 5
        while _time.time() < deadline:
            meta = client.get(f"/generate/task/{task_id}").get_json()["data"]
            if meta.get("status") == "done":
                break
            _time.sleep(0.05)
        assert meta.get("status") == "done", meta
        assert meta["revised"] == 1
        # 卡的 write_date 已被实时检查更新
        assert store.find_by_code("E-001")["write_date"] == "2026-08-01 09:00:00"
        # 下载含版本区块的提醒单
        dl = client.get(f"/generate/task/{task_id}/download")
        assert dl.status_code == 200 and "spreadsheetml" in dl.mimetype

    def test_unknown_task_404(self, client, ajax_headers):
        resp = client.get("/generate/task/nonexistent", headers=ajax_headers)
        assert resp.status_code == 404

    def test_sync_path_preserved_without_checkbox(self, client, store):
        """不勾选版本检查 → 旧同步路径直接返回 xlsx（保留一个版本的开关）"""
        pkg_id = self._make_package(store)
        resp = client.post("/generate/reminder", data={"package_id": pkg_id})
        assert resp.status_code == 200 and "spreadsheetml" in resp.mimetype
