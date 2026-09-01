"""AMRO 三域同步集成测试 — Task 2: 表头登录三件套 + /inventory 简化"""
import io
import json
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
    import reqman.services.amro_sync as amro_sync_mod
    monkeypatch.setattr(amro_sync_mod, "OUTPUT_DIR", out_dir)   # 查询结果简述持久化隔离
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
            assert "%~dp0start_login.bat" in bat  # 协议自定位（解压任意位置有效）
            assert "Desktop" not in bat          # 不再依赖桌面路径

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

        status = {}
        deadline = _time.time() + 5
        while _time.time() < deadline:
            status = client.get("/card/aircraft/amro-status").get_json()["data"]
            if status.get("status") == "done":
                break
            _time.sleep(0.05)
        assert status.get("status") == "done", status
        assert status["summary"]["added"] == 1 and status["summary"]["updated"] == 2
        # 飞机列表页渲染持久状态栏（上次查询简述）
        html = client.get("/card/aircraft").get_data(as_text=True)
        assert "上次查询" in html and "新增 1 架" in html

    def test_sync_duplicate_start_conflict(self, client, app, ajax_headers, monkeypatch):
        """全局互斥：已有查询在跑 → 409 + 统一 busy 文案（不排队）。"""
        import reqman.blueprints.cards_bp as cb_mod
        monkeypatch.setattr(cb_mod, "_require_amro_session", lambda: True)
        release = _occupy_query_slot("查询飞机数据")
        try:
            resp = client.post("/card/aircraft/amro-sync", headers=ajax_headers)
            assert resp.status_code == 409
            msg = resp.get_json()["message"]
            assert "已有查询任务进行中" in msg and "查询飞机数据" in msg
        finally:
            release()


