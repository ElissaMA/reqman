"""AMRO 连接器单元测试（mock httpx）"""
import asyncio

import httpx
import pytest

from reqman.services.connectors import amro


def _run(coro):
    return asyncio.run(coro)


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
