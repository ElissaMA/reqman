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
