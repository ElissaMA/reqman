"""作废工卡库（CancelledCardStore）单元测试：全字段承接、upsert 幂等、彻底删除"""
import pytest

from reqman.models.cancelled_card_store import CancelledCardStore


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
