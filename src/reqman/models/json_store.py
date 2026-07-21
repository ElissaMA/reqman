"""JSON 文件持久化实现

特点：
1. 原子写入 — 先写临时文件再 rename，防止写入中途崩溃损坏数据
2. 编码倒排索引 — O(1) 按工卡号查找
3. 线程锁 — 保证 ID 生成的原子性
4. 自动备份 — 每次保存后复制 .bak
5. 启动自愈 — 如果主文件损坏，自动从 .bak 恢复
"""

import json
import os
import shutil
import threading
import logging
import uuid
from typing import Optional

from ..config import CATEGORIES

logger = logging.getLogger(__name__)


def _atomic_write(path: str, data: dict) -> None:
    """原子写入：写到 .tmp 然后 rename。rename 在同文件系统上是原子的。"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # Windows / Unix 上均为原子操作
    except Exception:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except: pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


_EMPTY_DB = {
    "next_id": 1,
    "code_index": {},
    "cards": {},
    "card_sets": {},
    "aircraft": {},
}


class JsonStore:
    """单文件 JSON 存储，带编码索引"""

    _lock = threading.Lock()

    _FIELDS = {
        "card": {
            "id": None, "task_code": "", "task_name": "", "category": "机体",
            "task_type": "", "remark": "", "tools": [], "materials": [],
            "tools_confirmed": False, "materials_confirmed": False,
            "set_id": None, "reminder_type": "一般提醒",
        },
        "set": {
            "id": None, "name": "", "description": "", "category": "机体",
            "tools": [], "materials": [],
            "tools_confirmed": False, "materials_confirmed": False,
        },
        "aircraft": {
            "id": None, "reg": "", "model": "", "engine": "",
            "fsn": "", "msn": "", "apu": "",
        },
    }

    def _norm(self, d, kind):
        defaults = self._FIELDS[kind]
        return {k: d.get(k, v) for k, v in defaults.items()}

    # ---------- 初始化 ----------

    def __init__(self, db_path: str):
        self._path = str(db_path)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化或修复数据库"""
        if not os.path.exists(self._path):
            bak = self._path + ".bak"
            if os.path.exists(bak):
                logger.warning("主数据库缺失，从备份恢复")
                shutil.copy2(bak, self._path)
            else:
                self._write(_EMPTY_DB)
                return

        # 验证文件可读
        try:
            self._read()
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"数据库文件损坏: {e}")
            bak = self._path + ".bak"
            if os.path.exists(bak):
                logger.warning("尝试从备份恢复")
                shutil.copy2(bak, self._path)
                try:
                    self._read()
                except Exception:
                    self._write(_EMPTY_DB)
                    return
            else:
                self._write(_EMPTY_DB)
                return

    # ---------- 内部分方法 ----------

    def _read(self) -> dict:
        with open(self._path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        _atomic_write(self._path, data)
        # 自动备份
        try:
            shutil.copy2(self._path, self._path + ".bak")
        except Exception:
            pass  # 备份失败不影响主流程

    def _next_id(self, db: dict) -> int:
        """从 db dict 中取 next_id 并递增。调用方需持有 _lock"""
        nid = db["next_id"]
        db["next_id"] = nid + 1
        return nid

    def _rebuild_index(self, db: dict) -> None:
        """重建编码索引"""
        db["code_index"] = {}
        for cid, card in db.get("cards", {}).items():
            db["code_index"][card["task_code"]] = int(cid)

    # ---------- 工卡 CRUD ----------

    def get_all(self, search: str = "", category: str = "") -> list[dict]:
        db = self._read()
        cards = list(db.get("cards", {}).values())

        if search:
            s = search.lower()
            cards = [
                c for c in cards
                if s in c["task_code"].lower() or s in c.get("task_name", "").lower()
            ]

        if category:
            cards = [c for c in cards if c.get("category") == category]

        # 按 专业 → 工卡号 排序
        cat_order = {c: i for i, c in enumerate(CATEGORIES)}
        cards.sort(key=lambda c: (cat_order.get(c.get("category"), 99), c["task_code"]))
        return cards

    def get(self, card_id: int) -> Optional[dict]:
        db = self._read()
        card = db.get("cards", {}).get(str(card_id))
        return self._norm(card, "card") if card else None

    def find_by_code(self, code: str) -> Optional[dict]:
        db = self._read()
        cid = db.get("code_index", {}).get(code)
        if cid is None:
            return None
        card = db.get("cards", {}).get(str(cid))
        return self._norm(card, "card") if card else None

    def add(self, task_code: str, task_name: str = "",
            category: str = "机体", task_type: str = "",
            remark: str = "") -> Optional[dict]:
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
                "reminder_type": "一般提醒",
            }

            db.setdefault("cards", {})[str(card_id)] = card
            db.setdefault("code_index", {})[task_code] = card_id

            self._write(db)
            return self._norm(card, "card")

    def update(self, card_id: int, **kwargs) -> Optional[dict]:
        with self._lock:
            db = self._read()
            card = db.get("cards", {}).get(str(card_id))
            if card is None:
                return None

            old_code = card.get("task_code")

            for key in ("task_code", "task_name", "category",
                        "task_type", "remark", "tools", "materials",
                        "set_id", "tools_confirmed", "materials_confirmed",
                        "reminder_type"):
                if key in kwargs:
                    card[key] = kwargs[key]

            # 如果编码变了，更新索引
            new_code = card.get("task_code")
            if old_code and old_code != new_code:
                db["code_index"].pop(old_code, None)
                if new_code:
                    db["code_index"][new_code] = card_id

            self._write(db)
            return self._norm(card, "card")

    def delete(self, card_id: int) -> bool:
        with self._lock:
            db = self._read()
            card = db.get("cards", {}).pop(str(card_id), None)
            if card is None:
                return False

            db["code_index"].pop(card.get("task_code"), None)
            self._write(db)
            return True

    # ---------- 工卡组 CRUD ----------

    def get_all_sets(self) -> list[dict]:
        db = self._read()
        sets = [self._norm(s, "set") for s in db.get("card_sets", {}).values()]
        sets.sort(key=lambda s: s.get("name", ""))
        return sets

    def get_set(self, set_id: int) -> Optional[dict]:
        db = self._read()
        s = db.get("card_sets", {}).get(str(set_id))
        return self._norm(s, "set") if s else None

    def add_set(self, name: str, description: str = "",
                category: str = "机体") -> dict:
        with self._lock:
            db = self._read()
            sid = self._next_id(db)
            s = {
                "id": sid,
                "name": name,
                "description": description,
                "category": category,
                "tools": [],
                "materials": [],
                "tools_confirmed": False,
                "materials_confirmed": False,
            }
            db.setdefault("card_sets", {})[str(sid)] = s
            self._write(db)
            return dict(s)

    def update_set(self, set_id: int, **kwargs) -> Optional[dict]:
        with self._lock:
            db = self._read()
            s = db.get("card_sets", {}).get(str(set_id))
            if s is None:
                return None

            for key in ("name", "description", "category", "tools",
                         "materials", "tools_confirmed", "materials_confirmed"):
                if key in kwargs and kwargs[key] is not None:
                    s[key] = kwargs[key]

            self._write(db)
            return dict(s)

    def delete_set(self, set_id: int) -> bool:
        with self._lock:
            db = self._read()
            if str(set_id) not in db.get("card_sets", {}):
                return False

            # 解除关联工卡
            for card in db.get("cards", {}).values():
                if card.get("set_id") == set_id:
                    card["set_id"] = None

            db["card_sets"].pop(str(set_id))
            self._write(db)
            return True

    def get_cards_in_set(self, set_id: int) -> list[dict]:
        db = self._read()
        return [
            self._norm(c, "card") for c in db.get("cards", {}).values()
            if c.get("set_id") == set_id
        ]

    # ---------- 飞机信息 CRUD ----------

    def get_all_aircraft(self) -> list[dict]:
        db = self._read()
        aircraft = list(db.get("aircraft", {}).values())
        aircraft.sort(key=lambda a: a.get("reg", ""))
        return [self._norm(a, "aircraft") for a in aircraft]

    def get_aircraft(self, aircraft_id: int) -> Optional[dict]:
        db = self._read()
        ac = db.get("aircraft", {}).get(str(aircraft_id))
        return self._norm(ac, "aircraft") if ac else None

    def find_aircraft_by_reg(self, reg: str):
        for a in self._read().get("aircraft", {}).values():
            if a.get("reg") == reg:
                return self._norm(a, "aircraft")
        return None

    def add_aircraft(self, reg: str, model: str = "",
                     engine: str = "", fsn: str = "", msn: str = "", apu: str = "") -> dict:
        with self._lock:
            db = self._read()
            ac_id = self._next_id(db)
            ac = {
                "id": ac_id,
                "reg": reg,
                "model": model,
                "engine": engine,
                "fsn": fsn,
                "msn": msn,
                "apu": apu,
            }
            db.setdefault("aircraft", {})[str(ac_id)] = ac
            self._write(db)
            return self._norm(ac, "aircraft")

    def update_aircraft(self, aircraft_id: int, **kwargs) -> Optional[dict]:
        with self._lock:
            db = self._read()
            ac = db.get("aircraft", {}).get(str(aircraft_id))
            if ac is None:
                return None

            for key in ("reg", "model", "engine", "fsn", "msn", "apu"):
                if key in kwargs:
                    ac[key] = kwargs[key]

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
        return sorted(wps, key=lambda x: x.get("date", ""), reverse=True)

    def get_work_package(self, package_id: str) -> Optional[dict]:
        db = self._read()
        for wp in db.get("work_packages", []):
            if wp.get("package_id") == package_id:
                return dict(wp)
        return None

    def delete_aircraft(self, aircraft_id: int) -> bool:
        with self._lock:
            db = self._read()
            if str(aircraft_id) not in db.get("aircraft", {}):
                return False
            db["aircraft"].pop(str(aircraft_id))
            self._write(db)
            return True

    # ---------- 工卡组同步 ----------

    def sync_set_to_cards(self, set_id: int) -> None:
        """将工卡组的工具/航材同步到组内所有卡，主工卡保留原数据但加 set_id"""
        with self._lock:
            db = self._read()
            s = db.get("card_sets", {}).get(str(set_id))
            if not s:
                return
            tools = s.get("tools", [])
            materials = s.get("materials", [])
            for card in db.get("cards", {}).values():
                if card.get("set_id") == set_id:
                    card["tools"] = list(tools)
                    card["materials"] = list(materials)
            self._write(db)
