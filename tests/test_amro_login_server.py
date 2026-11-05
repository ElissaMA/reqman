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


def test_upload_url_for_with_server(amro_login, monkeypatch):
    """--server 仅在通过白名单校验后生效，且去除尾斜杠。"""
    monkeypatch.setattr(amro_login, "ALLOWED_SERVER_HOSTS", ["reqman.local"])
    assert amro_login.upload_url_for("http://reqman.local") == \
        "http://reqman.local/inventory/login/upload"
    assert amro_login.upload_url_for("http://reqman.local/") == \
        "http://reqman.local/inventory/login/upload"


def test_upload_url_rejects_foreign_host(amro_login):
    """含 JSESSIONID 的上传目标必须受限：任意主机一律拒绝。"""
    with pytest.raises(ValueError, match="不在允许列表"):
        amro_login.upload_url_for("http://evil.example.com")


def test_upload_url_rejects_bad_scheme(amro_login):
    with pytest.raises(ValueError, match="格式非法"):
        amro_login.upload_url_for("ftp://127.0.0.1/x")
    with pytest.raises(ValueError, match="格式非法"):
        amro_login.upload_url_for("127.0.0.1:5001")


def test_upload_url_allows_whitelisted_host(amro_login, monkeypatch):
    monkeypatch.setattr(amro_login, "ALLOWED_SERVER_HOSTS", ["reqman.example.com"])
    assert amro_login.upload_url_for("http://reqman.example.com") == \
        "http://reqman.example.com/inventory/login/upload"
    assert amro_login.upload_url_for("http://reqman.example.com:8080") == \
        "http://reqman.example.com:8080/inventory/login/upload"


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


def test_upload_url_uses_injected_address_when_no_arg(tmp_path):
    """打包时 SERVER_URL/UPLOAD_URL 注入真实地址：双击运行（无 --server）必须传到该地址，
    不能回退本机 127.0.0.1（否则服务器端报 All connection attempts failed）。"""
    source = _SCRIPT.read_text(encoding="utf-8")
    source = source.replace(
        'UPLOAD_URL = "http://127.0.0.1:5001/inventory/login/upload"',
        'UPLOAD_URL = "http://8.137.15.167/inventory/login/upload"',
    ).replace(
        'SERVER_URL = "http://127.0.0.1:5001"',
        'SERVER_URL = "http://8.137.15.167"',
    )
    packed = tmp_path / "amro_login_packed.py"
    packed.write_text(source, encoding="utf-8")

    spec = importlib.util.spec_from_file_location("packed_login", packed)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.upload_url_for("") == "http://8.137.15.167/inventory/login/upload"
    assert mod.upload_url_for(None) == "http://8.137.15.167/inventory/login/upload"
    # --server（一键协议）优先级更高，且去尾斜杠
    assert mod.upload_url_for("http://other:5001/") == \
        "http://other:5001/inventory/login/upload"
