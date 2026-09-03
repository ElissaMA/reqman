"""作废工卡独立存储 — 单独 JSON 文件，与主库分离降低读写体积。

工卡版本检查检测到作废后整卡移入本库（承接原卡全部字段），主库随即删除：
作废卡因此自动退出工卡清单/工卡组/匹配/版本检查，本库不做任何参与性补查。
"""
import json
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from .json_store import _atomic_write

logger = logging.getLogger(__name__)

_BJ = ZoneInfo("Asia/Shanghai")

_EMPTY = {"next_id": 1, "cards": {}}


class CancelledCardStore:
    """作废工卡库：{"next_id": int, "cards": {"<id>": 记录}}。

    记录 = 原卡全部字段（id 换为本库自增 id，主库原 id 存 orig_id）
    + cancelled_at（作废时间）+ cancel_source（检测来源）+ set_name（原工卡组名快照，仅展示）。
    """

    _lock = threading.Lock()

    def __init__(self, path: str):
        self._path = str(path)
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)

    def _read(self) -> dict:
        if not os.path.exists(self._path):
            return dict(_EMPTY)
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.error("作废工卡库读取失败: %s", self._path)
            return dict(_EMPTY)
        if not isinstance(data, dict) or "cards" not in data:
            return dict(_EMPTY)
        return data

    def _write(self, data: dict) -> None:
        _atomic_write(self._path, data)

    def get_all(self) -> list[dict]:
        """全部作废工卡，按作废时间倒序（同刻按 id 倒序保稳定）。"""
        with self._lock:
            cards = list(self._read().get("cards", {}).values())
        cards.sort(key=lambda c: (c.get("cancelled_at", ""), c.get("id", 0)), reverse=True)
        return cards

    def find_by_code(self, code: str) -> dict | None:
        with self._lock:
            for card in self._read().get("cards", {}).values():
                if card.get("task_code") == code:
                    return card
        return None

    def add(self, card: dict, source: str, set_name: str = "") -> dict:
        """整卡移入（按 task_code upsert：重复作废覆盖旧记录，中断重跑安全）。"""
        code = str(card.get("task_code", "")).strip()
        with self._lock:
            data = self._read()
            cards: dict = data.setdefault("cards", {})
            record = dict(card)
            record["orig_id"] = card.get("id")
            record["cancelled_at"] = datetime.now(_BJ).strftime("%Y-%m-%d %H:%M:%S")
            record["cancel_source"] = source
            record["set_name"] = set_name or ""
            existing_id = next((int(k) for k, v in cards.items()
                                if v.get("task_code") == code), None)
            if existing_id is None:
                existing_id = int(data.get("next_id", 1))
                data["next_id"] = existing_id + 1
            record["id"] = existing_id
            cards[str(existing_id)] = record
            self._write(data)
        return record

    def remove(self, card_id: int) -> dict | None:
        """彻底删除，返回被删记录（无则 None）。"""
        with self._lock:
            data = self._read()
            record = data.get("cards", {}).pop(str(card_id), None)
            if record is None:
                return None
            self._write(data)
        return record
