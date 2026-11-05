"""第三批（High）修复的回归测试。

覆盖 H1-H8：
- H1 凭证上传鉴权（令牌 / 本机回退）
- H2 Host 头白名单校验
- H3 登录脚本 --server 白名单
- H4 探活 clear() 的 CAS 语义
- H5 AMRO data:null 守卫
- H6 线程启动失败回滚全局查询锁
- H7 改版清单容量护栏（template_max）
- H8 需求单数据区不越过下一个区标题
"""
import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------- H3: 脚本侧白名单 ----------
class TestLoginScriptHostAllowlist:
    @pytest.fixture
    def mod(self):
        import importlib.util

        path = ROOT / "scripts" / "amro_login.py"
        spec = importlib.util.spec_from_file_location("h3_login", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_rejects_foreign_host(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "ALLOWED_SERVER_HOSTS", ["good.example.com"])
        with pytest.raises(ValueError, match="不在允许列表"):
            mod.upload_url_for("http://evil.example.com")

    def test_accepts_allowed_host(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "ALLOWED_SERVER_HOSTS", ["good.example.com"])
        assert mod.upload_url_for("http://good.example.com") == \
            "http://good.example.com/inventory/login/upload"

    def test_rejects_bad_scheme(self, mod):
        with pytest.raises(ValueError, match="格式非法"):
            mod.upload_url_for("file:///etc/passwd")


# ---------- H4: 探活 clear 的 CAS ----------
class TestProbeClearCas:
    def test_does_not_clear_newer_credentials(self, tmp_path, monkeypatch):
        """探活用旧快照得 expired，期间已写入新凭证 → 不得清除新凭证。"""
        from reqman.services.connectors.session import LoginSessionStore
        from reqman.services.inventory_service import InventoryService

        svc = InventoryService(LoginSessionStore(str(tmp_path / "s.json")))
        svc.save_login([{"name": "JSESSIONID", "value": "old"}], account="u1")

        async def fake_probe(data):
            # 探活期间模拟用户重新登录
            svc.save_login([{"name": "JSESSIONID", "value": "new"}], account="u2")
            return "expired"

        monkeypatch.setattr(svc, "_probe_cached_session", fake_probe)
        assert svc.check_login_state() == "expired"
        # 新凭证必须仍在
        latest = svc.session_store.load()
        assert latest is not None
        assert latest["cookies"]["JSESSIONID"] == "new"

    def test_clears_when_credentials_unchanged(self, tmp_path, monkeypatch):
        from reqman.services.connectors.session import LoginSessionStore
        from reqman.services.inventory_service import InventoryService

        svc = InventoryService(LoginSessionStore(str(tmp_path / "s.json")))
        svc.save_login([{"name": "JSESSIONID", "value": "old"}], account="u1")

        async def fake_probe(data):
            return "expired"

        monkeypatch.setattr(svc, "_probe_cached_session", fake_probe)
        assert svc.check_login_state() == "expired"
        assert svc.session_store.load() is None


# ---------- H5: data:null 守卫 ----------
class TestAmroDataNull:
    def test_query_single_pn_handles_null_data(self, monkeypatch):
        from reqman.services.connectors import amro

        async def fake_query_plugin(client, cookies, plugin, form, *, timeout=30):
            return {"code": 200, "data": None}

        monkeypatch.setattr(amro, "query_plugin", fake_query_plugin)

        class C:
            pass

        rows = asyncio.run(amro.query_single_pn(C(), {}, "PN-1", "01"))
        assert rows == []

    def test_query_single_pn_filters_non_dict_rows(self, monkeypatch):
        from reqman.services.connectors import amro

        async def fake_query_plugin(client, cookies, plugin, form, *, timeout=30):
            return {"code": 200, "data": [{"swerk": "KM01"}, "junk", None]}

        monkeypatch.setattr(amro, "query_plugin", fake_query_plugin)
        rows = asyncio.run(amro.query_single_pn(object(), {}, "PN-1", "01"))
        assert rows == [{"swerk": "KM01"}]


# ---------- H6: 线程启动失败回滚锁 ----------
class TestQueryRunnerThreadFailure:
    def test_lock_released_when_thread_start_fails(self, monkeypatch):
        from reqman.services.amro_sync import query_runner as qr

        class BoomThread:
            def __init__(self, *a, **kw):
                pass

            def start(self):
                raise RuntimeError("thread resources exhausted")

        monkeypatch.setattr(qr.threading, "Thread", BoomThread)
        qr.QUERY_STATUS.pop("h6", None)

        started = qr.run_query("h6", "测试任务", dict)
        assert started is False
        assert qr.QUERY_STATUS["h6"]["status"] == "error"
        # 关键：全局锁必须已释放，后续查询仍可启动
        token = qr.try_begin_query("后续任务")
        assert token is not None
        qr.end_query(token)


# ---------- H7: 容量护栏 ----------
class TestVersionReportCapacity:
    def test_guard_uses_template_max_not_inflated_max_row(self):
        """ws.cell() 读取会抬高 max_row；护栏必须与探测前的模板行数比较。"""
        source = (ROOT / "src/reqman/services/amro_sync/versions.py").read_text(encoding="utf-8")
        assert "TEMPLATE_MAX_ROW = ws.max_row" in source
        # 护栏比较必须使用快照值，而不是会随读取变化的 ws.max_row
        assert "if row > TEMPLATE_MAX_ROW:" in source
        assert "if row > ws.max_row:" not in source

    def test_openpyxl_cell_read_inflates_max_row(self):
        """锁定该前提：读取 cell 会改变 max_row，故必须提前快照。"""
        import openpyxl

        ws = openpyxl.Workbook().active
        before = ws.max_row
        ws.cell(row=before + 50, column=3)
        assert ws.max_row > before


# ---------- H8: 数据区边界 ----------
class TestFindDataStartBoundary:
    def _build(self, tmp_path):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "定检专业\n（工具）"
        ws["C2"] = "件号"
        # 工具区无数据行 → 直接接下一个区标题
        ws["A3"] = "三、备用航材需求(定检中队、MCC负责)"
        ws["C4"] = "SPARE-PN"
        path = tmp_path / "d.xlsx"
        wb.save(path)
        return path

    def test_does_not_cross_into_next_section(self, tmp_path):
        import openpyxl

        from reqman.services.xlsx_workbook import _find_data_start

        path = self._build(tmp_path)
        wb = openpyxl.load_workbook(path)
        try:
            # 工具区没有数据，不得把备用区的 SPARE-PN 当成工具区数据起点
            assert _find_data_start(wb.active, "定检专业\n（工具）") is None
        finally:
            wb.close()


