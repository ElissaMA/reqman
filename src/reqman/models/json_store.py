"""JSON 文件持久化实现

特点：
1. 原子写入 — 先写临时文件再 rename，防止写入中途崩溃损坏数据
2. 编码倒排索引 — O(1) 按工卡号查找
3. 线程锁 — 保证 ID 生成的原子性
4. 自动备份 — 每次保存后复制 .bak
5. 启动自愈 — 如果主文件损坏，自动从 .bak 恢复
"""

import json
import logging
import os
import shutil
import threading
import uuid
from typing import ClassVar
from zoneinfo import ZoneInfo

from ..config import CATEGORIES

logger = logging.getLogger(__name__)


def _atomic_write(path: str, data: dict) -> None:
    """原子写入：写到 .tmp 然后 rename。rename 在同文件系统上是原子的。"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # Windows / Unix 上均为原子操作
    except (OSError, TypeError):
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                logger.debug("Failed to remove temp file: %s", tmp)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


_EMPTY_DB = {
    "next_id": 1,
    "code_index": {},
    "cards": {},
    "card_sets": {},
    "aircraft": {},
    "card_logs": [],
    "card_log_next_id": 1,
}

# 运行时数据（不纳入 Git 追踪）的键列表
_RUNTIME_KEYS = {
    "work_packages",
    "next_id",
    "code_index",
    "next_ac_id",
}


class JsonStore:
    """双文件 JSON 存储：核心数据（飞机/工卡/工卡组/日志）+ 运行时数据（工作包/计数器）

    核心数据默认受 Git 追踪，运行时数据（_RUNTIME_KEYS）写入独立文件，
    应在 .gitignore 中忽略运行时文件。
    """

    _lock = threading.Lock()

    _FIELDS: ClassVar[dict] = {
        "card": {
            "id": None, "task_code": "", "task_name": "", "category": "机体",
            "task_type": "", "remark": "", "tools": [], "materials": [],
            "tools_confirmed": False, "materials_confirmed": False,
            "set_id": None, "reminder_type": "", "card_ok": False, "reminder_confirmed": False,
        },
        "set": {
            "id": None, "name": "", "description": "", "category": "机体",
            "tools": [], "materials": [],
            "tools_confirmed": False, "materials_confirmed": False,
            "reminder_type": "", "card_ok": False, "reminder_confirmed": False,
        },
        "aircraft": {
            "id": None, "reg": "", "model": "", "engine": "",
            "fsn": "", "msn": "", "apu": "",
        },
    }

    # 字段映射表（用于变更检测）
    _CARD_FIELDS: ClassVar[list] = ["task_code", "task_name", "category", "task_type", "remark",
                    "tools", "materials", "tools_confirmed", "materials_confirmed",
                    "set_id", "reminder_type", "card_ok", "reminder_confirmed"]
    _SET_FIELDS: ClassVar[list] = ["name", "description", "category", "tools", "materials",
                   "tools_confirmed", "materials_confirmed",
                   "reminder_type", "card_ok", "reminder_confirmed"]
    _AIRCRAFT_FIELDS: ClassVar[list] = ["reg", "model", "engine", "fsn", "msn", "apu"]

    def _norm(self, d, kind):
        defaults = self._FIELDS[kind]
        return {k: d.get(k, v) for k, v in defaults.items()}

    # ---------- 初始化 ----------

    def __init__(self, db_path: str):
        self._path = str(db_path)
        base, ext = os.path.splitext(self._path)
        self._runtime_path = base + "_runtime" + ext
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化或修复数据库。首次拆分时将运行时数据写入独立文件"""
        if not os.path.exists(self._path) and not os.path.exists(self._runtime_path):
            bak = self._path + ".bak"
            if os.path.exists(bak):
                logger.warning("主数据库缺失，从备份恢复")
                shutil.copy2(bak, self._path)
            else:
                self._write(_EMPTY_DB)
                return

        # 核心文件缺失但运行时存在时，尝试从备份恢复核心文件
        if not os.path.exists(self._path) and os.path.exists(self._runtime_path):
            bak = self._path + ".bak"
            if os.path.exists(bak):
                logger.warning("核心数据库缺失，从备份恢复")
                shutil.copy2(bak, self._path)
            else:
                # 无备份，用空核心
                _atomic_write(self._path, {})

        # 验证文件可读（合并读取两个文件）
        try:
            self._read()
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"数据库文件损坏: {e}")
            bak = self._path + ".bak"
            if os.path.exists(bak):
                logger.warning("尝试从备份恢复")
                shutil.copy2(bak, self._path)
                try:
                    self._read()
                except (OSError, json.JSONDecodeError):
                    self._write(_EMPTY_DB)
                    return
            else:
                self._write(_EMPTY_DB)
                return

    # ---------- 内部分方法 ----------

    def _read(self) -> dict:
        """合并加载两个文件：核心数据 + 运行时数据"""
        db = {}
        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    db.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                logger.warning("核心数据库读取失败: %s", self._path)
        if os.path.exists(self._runtime_path):
            try:
                with open(self._runtime_path, encoding="utf-8") as f:
                    db.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                logger.warning("运行时数据库读取失败: %s", self._runtime_path)
        # 内存中修复不完整的索引（不持久化，下次 _write() 时自动保存）
        if db.get("cards"):
            ci = db.get("code_index", {})
            if not ci or len(ci) < len(db["cards"]):
                self._rebuild_index(db)
        return db

    def _write(self, data: dict) -> None:
        """拆分写入两个文件：运行时数据写入独立文件"""
        # 自动重建索引（处理数据导入后索引丢失或不完整的情况）
        if data.get("cards"):
            ci = data.get("code_index", {})
            if not ci or len(ci) < len(data["cards"]):
                self._rebuild_index(data)
        core = {}
        runtime = {}
        for k, v in data.items():
            if k in _RUNTIME_KEYS:
                runtime[k] = v
            else:
                core[k] = v

        _atomic_write(self._path, core)
        _atomic_write(self._runtime_path, runtime)

        # 备份核心文件
        try:
            shutil.copy2(self._path, self._path + ".bak")
        except OSError:
            logger.warning("核心文件备份失败: %s.bak", self._path)

    def _next_id(self, db: dict) -> int:
        """从 db dict 中取 next_id 并递增。调用方需持有 _lock"""
        nid = db["next_id"]
        db["next_id"] = nid + 1
        return nid

    def _rebuild_index(self, db: dict) -> None:
        """重建编码索引"""
        db["code_index"] = {}
        for card_id, card in db.get("cards", {}).items():
            db["code_index"][card["task_code"]] = int(card_id)

    # ---------- 日志辅助方法 ----------

    @staticmethod
    def _detect_changes(old_data: dict, new_data: dict, field_map: list) -> list:
        """检测两个数据字典之间的变更，返回 changes 列表"""
        changes = []
        for field in field_map:
            old_val = old_data.get(field)
            new_val = new_data.get(field)
            if old_val != new_val:
                changes.append({
                    "field": field,
                    "old": old_val,
                    "new": new_val,
                })
        return changes

    def _add_log(self, db: dict, operation: str, target_type: str,
                 target_id: int, target_identifier: str, target_name: str,
                 changes: list) -> dict:
        """添加变更日志到 db（调用方需持有 _lock）"""
        from datetime import datetime
        log_id = db.setdefault("card_log_next_id", 1)
        db["card_log_next_id"] = log_id + 1
        log = {
            "id": log_id,
            "operation": operation,
            "target_type": target_type,
            "target_id": target_id,
            "target_identifier": target_identifier,
            "target_name": target_name,
            "changes": changes,
            "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        }
        db.setdefault("card_logs", []).append(log)
        return log

    # ---------- 工卡 CRUD ----------

    def get_all(self, search: str = "", category: str = "",
                reminder_type: str = "") -> list[dict]:
        db = self._read()
        cards = list(db.get("cards", {}).values())

        if search:
            keyword = search.lower()
            cards = [
                card for card in cards
                if keyword in card["task_code"].lower() or keyword in card.get("task_name", "").lower()
            ]

        if category:
            cards = [card for card in cards if card.get("category") == category]

        if reminder_type:
            cards = [card for card in cards if card.get("reminder_type") == reminder_type]

        # 按 专业 → 工卡号 排序
        cat_order = {cat: i for i, cat in enumerate(CATEGORIES)}
        cards.sort(key=lambda card: (cat_order.get(card.get("category"), 99), card["task_code"]))
        return cards

    def get(self, card_id: int) -> dict | None:
        db = self._read()
        card = db.get("cards", {}).get(str(card_id))
        return self._norm(card, "card") if card else None

    def find_by_code(self, code: str) -> dict | None:
        db = self._read()
        card_id = db.get("code_index", {}).get(code)
        if card_id is None:
            return None
        card = db.get("cards", {}).get(str(card_id))
        return self._norm(card, "card") if card else None

    def add(self, task_code: str, task_name: str = "",
            category: str = "机体", task_type: str = "",
            remark: str = "", reminder_type: str = "") -> dict | None:
        with self._lock:
            db = self._read()

            # 检查重复
            if task_code in db.get("code_index", {}):
                return None

            if category not in CATEGORIES:
                category = "机体"

            card_id = self._next_id(db)
            card = {
                "id": card_id,
                "task_code": task_code,
                "task_name": task_name,
                "category": category,
                "task_type": task_type,
                "remark": remark,
                "tools": [],
                "materials": [],
                "tools_confirmed": False,
                "materials_confirmed": False,
                "set_id": None,
                "reminder_type": reminder_type,
                "card_ok": False,
                "reminder_confirmed": False,
            }

            db.setdefault("cards", {})[str(card_id)] = card
            db.setdefault("code_index", {})[task_code] = card_id

            self._add_log(db, "add", "card", card_id, task_code, task_name, [])
            self._write(db)
            return self._norm(card, "card")

    def update(self, card_id: int, **kwargs) -> dict | None:
        with self._lock:
            db = self._read()
            card = db.get("cards", {}).get(str(card_id))
            if card is None:
                return None

            old_card = dict(card)  # 变更前快照
            old_code = card.get("task_code")

            for key in ("task_code", "task_name", "category",
                        "task_type", "remark", "tools", "materials",
                        "set_id", "tools_confirmed", "materials_confirmed",
                        "reminder_type", "card_ok", "reminder_confirmed"):
                if key in kwargs:
                    card[key] = kwargs[key]

            # 如果编码变了，更新索引
            new_code = card.get("task_code")
            if old_code and old_code != new_code:
                db["code_index"].pop(old_code, None)
                if new_code:
                    db["code_index"][new_code] = card_id

            changes = self._detect_changes(old_card, card, self._CARD_FIELDS)
            self._add_log(db, "update", "card", card_id,
                          card.get("task_code", ""), card.get("task_name", ""), changes)
            self._write(db)
            return self._norm(card, "card")

    def delete(self, card_id: int) -> bool:
        with self._lock:
            db = self._read()
            card = db.get("cards", {}).pop(str(card_id), None)
            if card is None:
                return False

            db["code_index"].pop(card.get("task_code"), None)
            self._add_log(db, "delete", "card", card_id,
                          card.get("task_code", ""), card.get("task_name", ""), [])
            self._write(db)
            return True

    # ---------- 工卡组 CRUD ----------

    def get_all_sets(self) -> list[dict]:
        db = self._read()
        sets = [self._norm(set, "set") for set in db.get("card_sets", {}).values()]
        sets.sort(key=lambda set: set.get("name", ""))
        return sets

    def get_set(self, set_id: int) -> dict | None:
        db = self._read()
        set = db.get("card_sets", {}).get(str(set_id))
        return self._norm(set, "set") if set else None

    def add_set(self, name: str, description: str = "",
                category: str = "机体", reminder_type: str = "",
                card_ok: bool = False, reminder_confirmed: bool = False) -> dict:
        with self._lock:
            db = self._read()
            set_id = self._next_id(db)
            set = {
                "id": set_id,
                "name": name,
                "description": description,
                "category": category,
                "tools": [],
                "materials": [],
                "tools_confirmed": False,
                "materials_confirmed": False,
                "reminder_type": reminder_type,
                "card_ok": card_ok,
                "reminder_confirmed": reminder_confirmed,
            }
            db.setdefault("card_sets", {})[str(set_id)] = set
            self._add_log(db, "add", "set", set_id, name, name, [])
            self._write(db)
            return dict(set)

    def update_set(self, set_id: int, **kwargs) -> dict | None:
        with self._lock:
            db = self._read()
            set = db.get("card_sets", {}).get(str(set_id))
            if set is None:
                return None

            old_set = dict(set)  # 变更前快照
            for key in ("name", "description", "category", "tools",
                         "materials", "tools_confirmed", "materials_confirmed",
                         "reminder_type", "card_ok", "reminder_confirmed"):
                if key in kwargs and kwargs[key] is not None:
                    set[key] = kwargs[key]

            changes = self._detect_changes(old_set, set, self._SET_FIELDS)
            self._add_log(db, "update", "set", set_id,
                          set.get("name", ""), set.get("name", ""), changes)
            self._write(db)
            return dict(set)

    def delete_set(self, set_id: int) -> bool:
        with self._lock:
            db = self._read()
            if str(set_id) not in db.get("card_sets", {}):
                return False

            # 解除关联工卡
            for card in db.get("cards", {}).values():
                if card.get("set_id") == set_id:
                    card["set_id"] = None

            set = db["card_sets"].pop(str(set_id))
            self._add_log(db, "delete", "set", set_id,
                          set.get("name", ""), set.get("name", ""), [])
            self._write(db)
            return True

    def get_cards_in_set(self, set_id: int) -> list[dict]:
        db = self._read()
        return [
            self._norm(card, "card") for card in db.get("cards", {}).values()
            if card.get("set_id") == set_id
        ]

    # ---------- 飞机信息 CRUD ----------

    def get_all_aircraft(self) -> list[dict]:
        db = self._read()
        ac_list = list(db.get("aircraft", {}).values())
        ac_list.sort(key=lambda ac: ac.get("reg", ""))
        return [self._norm(ac, "aircraft") for ac in ac_list]

    def get_aircraft(self, aircraft_id: int) -> dict | None:
        db = self._read()
        ac = db.get("aircraft", {}).get(str(aircraft_id))
        return self._norm(ac, "aircraft") if ac else None

    def find_aircraft_by_reg(self, reg: str):
        for ac in self._read().get("aircraft", {}).values():
            if ac.get("reg") == reg:
                return self._norm(ac, "aircraft")
        return None

    def add_aircraft(self, reg: str, model: str = "",
                     engine: str = "", fsn: str = "", msn: str = "", apu: str = "") -> dict:
        with self._lock:
            db = self._read()
            aircraft_id = self._next_id(db)
            ac = {
                "id": aircraft_id,
                "reg": reg,
                "model": model,
                "engine": engine,
                "fsn": fsn,
                "msn": msn,
                "apu": apu,
            }
            db.setdefault("aircraft", {})[str(aircraft_id)] = ac
            self._add_log(db, "add", "aircraft", aircraft_id, reg, model, [])
            self._write(db)
            return self._norm(ac, "aircraft")

    def update_aircraft(self, aircraft_id: int, **kwargs) -> dict | None:
        with self._lock:
            db = self._read()
            ac = db.get("aircraft", {}).get(str(aircraft_id))
            if ac is None:
                return None

            old_ac = dict(ac)  # 变更前快照
            for key in ("reg", "model", "engine", "fsn", "msn", "apu"):
                if key in kwargs:
                    ac[key] = kwargs[key]

            changes = self._detect_changes(old_ac, ac, self._AIRCRAFT_FIELDS)
            self._add_log(db, "update", "aircraft", aircraft_id,
                          ac.get("reg", ""), ac.get("model", ""), changes)
            self._write(db)
            return self._norm(ac, "aircraft")

    def save_work_package(self, data):
        db = self._read()
        wps = db.setdefault("work_packages", [])
        if "package_id" not in data:
            data["package_id"] = str(uuid.uuid4())
        for i, wp in enumerate(wps):
            if wp.get("reg") == data["reg"] and wp.get("description") == data["description"]:
                data["package_id"] = wp.get("package_id", data["package_id"])
                wps[i] = data
                self._write(db)
                return data
        wps.append(data)
        if len(wps) > 10:
            wps.sort(key=lambda x: x.get("date", ""), reverse=True)
            wps[:] = wps[:10]
        self._write(db)
        return data

    def get_work_packages(self):
        db = self._read()
        wps = db.get("work_packages", [])
        return sorted(wps, key=lambda x: x.get("date", ""), reverse=False)

    def get_work_package(self, package_id: str) -> dict | None:
        db = self._read()
        for wp in db.get("work_packages", []):
            if wp.get("package_id") == package_id:
                return dict(wp)
        return None

    def delete_work_package(self, package_id: str) -> bool:
        with self._lock:
            db = self._read()
            wps = db.get("work_packages", [])
            new_wps = [w for w in wps if w.get("package_id") != package_id]
            if len(new_wps) == len(wps):
                return False
            db["work_packages"] = new_wps
            self._write(db)
            return True

    def delete_aircraft(self, aircraft_id: int) -> bool:
        with self._lock:
            db = self._read()
            if str(aircraft_id) not in db.get("aircraft", {}):
                return False
            ac = db["aircraft"].pop(str(aircraft_id))
            self._add_log(db, "delete", "aircraft", aircraft_id,
                          ac.get("reg", ""), ac.get("model", ""), [])
            self._write(db)
            return True

    # ---------- 工卡组同步 ----------

    def sync_set_to_cards(self, set_id: int) -> None:
        """将工卡组的分类/工具/航材/提醒字段同步到组内所有卡"""
        with self._lock:
            db = self._read()
            set = db.get("card_sets", {}).get(str(set_id))
            if not set:
                return
            for field in ("category", "tools", "materials",
                          "tools_confirmed", "materials_confirmed",
                          "card_ok", "reminder_type", "reminder_confirmed"):
                if field not in set:
                    continue
                for card in db.get("cards", {}).values():
                    if card.get("set_id") == set_id:
                        card[field] = set[field]
            self._write(db)

    # ---------- 日志查询 ----------

    def get_logs(self, operation: str | None = None, target_type: str | None = None,
                 start_date: str | None = None, end_date: str | None = None,
                 limit: int = 100) -> list[dict]:
        """查询日志，支持按操作类型、目标类型、时间范围筛选，按时间降序"""
        db = self._read()
        logs = list(db.get("card_logs", []))
        if operation:
            logs = [log for log in logs if log.get("operation") == operation]
        if target_type:
            logs = [log for log in logs if log.get("target_type") == target_type]
        if start_date:
            logs = [log for log in logs if log.get("timestamp", "") >= start_date]
        if end_date:
            logs = [log for log in logs if log.get("timestamp", "") <= end_date]
        logs.sort(key=lambda log: log.get("timestamp", ""), reverse=True)
        return logs[:limit]

    def delete_logs(self, log_ids: list[int]) -> int:
        """删除指定 ID 的日志，返回删除数量"""
        with self._lock:
            db = self._read()
            logs = db.get("card_logs", [])
            log_ids_set = set(log_ids)
            new_logs = [log for log in logs if log.get("id") not in log_ids_set]
            deleted = len(logs) - len(new_logs)
            if deleted:
                db["card_logs"] = new_logs
                self._write(db)
            return deleted

    def trim_logs(self, max_count: int = 200) -> int:
        """保留最新N条日志，删除多余的，返回删除数量"""
        with self._lock:
            db = self._read()
            logs = db.get("card_logs", [])
            if len(logs) <= max_count:
                return 0
            # 按时间降序排列，保留前max_count条
            logs.sort(key=lambda log: log.get("timestamp", ""), reverse=True)
            deleted_count = len(logs) - max_count
            db["card_logs"] = logs[:max_count]
            self._write(db)
            return deleted_count
