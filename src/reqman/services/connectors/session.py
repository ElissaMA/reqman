"""AMRO 登录凭证持久缓存。

Cookie 是否仍可用由 AMRO 只读探活决定，不由本地固定 TTL 截断。
与业务数据库（json_store）解耦；原子写防并发损坏；保留旧缓存兼容读取。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    """原子写入，失败时保留原文件并抛出异常。"""
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        for attempt in range(3):
            try:
                os.replace(tmp, str(path))
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        # 敏感凭证(含 JSESSIONID)限制为仅属主可读写；Windows 下 chmod 会置只读位导致后续写入失败，故仅非 Windows 执行。
        if os.name != "nt":
            try:
                os.chmod(str(path), 0o600)
            except OSError:
                pass
    except (OSError, TypeError):
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


class LoginSessionStore:
    """AMRO 登录凭证持久缓存。

    ``ttl_seconds`` 仅保留为旧配置兼容参数，不参与缓存失效判断；
    真正的失效由 AMRO 只读探活返回的会话状态决定。
    """

    _lock = threading.Lock()

    def __init__(self, path: str | Path, ttl_seconds: int = 0):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds  # deprecated: retained for constructor compatibility
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalise(data: object) -> dict | None:
        if not isinstance(data, dict):
            return None
        raw_cookies = data.get("cookies")
        if not isinstance(raw_cookies, dict) or not raw_cookies:
            return None
        cookies: dict[str, str] = {}
        for name, value in raw_cookies.items():
            if not isinstance(name, str) or not name.strip():
                return None
            if not isinstance(value, str) or not value.strip():
                return None
            cookies[name] = value
        if not cookies.get("JSESSIONID", "").strip():
            return None
        created_at = data.get("created_at")
        login_at = data.get("login_at") or created_at
        account = data.get("account")
        if not isinstance(account, str) or not account.strip():
            account = None
        return {
            "schema_version": data.get("schema_version", 1),
            "cookies": cookies,
            "account": account.strip() if account else None,
            "created_at": created_at,
            "login_at": login_at,
            "last_checked_at": data.get("last_checked_at"),
            "last_check_state": data.get("last_check_state", "never"),
            "last_check_error": data.get("last_check_error"),
            # 保留旧字段仅为格式兼容，不再参与失效判断。
            "expires_at": data.get("expires_at"),
            "user": data.get("user"),
        }

    def _read_raw(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("登录凭证缓存读取失败: %s", self.path)
            return None
        return self._normalise(raw)

    def load(self) -> dict | None:
        """读取未损坏的缓存；不再检查 expires_at。"""
        with self._lock:
            return self._read_raw()

    @staticmethod
    def _validate_cookie_list(cookies: list[dict]) -> dict[str, str]:
        if not isinstance(cookies, list) or not cookies:
            raise ValueError("登录凭证必须是非空列表")
        cookie_map: dict[str, str] = {}
        for cookie in cookies:
            if not isinstance(cookie, dict):
                raise TypeError("登录凭证条目格式错误")
            name = cookie.get("name")
            value = cookie.get("value")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("登录凭证缺少 Cookie 名称")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("登录凭证缺少 Cookie 值")
            cookie_map[name] = value
        if not cookie_map.get("JSESSIONID", "").strip():
            raise ValueError("登录凭证缺少有效 JSESSIONID")
        return cookie_map

    def save(self, cookies: list[dict], account: str | None = None) -> None:
        cookie_map = self._validate_cookie_list(cookies)
        now = _now_iso()
        account = account.strip() if isinstance(account, str) and account.strip() else None
        data = {
            "schema_version": 2,
            "cookies": cookie_map,
            "account": account,
            "created_at": now,
            "login_at": now,
            "last_checked_at": None,
            "last_check_state": "never",
            "last_check_error": None,
            "expires_at": None,
            "user": None,
        }
        with self._lock:
            _atomic_write(self.path, data)

    def mark_probe(self, state: str, error: str | None = None) -> None:
        """记录最近一次探活结果，不记录 Cookie 值。"""
        if state not in {"valid", "expired", "probe_error"}:
            raise ValueError(f"未知探活状态: {state}")
        with self._lock:
            data = self._read_raw()
            if not data:
                return
            data["last_checked_at"] = _now_iso()
            data["last_check_state"] = state
            data["last_check_error"] = error if state == "probe_error" else None
            _atomic_write(self.path, data)

    def clear(self) -> None:
        with self._lock:
            try:
                if self.path.exists():
                    self.path.unlink()
            except OSError:
                logger.warning("清除登录凭证缓存失败: %s", self.path)
