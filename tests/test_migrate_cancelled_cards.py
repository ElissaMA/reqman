"""作废工卡库合并主库迁移脚本测试（四分支 + 幂等 + dry-run）。"""
import json
from pathlib import Path

from reqman.models.json_store import JsonStore
from scripts.migrate_cancelled_cards import migrate


def _write_cancelled(path: Path, records: list[dict]) -> None:
    cards = {str(r["id"]): r for r in records}   # 作废库文件为 id 键 dict
    Path(path).write_text(json.dumps({"cards": cards}, ensure_ascii=False), encoding="utf-8")


def _record(code, name="旧卡", orig_id=1, cancelled_at="2026-09-03 10:00:00"):
    return {"id": 900 + orig_id, "orig_id": orig_id, "task_code": code, "task_name": name,
            "category": "机体", "task_type": "", "remark": "", "tools": [], "materials": [],
            "tools_confirmed": True, "materials_confirmed": True,
            "reminder_type": "", "reminder_confirmed": True,
            "set_id": None, "write_date": "2026-01-01", "log_time": "",
            "cancelled_at": cancelled_at, "cancel_source": "manual", "set_name": "组X"}


class TestMigrateCancelledCards:
    def test_migrates_whole_card_with_orig_id(self, tmp_path):
        """主库无此卡：整卡迁入并复用 orig_id，元数据齐全"""
        db_path = str(tmp_path / "main.json")
        JsonStore(db_path)
        src = tmp_path / "cancelled.json"
        _write_cancelled(src, [_record("CANC-1", orig_id=7)])

        result = migrate(db_path, str(src))

        assert result["migrated"] == 1 and result["archived"] is True
        store = JsonStore(db_path)
        card = store.find_by_code("CANC-1")
        assert card["id"] == 7                       # orig_id 复用
        assert card["cancelled"] is True
        assert card["cancel_source"] == "manual"
        assert card["set_name"] == "组X"
        assert not src.exists()                      # 原文件归档
        assert Path(str(src) + ".migrated.bak").exists()

    def test_orig_id_taken_allocates_new(self, tmp_path):
        """orig_id 被占用：分配新 id 迁入，不覆盖现有卡"""
        db_path = str(tmp_path / "main.json")
        store = JsonStore(db_path)
        existing = store.add("KEEP-1", "占用7号id的卡", "机体", "", "")
        assert existing["id"] == 1
        # 手动占用 id 7：直接构造
        with store._lock:
            db = store._read()
            db["cards"]["7"] = store._norm({"id": 7, "task_code": "KEEP-7"}, "card")
            store._write(db)
        src = tmp_path / "cancelled.json"
        _write_cancelled(src, [_record("CANC-2", orig_id=7)])

        result = migrate(db_path, str(src))

        assert result["migrated"] == 1
        store2 = JsonStore(db_path)
        assert store2.find_by_code("KEEP-7") is not None   # 原卡未被覆盖
        migrated = store2.find_by_code("CANC-2")
        assert migrated["id"] not in (1, 7)

    def test_same_code_same_name_marks_existing(self, tmp_path):
        """同号同名：只把作废元数据标记到主库现有卡（工卡号唯一）"""
        db_path = str(tmp_path / "main.json")
        store = JsonStore(db_path)
        store.add("DUP-1", "同名卡", "机体", "", "")
        src = tmp_path / "cancelled.json"
        _write_cancelled(src, [_record("DUP-1", name="同名卡", orig_id=99)])

        result = migrate(db_path, str(src))

        assert result["migrated"] == 1 and result["skipped"] == []
        store2 = JsonStore(db_path)
        cards = [c for c in store2.get_all(include_cancelled=True) if c["task_code"] == "DUP-1"]
        assert len(cards) == 1                       # 不产生第二条记录
        assert cards[0]["cancelled"] is True
        assert cards[0]["set_name"] == "组X"

    def test_same_code_diff_name_skipped(self, tmp_path):
        """同号不同名：跳过并报告，交人工决策"""
        db_path = str(tmp_path / "main.json")
        store = JsonStore(db_path)
        store.add("DUP-2", "主库卡", "机体", "", "")
        src = tmp_path / "cancelled.json"
        _write_cancelled(src, [_record("DUP-2", name="作废库卡", orig_id=99)])

        result = migrate(db_path, str(src))

        assert result["migrated"] == 0
        assert result["skipped"][0]["task_code"] == "DUP-2"
        assert "不一致" in result["skipped"][0]["reason"]
        assert src.exists()                          # 未归档
        assert JsonStore(db_path).find_by_code("DUP-2")["cancelled"] is False

    def test_dry_run_writes_nothing(self, tmp_path):
        """dry-run：不写主库、不归档"""
        db_path = str(tmp_path / "main.json")
        JsonStore(db_path)
        src = tmp_path / "cancelled.json"
        _write_cancelled(src, [_record("DRY-1", orig_id=5)])

        result = migrate(db_path, str(src), dry_run=True)

        assert result["migrated"] == 1 and result["archived"] is False
        assert src.exists()
        assert JsonStore(db_path).find_by_code("DRY-1") is None

    def test_idempotent_when_file_gone(self, tmp_path):
        """幂等：文件不存在（已迁/无作废库）直接返回 0"""
        db_path = str(tmp_path / "main.json")
        JsonStore(db_path)
        result = migrate(db_path, str(tmp_path / "nonexistent.json"))
        assert result == {"migrated": 0, "skipped": [], "archived": False}

    def test_empty_code_skipped(self, tmp_path):
        """空工卡号：跳过并报告"""
        db_path = str(tmp_path / "main.json")
        JsonStore(db_path)
        src = tmp_path / "cancelled.json"
        _write_cancelled(src, [_record("", orig_id=3)])

        result = migrate(db_path, str(src))

        assert result["migrated"] == 0
        assert result["skipped"][0]["reason"] == "工卡号为空"
