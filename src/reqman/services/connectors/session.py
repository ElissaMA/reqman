"""登录凭证临时缓存 — 一次性凭证，短时复用，用完/超时即删

与业务数据库（json_store）解耦；原子写防并发损坏；预留未来用户绑定字段。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _atomic_write(path: Path, data: dict) -> None:
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except (OSError, TypeError):
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class LoginSessionStore:
    """一次性登录凭证临时缓存（默认 TTL 2 小时）。"""

    _lock = threading.Lock()

    def __init__(self, path: str | Path, ttl_seconds: int = 7200):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_raw(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("登录凭证缓存读取失败: %s", self.path)
            return None

    def load(self) -> dict | None:
        with self._lock:
            data = self._read_raw()
            if not data:
                return None
            expires = data.get("expires_at", "")
            try:
                expires_dt = datetime.fromisoformat(expires)
            except (ValueError, TypeError):
                return None
            if expires_dt < datetime.now(timezone.utc).astimezone():
                return None
            cookies = data.get("cookies", {})
            if not isinstance(cookies, dict) or not cookies:
                return None
            return {"cookies": cookies, "expires_at": expires}

    def save(self, cookies: list[dict]) -> None:
        cookie_map = {c.get("name", ""): c.get("value", "") for c in cookies if c.get("name")}
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(seconds=self.ttl_seconds)
        data = {
            "cookies": cookie_map,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            # 预留用户绑定字段（G1 全局共享，未来用户体系接入时填充）
            "user": None,
        }
        with self._lock:
            _atomic_write(self.path, data)

    def clear(self) -> None:
        with self._lock:
            try:
                if self.path.exists():
                    self.path.unlink()
            except OSError:
                logger.warning("清除登录凭证缓存失败: %s", self.path)

    def remaining_seconds(self) -> int:
        data = self._read_raw()
        if not data:
            return 0
        expires = data.get("expires_at", "")
        try:
            expires_dt = datetime.fromisoformat(expires)
        except (ValueError, TypeError):
            return 0
        rem = (expires_dt - datetime.now(timezone.utc).astimezone()).total_seconds()
        return max(int(rem), 0)
