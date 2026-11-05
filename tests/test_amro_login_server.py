"""amro_login.py 的 --server 解析：动态定址上传，登录配置包通用。"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "amro_login.py"


@pytest.fixture
def amro_login():
    spec = importlib.util.spec_from_file_location("amro_login_test_mod", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upload_url_for_with_server(amro_login):
    assert amro_login.upload_url_for("http://127.0.0.1:5001") == \
        "http://127.0.0.1:5001/inventory/login/upload"
    assert amro_login.upload_url_for("http://amro.example.com") == \
        "http://amro.example.com/inventory/login/upload"
    assert amro_login.upload_url_for("http://host:9000/") == \
        "http://host:9000/inventory/login/upload"


def test_upload_url_for_fallback(amro_login):
    assert amro_login.upload_url_for("") == amro_login.UPLOAD_URL
    assert amro_login.upload_url_for(None) == amro_login.UPLOAD_URL


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._body


class _Client:
    def __init__(self, resp):
        self._resp = resp
        self.headers = {}

    async def post(self, url, data=None, cookies=None, timeout=None):
        return self._resp


class _RaisingClient:
    async def post(self, url, data=None, cookies=None, timeout=None):
        import httpx
        raise httpx.ConnectError("no net")


def _probe(amro_login, client):
    import asyncio
    return asyncio.run(amro_login._probe_login(client, [{"name": "JSESSIONID", "value": "x"}]))


def test_probe_valid(amro_login):
    assert _probe(amro_login, _Client(_Resp({"code": 200}))) == "valid"


def test_probe_pending(amro_login):
    assert _probe(amro_login, _Client(_Resp({"code": 100}))) == "pending"


def test_probe_blocked_on_403(amro_login):
    assert _probe(amro_login, _Client(_Resp({}, status_code=403))) == "blocked"


def test_probe_retry_on_network_error(amro_login):
    assert _probe(amro_login, _RaisingClient()) == "retry"


def test_probe_retry_on_unknown_code(amro_login):
    assert _probe(amro_login, _Client(_Resp({"code": 500}))) == "retry"


def test_login_script_carries_amro_user_agent(amro_login):
    """httpx 默认 python-httpx/x 被 AMRO 网关 403，脚本必须显式带 UA。"""
    assert amro_login.AMRO_USER_AGENT == "ReqMan/3.7.1 (AMRO read-only)"
    source = _SCRIPT.read_text(encoding="utf-8")
    assert 'headers={"User-Agent": AMRO_USER_AGENT}' in source


def test_login_version_bumped(amro_login):
    assert amro_login.LOGIN_VERSION == "5"
