"""AMRO 连接器单元测试（mock httpx）"""
import asyncio
import json

import httpx
import pytest

from reqman.services.connectors import amro


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_amro(monkeypatch, tmp_path):
    """隔离 AMRO 审计落盘与限速：所有调用写临时审计文件且不真实等待。"""
    monkeypatch.setattr(amro, "_audit_path", lambda: tmp_path / "amro_audit.jsonl")
    monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
    # 不真实等待：限速用 asyncio.sleep，mock 为异步空操作，避免测试中累积休眠
    async def _no_sleep(_):
        return None
    monkeypatch.setattr(amro.asyncio, "sleep", _no_sleep)


def _make_client(json_body):
    class _FakeResp:
        def __init__(self, body, status=200):
            self._body = body
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=None)

        def json(self):
            return self._body

    class _FakeClient:
        def __init__(self):
            self.data = {}

        async def post(self, url, data=None, cookies=None, timeout=None):
            self.data = {"url": url, "data": data, "cookies": cookies}
            return _FakeResp(json_body)

    return _FakeClient(), _FakeResp


class TestIsKunming:
    def test_kunming_prefix(self):
        assert amro.is_kunming("KM123") is True

    def test_non_kunming(self):
        assert amro.is_kunming("CD100") is False

    def test_empty(self):
        assert amro.is_kunming("") is False


class TestQueryKunmingStock:
    def test_sums_kunming_only(self):
        body = {"code": 200, "data": [
            {"swerk": "KM01", "clabs": 5, "meins": "EA", "maktx": "螺钉"},
            {"swerk": "KM02", "clabs": 3, "meins": "EA", "maktx": ""},
            {"swerk": "CD01", "clabs": 100, "meins": "EA", "maktx": ""},
        ]}
        client, _ = _make_client(body)
        stock = _run(amro.query_kunming_stock(client, {"k": "v"}, "PN-1"))
        assert stock is not None
        assert stock.total_qty == 8.0
        assert stock.unit == "EA"
        assert stock.pn_desc == "螺钉"

    def test_session_expired_raises(self):
        client, _ = _make_client({"code": 100, "msg": "会话过期"})
        with pytest.raises(RuntimeError, match="登录已失效"):
            _run(amro.query_kunming_stock(client, {}, "PN-1"))

    def test_all_requests_fail_returns_none(self):
        class _FailResp:
            def raise_for_status(self):
                raise httpx.ConnectError("no net")

            def json(self):
                raise AssertionError("should not reach")

        class _FailClient:
            async def post(self, url, data=None, cookies=None, timeout=None):
                return _FailResp()

        stock = _run(amro.query_kunming_stock(_FailClient(), {}, "PN-1"))
        assert stock is None


class TestCheckSession:
    def test_ok_session(self):
        client, _ = _make_client({"code": 200, "data": []})
        assert _run(amro.check_session(client, {}, "PN-1")) is True

    def test_expired_session(self):
        client, _ = _make_client({"code": 100, "msg": "会话过期"})
        assert _run(amro.check_session(client, {}, "PN-1")) is False

    def test_network_error_still_true(self):
        class _FailClient:
            async def post(self, url, data=None, cookies=None, timeout=None):
                raise httpx.ConnectError("no net")

        assert _run(amro.check_session(_FailClient(), {}, "PN-1")) is True


class TestQueryPlugin:
    """v3.5.0 通用只读调用器：白名单/限速/审计/会话异常"""

    def test_whitelist_rejects_write_plugin(self):
        client, _ = _make_client({"code": 200, "data": []})
        with pytest.raises(ValueError):
            _run(amro.query_plugin(client, {}, "BM_RWJS_JS", {}))
        assert client.data == {}  # 白名单外零外呼

    def test_session_expired_raises(self, tmp_path, monkeypatch):
        client, _ = _make_client({"code": 100, "msg": "会话过期"})
        monkeypatch.setattr(amro, "_audit_path", lambda: tmp_path / "audit.jsonl")
        monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro.time, "sleep", lambda s: None)
        with pytest.raises(amro.AmroSessionExpired):
            _run(amro.query_plugin(client, {}, "DA_ACREG_LIST", {"page": "1"}))

    def test_audit_line_written(self, tmp_path, monkeypatch):
        client, _ = _make_client({"code": 200, "data": []})
        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(amro, "_audit_path", lambda: audit)
        monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro.time, "sleep", lambda s: None)
        _run(amro.query_plugin(client, {}, "DA_ACREG_LIST", {"page": "1"}))
        line = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert line["plugin"] == "DA_ACREG_LIST" and line["code"] == 200

    def test_fetch_all_pages_zero_total_with_rows(self, tmp_path, monkeypatch):
        """BM_TSK_LIST 语义：total 恒 0 但有行 → 按空页终止不空转"""
        pages = {1: [{"i": i} for i in range(10)], 2: [{"i": 10}], 3: []}

        class _Resp:
            def __init__(self, body):
                self._body = body

            def raise_for_status(self):
                pass

            def json(self):
                return self._body

        class _PagedClient:
            async def post(self, url, data=None, cookies=None, timeout=None):
                return _Resp({"code": 200, "total": 0, "data": pages[data["page"]]})

        monkeypatch.setattr(amro, "_audit_path", lambda: tmp_path / "audit.jsonl")
        monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro.time, "sleep", lambda s: None)
        rows = _run(amro.fetch_all_pages(
            _PagedClient(), {}, "BM_TSK_LIST", {"baseCode": "KM01", "rows": 10}))
        assert len(rows) == 11


class TestInventoryReadonlyRouting:
    """库存查询必须经由通用只读调用器（白名单 + 审计），不可直连 AMRO。"""

    def test_inventory_writes_mm_audit(self, tmp_path):
        body = {"code": 200, "data": [
            {"swerk": "KM01", "clabs": 5, "meins": "EA", "maktx": "螺钉"},
        ]}
        client, _ = _make_client(body)
        _run(amro.query_kunming_stock(client, {"k": "v"}, "PN-1"))
        lines = (tmp_path / "amro_audit.jsonl").read_text(encoding="utf-8").splitlines()
        plugins = [json.loads(l)["plugin"] for l in lines]
        # 库存类型仅 "01" → 恰好一次 MM_PARTNUMBERCHAXUN_LIST 调用
        assert plugins.count("MM_PARTNUMBERCHAXUN_LIST") == 1

    def test_inventory_blocked_if_dropped_from_whitelist(self, monkeypatch):
        # 反向校验：白名单移除该端点时，库存查询被通用只读调用器拦截，零外呼
        monkeypatch.setattr(amro, "READONLY_PLUGINS", frozenset())
        client, _ = _make_client({"code": 200, "data": []})
        result = _run(amro.query_kunming_stock(client, {}, "PN-1"))
        assert result is None  # 被拦截，无任何库存数据
        assert client.data == {}  # 白名单外零外呼
