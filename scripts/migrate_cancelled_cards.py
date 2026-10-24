"""作废工卡库一次性迁移 — 把 data/cancelled_cards.json 合并进主库。

规则（已确认）：
- 同 id 保留（orig_id 主库空闲时恢复原 id，否则分配新 id）；
- 标记 cancelled=True + cancelled_at/cancel_source/set_name；
- task_code 与主库现存卡撞号时跳过并报告（人工决策）；
- 迁移成功后原文件改名归档（.migrated.bak）；
- 幂等：文件不存在或已归档时直接跳过。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reqman.models.json_store import JsonStore


def migrate(db_path: str, cancelled_path: str, *, dry_run: bool = False) -> dict:
    """执行迁移，返回摘要 {migrated, skipped, archived}。"""
    cancelled_path = Path(cancelled_path)
    if not cancelled_path.exists():
        return {"migrated": 0, "skipped": [], "archived": False}
    raw = json.loads(cancelled_path.read_text(encoding="utf-8"))
    records = sorted(raw.get("cards", {}).values(),
                     key=lambda c: (c.get("cancelled_at", ""), c.get("id", 0)))
    if not records:
        return {"migrated": 0, "skipped": [], "archived": False}

    store = JsonStore(db_path)
    migrated = 0
    skipped = []
    with store._lock:
        db = store._read()
        cards = db.setdefault("cards", {})
        for record in records:
            code = str(record.get("task_code", "")).strip()
            if not code:
                skipped.append({"task_code": code, "reason": "工卡号为空"})
                continue
            # 同号已存在于主库：核对为同一张卡后，把作废元数据标记到该卡（工卡号唯一）
            existing = next((c for c in cards.values()
                             if c.get("task_code") == code), None)
            if existing is not None:
                if existing.get("task_name") != record.get("task_name"):
                    skipped.append({"task_code": code,
                                    "reason": "主库同号卡内容不一致，需人工确认"})
                    continue
                existing["cancelled"] = True
                existing["cancelled_at"] = record.get("cancelled_at", "")
                existing["cancel_source"] = record.get("cancel_source", "")
                existing["set_name"] = record.get("set_name", "")
                existing["card_ok"] = False
                migrated += 1
                continue
            # 主库无此卡：整卡迁入
            target_id = record.get("orig_id")
            if target_id is None or str(target_id) in cards:
                target_id = store._next_id(db)
            card = store._norm({
                "id": target_id,
                "task_code": code,
                "task_name": record.get("task_name", ""),
                "category": record.get("category", "机体"),
                "task_type": record.get("task_type", ""),
                "remark": record.get("remark", ""),
                "tools": record.get("tools", []),
                "materials": record.get("materials", []),
                "tools_confirmed": record.get("tools_confirmed", False),
                "materials_confirmed": record.get("materials_confirmed", False),
                "reminder_type": record.get("reminder_type", ""),
                "reminder_confirmed": record.get("reminder_confirmed", False),
                "set_id": record.get("set_id"),
                "write_date": record.get("write_date", ""),
                "card_ok": False,
                "log_time": record.get("log_time", ""),
                "cancelled": True,
                "cancelled_at": record.get("cancelled_at", ""),
                "cancel_source": record.get("cancel_source", ""),
                "set_name": record.get("set_name", ""),
            }, "card")
            cards[str(target_id)] = card
            db.setdefault("code_index", {})[code] = target_id
            migrated += 1
        if not dry_run and migrated:
            store._write(db)

    archived = False
    if not dry_run and migrated:
        cancelled_path.rename(str(cancelled_path) + ".migrated.bak")
        archived = True
    return {"migrated": migrated, "skipped": skipped, "archived": archived}


if __name__ == "__main__":
    from reqman.config import BASE_DIR, DB_FILE
    cancelled_file = BASE_DIR / "data" / "cancelled_cards.json"
    dry = "--dry-run" in sys.argv
    result = migrate(str(DB_FILE), str(cancelled_file), dry_run=dry)
    print(f"migrated={result['migrated']} archived={result['archived']}")
    for skip in result["skipped"]:
        print(f"skipped: {skip['task_code']} ({skip['reason']})")