class TestAmroPackageApi:
    """Task 5: 工作包直读（amro-fetch）与版本变动日志"""

    def test_fetch_imports_and_matches(self, client, app, ajax_headers, monkeypatch):
        import reqman.services.connectors.amro as amro_mod
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)

        base_row = {"REVNR": "66A", "ACNO": "B-1662", "ACTYPE": "A320-232", "ENGTYPE": "V2500",
                    "REVTITLE": "A320 4C检", "CHKTP": "4C", "PLANSTD": "2026-09-01 08:00:00",
                    "ZRFD": "云南定检中队一分队(主),云南定检中队二分队", "LIMH": "170"}

        async def fake_fetch(client_, cookies, plugin, base_form, **kw):
            if plugin == "BM_TSK_002_LIST":
                return [dict(base_row, JCNO="CSCA320-256652-01-1-X", TASK="RST",
                             ZY="机身", JCTITLE="检查救生衣", PPCBZSM="")]
            return [dict(base_row, JCNO="EOJC-A320-31-2026-007-A", TASK="EO",
                         ZY="电子", JCTITLE="实时数据改装", PPCBZSM="")]
        monkeypatch.setattr(amro_mod, "fetch_all_pages", fake_fetch)

        form = {"revnr": "66A", "header": json.dumps(base_row)}
        resp = client.post("/packages/amro-fetch", data=form, headers=ajax_headers)
        assert resp.status_code == 200
        summary = resp.get_json()["data"]
        assert summary["routine"] == 1 and summary["other"] == 1

        pkg = app.extensions["store"].get_work_package(summary["package_id"])
        assert pkg["is_matched"] is False          # 导入仅入库，不匹配（与 Excel 一致）
        assert pkg["generated_at"] is None         # 生成日期匹配后才记
        assert pkg["routine_count"] == 1 and pkg["other_count"] == 1
        # 包头字段来自前端选中的列表行（机号/描述/日期/分队/工时）
        assert pkg["reg"] == "B-1662"
        assert pkg["description"] == "A320 4C检"
        assert pkg["date"] == "2026.09.01"
        info = pkg["aircraft_info"]
        assert info["type"] == "A320-232" and info["engine"] == "V2500"
        assert info["squadron"] == "云南定检中队一分队"          # 剥掉“(主)”
        assert info["plan_hours"] == "170"
        # 机身→机体 映射与来源标注
        codes = {i["task_code"]: i for i in pkg["all_items"]}
        assert codes["CSCA320-256652-01-1-X"]["category"] == "机体"
        assert codes["EOJC-A320-31-2026-007-A"]["source"] == "其他"
        # 同 reg+description 重复导入覆盖（沿用现有幂等语义）
        resp2 = client.post("/packages/amro-fetch", data=form, headers=ajax_headers)
        assert resp2.get_json()["data"]["package_id"] == summary["package_id"]

    def test_fetch_requires_session(self, client, ajax_headers, monkeypatch):
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: False)
        resp = client.post("/packages/amro-fetch", data={"revnr": "66A"}, headers=ajax_headers)
        assert resp.status_code == 401

    def test_upload_keeps_last_package_query(self, client, ajax_headers, monkeypatch):
        """查询结果跨页保留：amro-list 成功后 /upload 注入快照行 + fetched_at 摘要。"""
        import reqman.services.connectors.amro as amro_mod
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        monkeypatch.setattr(amro_sync, "_last_package_query", {})

        row = {"REVNR": "66B", "ACNO": "B-1662", "ACTYPE": "A320-232", "ENGTYPE": "V2500",
               "REVTITLE": "A320 4C检", "CHKTP": "4C", "PLANSTD": "2026-09-01",
               "ZRFD": "云南定检中队一分队(主)", "LIMH": "170"}

        async def fake_fetch(client_, cookies, plugin, base_form, **kw):
            return {"code": 200, "data": [row]}
        monkeypatch.setattr(amro_mod, "query_plugin", fake_fetch)

        resp = client.post("/packages/amro-list", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert len(data["packages"]) == 1 and data["fetched_at"]

        html = client.get("/upload").get_data(as_text=True)
        assert '"66B"' in html and '"B-1662"' in html   # 快照行注入页面
        assert '"fetched_at"' in html                   # 日期摘要数据随页面注入

    def test_list_busy_conflict(self, client, ajax_headers, monkeypatch):
        """全局互斥：查询工作包列表在已有查询时 → 409。"""
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        release = _occupy_query_slot("查询飞机数据")
        try:
            resp = client.post("/packages/amro-list", headers=ajax_headers)
            assert resp.status_code == 409
            assert "已有查询任务进行中" in resp.get_json()["message"]
        finally:
            release()

    def test_fetch_busy_conflict(self, client, ajax_headers, monkeypatch):
        """全局互斥：导入工作包在已有查询时 → 409。"""
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        release = _occupy_query_slot("查询飞机数据")
        try:
            resp = client.post("/packages/amro-fetch", data={"revnr": "66A"},
                               headers=ajax_headers)
            assert resp.status_code == 409
            assert "已有查询任务进行中" in resp.get_json()["message"]
        finally:
            release()

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

    def test_check_busy_conflict(self, client, app, ajax_headers, monkeypatch):
        """全局互斥：全量查询工卡版本在已有查询时 → 409（不排队）。"""
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        release = _occupy_query_slot("查询库存")
        try:
            resp = client.post("/card/amro-version-check", headers=ajax_headers)
            assert resp.status_code == 409
            msg = resp.get_json()["message"]
            assert "已有查询任务进行中" in msg and "查询库存" in msg
        finally:
            release()

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
        assert meta["summary"]["revised"] and meta["summary"]["cancelled"]
        assert meta["summary"]["filename"].startswith("amro_full_version_report_")

        dl = client.get("/card/amro-version-report")
        assert dl.status_code == 200
        from urllib.parse import unquote
        assert "工卡改版提醒单（全量）" in unquote(dl.headers["Content-Disposition"])


def _jcrow(jcno, wd, **kw):
    row = {"JC_NO": jcno, "WRITE_DATE": wd}
    row.update(kw)
    return row


def _occupy_query_slot(label: str):
    """占用全局查询槽（带重试，等待前一任务 daemon 线程释放）。返回释放函数。"""
    import time as _time

    from reqman.services import amro_sync
    deadline = _time.time() + 3
    while _time.time() < deadline:
        if amro_sync.try_begin_query(label):
            return amro_sync.end_query
        _time.sleep(0.02)
    raise AssertionError(f"query slot still busy, cannot occupy for {label}")


def store_add(app, code, name):
    return app.extensions["store"].add(code, name, "机体", "", "")


class TestPackageVersionApi:
    """步骤4：工作包行级版本检查（同步）+ 预览页改版清单下载 + 提醒单回退纯同步"""

    @staticmethod
    def _make_package(store, days_ahead: int = 1):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        pkg_date = (today + timedelta(days=days_ahead)).strftime("%Y.%m.%d")
        for code, name, cat in (("E-001", "电子例行卡", "电子"), ("J-001", "机体例行卡", "机体")):
            store.add(task_code=code, task_name=name, category=cat)
            store.update(store.find_by_code(code)["id"], tools_confirmed=True,
                         materials_confirmed=True, reminder_type="重点提醒",
                         reminder_confirmed=True, card_ok=True)
        return store.save_work_package({
            "reg": "B-1234", "description": "46A", "date": pkg_date,
            "aircraft_info": {"reg": "B-1234", "type": "A320", "description": "46A",
                              "date": pkg_date},
            "matched": [{"task_code": code, "task_name": name, "category": cat,
                         "reminder_type": "重点提醒", "card_ok": True,
                         "reminder_confirmed": True, "source": "例行",
                         "tools": [], "materials": []}
                        for code, name, cat in (("E-001", "电子例行卡", "电子"),
                                                ("J-001", "机体例行卡", "机体"))],
            "new_cards": [], "cancelled": [],
            "all_items": [{"task_code": code, "task_name": name, "category": cat, "source": "例行"}
                          for code, name, cat in (("E-001", "电子例行卡", "电子"),
                                                  ("J-001", "机体例行卡", "机体"))],
            "routine_count": 2, "other_count": 0,
            "is_matched": True, "generated_at": "2026.08.23 10:00",
        })["package_id"]

    def test_package_version_check_sync(self, client, app, ajax_headers, monkeypatch, tmp_path):
        """行级查询工作包工卡版本：同步比对 → 更新版本 → 生成逐包改版清单（同包覆盖）。

        包内卡非 CSCA 前缀（E/J 例）→ 走 TD_JC_ALL_GET_ENTITY_BY_JCNO 逐卡直查。
        """
        import reqman.blueprints.packages_bp as pb_mod
        import reqman.services.connectors.amro as amro_mod
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        monkeypatch.setattr(pb_mod, "OUTPUT_DIR", tmp_path)

        entity_rows = {
            "E-001": {"JC_NO": "E-001", "WRITE_DATE": "2026-08-01 09:00:00", "ZY": "电子",
                      "JCTITLE": "电子例行卡", "TASK": "RST"},
            "J-001": {"JC_NO": "J-001", "WRITE_DATE": "2026-08-01 09:00:00", "ZY": "机体",
                      "JCTITLE": "机体例行卡", "TASK": "RST"},
        }

        async def fake_query(client_, cookies, plugin, form, **kw):
            return {"code": 200, "data": entity_rows.get(form.get("jcno"), {})}
        monkeypatch.setattr(amro_mod, "query_plugin", fake_query)

        store = app.extensions["store"]
        pkg_id = self._make_package(store)
        resp = client.post(f"/packages/{pkg_id}/amro-version-check", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["revised"] == 2 and data["cancelled"] == 0
        assert data["filename"] == f"amro_pkg_version_report_{pkg_id}.xlsx"
        assert (tmp_path / data["filename"]).exists()
        assert store.find_by_code("E-001")["write_date"] == "2026-08-01 09:00:00"
        # 持久摘要显示机号+描述，而非 package_id 编号串
        last = amro_sync.get_last_query_result("package_version", output_dir=tmp_path)
        assert "B-1234 46A" in last["summary"]
        assert pkg_id not in last["summary"]

    def test_package_version_check_busy_409(self, client, app, ajax_headers, monkeypatch):
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        pkg_id = self._make_package(app.extensions["store"])
        release = _occupy_query_slot("查询飞机数据")
        try:
            resp = client.post(f"/packages/{pkg_id}/amro-version-check", headers=ajax_headers)
            assert resp.status_code == 409
            assert "已有查询任务进行中" in resp.get_json()["message"]
        finally:
            release()

    def test_package_version_check_missing_404(self, client, ajax_headers, monkeypatch):
        from reqman.services import amro_sync
        monkeypatch.setattr(amro_sync, "require_amro_session", lambda: True)
        resp = client.post("/packages/nope/amro-version-check", headers=ajax_headers)
        assert resp.status_code == 404

    def test_report_download_404_without_query(self, client, monkeypatch, tmp_path):
        import reqman.blueprints.generate_bp as gb_mod
        monkeypatch.setattr(gb_mod, "OUTPUT_DIR", tmp_path)
        resp = client.get("/generate/package-version-report?package_id=p1")
        assert resp.status_code == 404
        assert "尚未查询" in resp.get_json()["message"]

    def test_report_download_chinese_name(self, client, app, monkeypatch, tmp_path):
        """逐包改版清单下载名 = 工卡改版提醒单（机号 描述）日期.xlsx（与预览页同路由同文件名）。"""
        from urllib.parse import unquote

        import reqman.blueprints.generate_bp as gb_mod
        monkeypatch.setattr(gb_mod, "OUTPUT_DIR", tmp_path)
        pkg_id = self._make_package(app.extensions["store"])
        (tmp_path / f"amro_pkg_version_report_{pkg_id}.xlsx").write_bytes(b"x")
        resp = client.get(f"/generate/package-version-report?package_id={pkg_id}")
        assert resp.status_code == 200
        disp = unquote(resp.headers["Content-Disposition"])
        assert "工卡改版提醒单（B-1234 46A）" in disp
        assert ".xlsx" in disp

    def test_report_download_ok(self, client, monkeypatch, tmp_path):
        import reqman.blueprints.generate_bp as gb_mod
        monkeypatch.setattr(gb_mod, "OUTPUT_DIR", tmp_path)
        (tmp_path / "amro_pkg_version_report_p1.xlsx").write_bytes(b"xlsx")
        resp = client.get("/generate/package-version-report?package_id=p1")
        assert resp.status_code == 200 and resp.data == b"xlsx"

    def test_reminder_pure_sync(self, client, store):
        """提醒单回归单一功能：直接返回 xlsx（版本检查已独立为按钮下载）。"""
        pkg_id = self._make_package(store)
        resp = client.post("/generate/reminder", data={"package_id": pkg_id})
        assert resp.status_code == 200 and "spreadsheetml" in resp.mimetype

    def test_upload_row_button_and_generate_buttons(self, client, store):
        """工作包行内「查询工作包工卡版本」按钮 + 预览页按钮排（生成工卡改版下载），勾选框已移除。"""
        pkg_id = self._make_package(store)
        html = client.get("/upload").get_data(as_text=True)
        # 行内按钮为 JS 拼装 URL：onclick="pkgVersionCheck('<package_id>', this)"
        assert f"pkgVersionCheck('{pkg_id}'" in html
        assert "查询工作包工卡版本" in html
        html2 = client.get(f"/generate?package_id={pkg_id}").get_data(as_text=True)
        assert "生成工卡改版下载" in html2
        assert "生成提醒单下载" in html2
        assert "versionCheck" not in html2   # 版本检查勾选框已移除
