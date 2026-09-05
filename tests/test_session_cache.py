"""AMRO 登录凭证持久缓存测试。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reqman.services.connectors.session import LoginSessionStore


def _cookies():
    return [{"name": "JSESSIONID", "value": "abc123"}]


class TestLoginSessionStore:
    def test_save_then_load_with_account(self, tmp_path: Path):
        store = LoginSessionStore(tmp_path / "session.json", ttl_seconds=7200)
        store.save(_cookies(), account="021219")
        loaded = store.load()
        assert loaded is not None
        assert loaded["cookies"]["JSESSIONID"] == "abc123"
        assert loaded["account"] == "021219"
        assert loaded["login_at"]
        assert loaded["expires_at"] is None

    def test_old_expired_cache_is_still_readable(self, tmp_path: Path):
        path = tmp_path / "session.json"
        old = datetime.now(timezone.utc) - timedelta(days=30)
        path.write_text(json.dumps({
            "cookies": {"JSESSIONID": "old"},
            "created_at": old.isoformat(),
            "expires_at": (old + timedelta(hours=2)).isoformat(),
            "user": None,
        }), encoding="utf-8")
        loaded = LoginSessionStore(path, ttl_seconds=7200).load()
        assert loaded is not None
        assert loaded["cookies"]["JSESSIONID"] == "old"
        assert loaded["login_at"] == old.isoformat()

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert LoginSessionStore(tmp_path / "nope.json").load() is None

    def test_invalid_cookie_structure_rejected(self, tmp_path: Path):
        store = LoginSessionStore(tmp_path / "session.json")
        for cookies in ([], [{}], [{"name": "JSESSIONID", "value": ""}], ["bad"]):
            try:
                store.save(cookies)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
            else:
                raise AssertionError(f"invalid cookies accepted: {cookies!r}")

    def test_clear(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path)
        store.save(_cookies())
        store.clear()
        assert store.load() is None
        assert not path.exists()

    def test_corrupt_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.json"
        path.write_text("{bad json", encoding="utf-8")
        assert LoginSessionStore(path).load() is None

    def test_non_dict_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.json"
        path.write_text("[]", encoding="utf-8")
        assert LoginSessionStore(path).load() is None

    def test_mark_probe_preserves_account(self, tmp_path: Path):
        store = LoginSessionStore(tmp_path / "session.json")
        store.save(_cookies(), account="021219")
        store.mark_probe("valid")
        loaded = store.load()
        assert loaded["last_check_state"] == "valid"
        assert loaded["last_checked_at"]
        assert loaded["account"] == "021219"
