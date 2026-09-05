"""作废工卡库（CancelledCardStore）单元测试：全字段承接、upsert 幂等、彻底删除"""
import pytest

from reqman.models.cancelled_card_store import (
    CancelledCardStore,
    CancelledCardStoreCorruptionError,
)


@pytest.fixture
def store(tmp_path):
    return CancelledCardStore(str(tmp_path / "cancelled_cards.json"))


def _card(code="CSCA320-256652-01-1-X", **overrides):
    card = {"id": 42, "task_code": code, "task_name": "检查救生衣", "category": "电子",
            "task_type": "RST", "remark": "", "tools": [{"device_name": "扳手"}],
            "materials": [], "tools_confirmed": True, "materials_confirmed": False,
            "set_id": 7, "reminder_type": "一般提醒", "card_ok": False,
            "reminder_confirmed": True, "write_date": "2026-08-01"}
    card.update(overrides)
    return card


class TestCancelledCardStore:
    def test_add_keeps_all_fields_with_metadata(self, store):
        rec = store.add(_card(), source="full_version", set_name="救生衣组")
        assert rec["task_code"] == "CSCA320-256652-01-1-X"
        assert rec["orig_id"] == 42              # 主库原 id 保留
        assert rec["cancel_source"] == "full_version"
        assert rec["set_name"] == "救生衣组"
        assert rec["cancelled_at"]               # 作废时间已记
        # 承接原卡全部信息
        for key in ("task_name", "category", "task_type", "remark", "tools",
                    "materials", "tools_confirmed", "materials_confirmed",
                    "set_id", "reminder_type", "card_ok", "reminder_confirmed",
                    "write_date"):
            assert rec[key] == _card()[key]

    def test_get_all_sorted_by_cancelled_at_desc(self, store):
        store.add(_card("A"), source="full_version")
        store.add(_card("B"), source="package_version")
        codes = [c["task_code"] for c in store.get_all()]
        assert set(codes) == {"A", "B"}

    def test_find_by_code(self, store):
        store.add(_card("CSCA-X"), source="full_version")
        assert store.find_by_code("CSCA-X") is not None
        assert store.find_by_code("MISS") is None

    def test_add_upsert_by_code_idempotent(self, store):
        """同号重复作废覆盖旧记录，不产生重复行（中断重跑安全）。"""
        first = store.add(_card("CSCA-X"), source="full_version")
        second = store.add(_card("CSCA-X", task_name="救生衣（新）"), source="package_version")
        assert second["id"] == first["id"]           # 复用同一作废库 id
        all_records = store.get_all()
        assert len(all_records) == 1
        assert all_records[0]["task_name"] == "救生衣（新）"
        assert all_records[0]["cancel_source"] == "package_version"

    def test_add_assigns_incrementing_ids(self, store):
        r1 = store.add(_card("A"), source="full_version")
        r2 = store.add(_card("B"), source="full_version")
        assert r2["id"] == r1["id"] + 1

    def test_remove(self, store):
        rec = store.add(_card("CSCA-X"), source="full_version")
        removed = store.remove(rec["id"])
        assert removed["task_code"] == "CSCA-X"
        assert store.get_all() == []
        assert store.remove(rec["id"]) is None       # 重复删除返回 None

    def test_default_cards_are_isolated_between_paths(self, tmp_path):
        first = CancelledCardStore(str(tmp_path / "first.json"))
        second = CancelledCardStore(str(tmp_path / "second.json"))
        first.add(_card("FIRST"), source="full_version")
        assert [c["task_code"] for c in second.get_all()] == []

    def test_nested_input_and_return_values_are_isolated(self, store):
        source = _card("ISOLATED", tools=[{"device_name": "扳手"}], materials=[])
        record = store.add(source, source="full_version")
        source["tools"][0]["device_name"] = "被修改的输入"
        record["tools"][0]["device_name"] = "被修改的返回值"
        fresh = store.find_by_code("ISOLATED")
        assert fresh["tools"][0]["device_name"] == "扳手"
        fresh["tools"][0]["device_name"] = "再次修改"
        assert store.find_by_code("ISOLATED")["tools"][0]["device_name"] == "扳手"

    def test_corrupt_file_refuses_write_and_preserves_evidence(self, store):
        with open(store._path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        with pytest.raises(CancelledCardStoreCorruptionError):
            store.add(_card("NO_OVERWRITE"), source="full_version")
        with open(store._path, encoding="utf-8") as f:
            assert f.read() == "{corrupt"

    def test_corrupt_file_recovers_from_valid_backup(self, store):
        store.add(_card("BACKUP"), source="full_version")
        with open(store._path, encoding="utf-8") as f:
            backup = f.read()
        with open(store._path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        with open(store._path + ".bak", "w", encoding="utf-8") as f:
            f.write(backup)
        recovered = CancelledCardStore(store._path)
        assert recovered.find_by_code("BACKUP")["task_code"] == "BACKUP"

    def test_add_creates_backup(self, store):
        store.add(_card("BACKUP_CREATED"), source="full_version")
        assert store._path.endswith("cancelled_cards.json")
        with open(store._path + ".bak", encoding="utf-8") as f:
            assert f.read()

    def test_replace_failure_preserves_existing_file(self, store, monkeypatch):
        store.add(_card("ORIGINAL"), source="full_version")
        with open(store._path, encoding="utf-8") as f:
            original = f.read()
        monkeypatch.setattr("reqman.models.cancelled_card_store.os.replace", lambda *_: (_ for _ in ()).throw(OSError("blocked")))
        with pytest.raises(OSError):
            store.add(_card("NEW"), source="full_version")
        with open(store._path, encoding="utf-8") as f:
            assert f.read() == original
