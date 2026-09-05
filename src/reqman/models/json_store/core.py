"""JsonStore 核心：持久化机制 + 共享常量/辅助。

特点：
1. 原子写入 — 先写临时文件再 rename，防止写入中途崩溃损坏数据
2. 编码倒排索引 — O(1) 按工卡号查找
3. 线程锁 — 保证 ID 生成的原子性
4. 自动备份 — 每次保存后复制 .bak
5. 启动自愈 — 如果主文件损坏，自动从 .bak 恢复

各类业务方法（工卡/工卡组/飞机/工作包/库存预警/日志）拆分到同包的
card_store / work_package_store / log_store 子模块，统一继承 JsonStoreCore。
"""

import copy
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _atomic_write(path: str, data: dict) -> None:
    """原子写入 JSON，使用唯一临时文件并尽力刷新到磁盘。"""
    directory = os.path.dirname(path) or "."
    base = os.path.basename(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{base}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                logger.debug("文件 fsync 不可用: %s", path)
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        try:
            dir_fd = os.open(directory, getattr(os, "O_DIRECTORY", 0))
        except (OSError, TypeError):
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            except OSError:
                logger.debug("目录 fsync 不可用: %s", directory)
            finally:
                os.close(dir_fd)
    except (OSError, TypeError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _today_iso() -> str:
    """当前北京日期 YYYY-MM-DD，用于条目新建/编辑日志时间。"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


_EMPTY_DB = {
    "next_id": 1,
    "code_index": {},
    "cards": {},
    "card_sets": {},
    "aircraft": {},
    "card_logs": [],
    "card_log_next_id": 1,
}

# 操作日志保留上限：每次新增日志后自动清理多余旧条目
MAX_LOGS = 500

# 运行时数据（不纳入 Git 追踪）的键列表
_RUNTIME_KEYS = {
    "work_packages",
    "next_id",
    "code_index",
}
_GENERATION_KEY = "__generation"


class JsonStoreCorruptionError(RuntimeError):
    """JSON 存储损坏或代际不一致，拒绝覆盖现场。"""


class JsonStoreCore:
    """双文件 JSON 存储核心机制：核心数据（飞机/工卡/工卡组/日志）+ 运行时数据（工作包/计数器）

    核心数据默认受 Git 追踪，运行时数据（_RUNTIME_KEYS）写入独立文件，
    应在 .gitignore 中忽略运行时文件。
    """

    _lock = threading.RLock()

    _FIELDS: ClassVar[dict] = {
        "card": {
            "id": None, "task_code": "", "task_name": "", "category": "机体",
            "task_type": "", "remark": "", "tools": [], "materials": [],
            "tools_confirmed": False, "materials_confirmed": False,
            "set_id": None, "reminder_type": "", "card_ok": False, "reminder_confirmed": False,
            "write_date": "", "log_time": "",
        },
        "set": {
            "id": None, "name": "", "description": "", "category": "机体",
            "tools": [], "materials": [],
            "tools_confirmed": False, "materials_confirmed": False,
            "reminder_type": "", "card_ok": False, "reminder_confirmed": False,
            "log_time": "",
        },
        "aircraft": {
            "id": None, "reg": "", "model": "", "engine": "",
            "fsn": "", "msn": "", "apu": "", "log_time": "",
        },
    }

    # 字段映射表（用于变更检测）
    _CARD_FIELDS: ClassVar[list] = ["task_code", "task_name", "category", "task_type", "remark",
                    "tools", "materials", "tools_confirmed", "materials_confirmed",
                    "set_id", "reminder_type", "card_ok", "reminder_confirmed", "write_date"]
    _SET_FIELDS: ClassVar[list] = ["name", "description", "category", "tools", "materials",
                   "tools_confirmed", "materials_confirmed",
                   "reminder_type", "card_ok", "reminder_confirmed"]
    _AIRCRAFT_FIELDS: ClassVar[list] = ["reg", "model", "engine", "fsn", "msn", "apu"]

    def _norm(self, d, kind):
        defaults = self._FIELDS[kind]
        return {k: copy.deepcopy(d.get(k, v)) for k, v in defaults.items()}

    # ---------- 初始化 ----------

    def __init__(self, db_path: str):
        self._path = str(db_path)
        base, ext = os.path.splitext(self._path)
        self._runtime_path = base + "_runtime" + ext
        self._corrupt = False  # 读损坏标志：置位期间拒绝一切写入
        self._corrupt_files: set[str] = set()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库；损坏或缺失且无有效备份时 fail-closed，绝不清空现场。"""
        with self._lock:
            core_exists = os.path.exists(self._path)
            runtime_exists = os.path.exists(self._runtime_path)
            if not core_exists and not runtime_exists:
                backup = self._valid_backup(self._path + ".bak")
                if backup is not None:
                    self._restore_file(self._path, backup)
                    core_exists = True
                else:
                    self._write(copy.deepcopy(_EMPTY_DB))
                    return
            if not core_exists:
                backup = self._valid_backup(self._path + ".bak")
                if backup is None:
                    raise JsonStoreCorruptionError(
                        f"核心数据库缺失且无有效备份：{self._path}"
                    )
                self._restore_file(self._path, backup)
            if not runtime_exists:
                runtime_backup = self._valid_backup(self._runtime_path + ".bak")
                if runtime_backup is not None:
                    self._restore_file(self._runtime_path, runtime_backup)
                else:
                    # runtime 是由旧版单文件或旧测试夹具派生的可重建部分，
                    # 创建空 runtime 不会覆盖核心业务数据。
                    logger.warning("运行时数据库缺失，创建空 runtime: %s", self._runtime_path)
                    _atomic_write(self._runtime_path, {})
            self._read()
            if self._corrupt:
                corrupt_files = sorted(self._corrupt_files)
                for path in corrupt_files:
                    backup = self._valid_backup(path + ".bak")
                    if backup is None:
                        logger.error("数据库文件无有效备份，保留现场并拒绝启动: %s", path)
                        raise JsonStoreCorruptionError(
                            "数据库文件损坏且无可用备份：" + path
                        )
                    self._restore_file(path, backup)
                self._read()
                if self._corrupt:
                    logger.error("数据库无法安全恢复，保留现场并拒绝启动：%s", corrupt_files)
                    raise JsonStoreCorruptionError(
                        "数据库文件损坏或代际不一致：" + ", ".join(corrupt_files)
                    )
                logger.warning("数据库已从有效备份恢复")

    @staticmethod
    def _validate_payload(data: dict) -> None:
        """校验 JSON 数据结构；兼容旧数据的缺字段，但拒绝错误类型。"""
        if not isinstance(data, dict):
            raise TypeError("JSON 根节点必须是对象")
        expected = {
            "cards": dict,
            "card_sets": dict,
            "aircraft": dict,
            "card_logs": list,
            "inventory_warnings": list,
            "work_packages": list,
            "code_index": dict,
        }
        for key, type_ in expected.items():
            if key in data and not isinstance(data[key], type_):
                raise TypeError(f"字段 {key} 类型错误")
        for key in ("next_id", "card_log_next_id"):
            if key in data and (isinstance(data[key], bool) or not isinstance(data[key], int) or data[key] < 1):
                raise TypeError(f"字段 {key} 类型错误")
        for collection in ("cards", "card_sets", "aircraft"):
            if collection in data and any(not isinstance(item, dict) for item in data[collection].values()):
                raise ValueError(f"字段 {collection} 包含非对象记录")

    def _valid_backup(self, path: str):
        """校验备份为可用对象；无效备份返回 None。"""
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._validate_payload(data)
            return data
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("备份文件无效: %s (%s)", path, exc)
        return None

    def _restore_file(self, path: str, data: dict) -> None:
        """通过原子写恢复文件，保留损坏文件现场。"""
        _atomic_write(path, data)

    def _is_legacy_single_file(self) -> bool:
        """判断核心文件是否包含旧版单文件运行时键。"""
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return isinstance(data, dict) and any(k in data for k in _RUNTIME_KEYS)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return False

    # ---------- 内部分方法 ----------

    def _read(self) -> dict:
        """在同一锁内读取并合并 core/runtime，拒绝错误结构和混合代际。"""
        with self._lock:
            self._corrupt = False
            self._corrupt_files = set()
            loaded = []
            db = {}
            for path in (self._path, self._runtime_path):
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, encoding="utf-8") as f:
                        value = json.load(f)
                    self._validate_payload(value)
                    loaded.append(value)
                except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    self._corrupt = True
                    self._corrupt_files.add(path)
                    logger.warning("数据库文件读取失败: %s (%s)", path, exc)
            for value in loaded:
                db.update(value)
            generations = {value.get(_GENERATION_KEY) for value in loaded if value.get(_GENERATION_KEY)}
            if len(generations) > 1:
                self._corrupt = True
                self._corrupt_files.update((self._path, self._runtime_path))
                logger.error("核心与运行时数据库代际不一致: %s", generations)
            db.pop("next_ac_id", None)
            db.pop("amro_sync_meta", None)
            if db.get("cards") and not self._index_ok(db):
                logger.warning("code_index 校验失败，已重建索引")
                self._rebuild_index(db)
            max_id = 0
            for coll in ("cards", "card_sets", "aircraft"):
                for key in db.get(coll, {}):
                    try:
                        max_id = max(max_id, int(key))
                    except (TypeError, ValueError):
                        pass
            if db.get("next_id", 1) <= max_id:
                logger.warning("next_id=%s 落后于现存实体最大ID=%d，自愈为 %d", db.get("next_id"), max_id, max_id + 1)
                db["next_id"] = max_id + 1
            return db

    def _write(self, data: dict) -> None:
        """以同一 generation 写入 core/runtime，并只发布完整可读代际。"""
        with self._lock:
            if self._corrupt:
                raise JsonStoreCorruptionError(
                    "数据库文件读取失败（损坏或代际不一致），已拒绝写入以保护数据；"
                    "请从 data/*.json.bak 或 data/backups/ 恢复后重启应用"
                )
            if data.get("cards") and not self._index_ok(data):
                self._rebuild_index(data)
            generation = uuid.uuid4().hex
            core = {}
            runtime = {}
            for key, value in data.items():
                if key in _RUNTIME_KEYS:
                    runtime[key] = value
                else:
                    core[key] = value
            core[_GENERATION_KEY] = generation
            runtime[_GENERATION_KEY] = generation
            old_core = self._read_raw(self._path)
            _atomic_write(self._path, core)
            try:
                _atomic_write(self._runtime_path, runtime)
            except Exception:
                if old_core is not None:
                    _atomic_write(self._path, old_core)
                raise
            self._backup_pair(core, runtime)
            self._corrupt = False
            self._corrupt_files = set()

    @staticmethod
    def _read_raw(path: str):
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def _backup_pair(self, core: dict, runtime: dict) -> None:
        """分别原子更新备份；主文件已完整发布后才更新备份。"""
        try:
            _atomic_write(self._path + ".bak", core)
            _atomic_write(self._runtime_path + ".bak", runtime)
        except OSError:
            logger.warning("数据库备份更新失败")

    def _next_id(self, db: dict) -> int:
        """从 db dict 中取 next_id 并递增，跳过已占用的实体 ID（cards/sets/aircraft 共用计数器）。
        调用方需持有 _lock"""
        nid = db.get("next_id", 1)
        taken = set()
        for coll in ("cards", "card_sets", "aircraft"):
            taken.update(str(k) for k in db.get(coll, {}))
        while str(nid) in taken:
            nid += 1
        db["next_id"] = nid + 1
        return nid

    def _rebuild_index(self, db: dict) -> None:
        """重建编码索引（缺 task_code 的卡跳过；重复码以后写入者为准并告警）"""
        db["code_index"] = {}
        coded = 0
        for card_id, card in db.get("cards", {}).items():
            code = card.get("task_code")
            if code:
                db["code_index"][code] = int(card_id)
                coded += 1
        if len(db["code_index"]) != coded:
            logger.warning("检测到重复工卡号，索引以后写入者为准，请检查数据")

    @staticmethod
    def _index_ok(db: dict) -> bool:
        """索引双向校验：每个键指向的卡存在且 task_code 匹配、有码卡数量一致。
        能查出条数比较查不出的悬挂/错映射（如卡删除后索引残留）"""
        cards = db["cards"]
        ci = db.get("code_index", {})
        cards_with_code = 0
        for cid, card in cards.items():
            code = card.get("task_code")
            if not code:
                continue
            cards_with_code += 1
            if ci.get(code) != int(cid):
                return False
        return len(ci) == cards_with_code

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
        # 自动清理：仅保留最新 MAX_LOGS 条（时间平局时按自增 id 判定新旧）
        logs = db["card_logs"]
        if len(logs) > MAX_LOGS:
            logs.sort(key=lambda item: (item.get("timestamp", ""), item.get("id", 0)), reverse=True)
            db["card_logs"] = logs[:MAX_LOGS]
        return log
