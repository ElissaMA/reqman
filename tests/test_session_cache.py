"""登录凭证临时缓存测试"""
from pathlib import Path

from reqman.services.connectors.session import LoginSessionStore


def _cookies():
    return [{"name": "JSESSIONID", "value": "abc123"}]


class TestLoginSessionStore:
    def test_save_then_load(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=7200)
        store.save(_cookies())
        loaded = store.load()
        assert loaded is not None
        assert loaded["cookies"]["JSESSIONID"] == "abc123"
        assert "expires_at" in loaded

    def test_load_missing_returns_none(self, tmp_path: Path):
        store = LoginSessionStore(tmp_path / "nope.json", ttl_seconds=7200)
        assert store.load() is None

    def test_expired_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=-1)  # 立即过期
        store.save(_cookies())
        assert store.load() is None

    def test_remaining_seconds(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=7200)
        store.save(_cookies())
        rem = store.remaining_seconds()
        assert 7190 <= rem <= 7200

    def test_clear(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=7200)
        store.save(_cookies())
        store.clear()
        assert store.load() is None
        assert not path.exists()

    def test_corrupt_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.json"
        path.write_text("{bad json", encoding="utf-8")
        store = LoginSessionStore(path, ttl_seconds=7200)
        assert store.load() is None
