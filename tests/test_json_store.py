"""JsonStore 单元测试"""
import json
import os
import shutil
from pathlib import Path

import pytest

from reqman.models.json_store import JsonStore


class TestInit:
    def test_init_creates_file(self, json_store: JsonStore, tmp_db_path: str):
        assert os.path.exists(tmp_db_path)

    def test_init_contents(self, json_store: JsonStore):
        data = json_store._read()
        assert "cards" in data
        assert "card_sets" in data
        assert "aircraft" in data

    def test_double_init(self, tmp_db_path: str):
        JsonStore(tmp_db_path)
        JsonStore(tmp_db_path)


class TestAtomicWrite:
    def test_valid_json(self, json_store: JsonStore):
        data = json_store._read()
        assert isinstance(data, dict)
        assert "cards" in data

    def test_bak_file_restore(self, tmp_path: Path):
        db_path = str(tmp_path / "restore_test.json")
        store = JsonStore(db_path)
        store.add("BACKUP-TASK", "备份测试", "发动机", "A", "")
        shutil.copy2(db_path, db_path + ".bak")
        os.remove(db_path)
        store2 = JsonStore(db_path)
        codes = [c["task_code"] for c in store2.get_all()]
        assert "BACKUP-TASK" in codes


class TestCardCRUD:
    """注意: add() 返回 dict（含 id），get/delete/update 均接受 int id"""

    def test_add(self, json_store: JsonStore):
        r = json_store.add("CARD-001", "测试工卡", "发动机", "A", "")
        card = json_store.get(r["id"])
        assert card["task_code"] == "CARD-001"

    def test_get_not_found(self, json_store: JsonStore):
        assert json_store.get(999) is None

    def test_update(self, json_store: JsonStore):
        r = json_store.add("CARD-001", "旧名称", "发动机", "A", "")
        json_store.update(r["id"], task_name="新名称")
        assert json_store.get(r["id"])["task_name"] == "新名称"

    def test_delete(self, json_store: JsonStore):
        r = json_store.add("CARD-001", "待删除", "发动机", "A", "")
        assert json_store.delete(r["id"]) is True
        assert json_store.get(r["id"]) is None

    def test_delete_not_found(self, json_store: JsonStore):
        assert json_store.delete(999) is False

    def test_get_all(self, json_store: JsonStore):
        json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        json_store.add("CARD-002", "工卡2", "电子", "B", "")
        assert len(json_store.get_all()) == 2

    def test_get_all_with_search(self, json_store: JsonStore):
        json_store.add("ENG-001", "发动机检查", "发动机", "A", "")
        json_store.add("ELE-001", "电子检查", "电子", "B", "")
        assert len(json_store.get_all(search="发动机")) == 1

    def test_get_all_with_category(self, json_store: JsonStore):
        json_store.add("ENG-001", "发动机检查", "发动机", "A", "")
        json_store.add("ELE-001", "电子检查", "电子", "B", "")
        assert len(json_store.get_all(category="电子")) == 1

    def test_find_by_code(self, json_store: JsonStore):
        json_store.add("UNIQUE-001", "编码测试", "发动机", "A", "")
        card = json_store.find_by_code("UNIQUE-001")
        assert card is not None and card["task_code"] == "UNIQUE-001"

    def test_find_by_code_not_found(self, json_store: JsonStore):
        assert json_store.find_by_code("NON-EXIST") is None

    def test_duplicate_code_returns_none(self, json_store: JsonStore):
        json_store.add("DUP-001", "工卡1", "发动机", "A", "")
        r2 = json_store.add("DUP-001", "工卡2", "发动机", "A", "")
        assert r2 is None


class TestCardSetCRUD:
    def test_add_set(self, json_store: JsonStore):
        r = json_store.add_set(name="测试组", description="测试用", category="发动机")
        s = json_store.get_set(r["id"])
        assert s["name"] == "测试组"

    def test_get_set_not_found(self, json_store: JsonStore):
        assert json_store.get_set(999) is None

    def test_update_set(self, json_store: JsonStore):
        r = json_store.add_set(name="旧名称", description="测试", category="发���机")
        json_store.update_set(r["id"], name="新名称")
        assert json_store.get_set(r["id"])["name"] == "新名称"

    def test_delete_set(self, json_store: JsonStore):
        r = json_store.add_set(name="待删除", description="测试", category="发动机")
        assert json_store.delete_set(r["id"]) is True
        assert json_store.get_set(r["id"]) is None

    def test_delete_set_not_found(self, json_store: JsonStore):
        assert json_store.delete_set(999) is False

    def test_get_all_sets(self, json_store: JsonStore):
        json_store.add_set(name="组A", description="", category="发动机")
        json_store.add_set(name="组B", description="", category="电子")
        assert len(json_store.get_all_sets()) == 2

    def test_get_cards_in_set(self, json_store: JsonStore):
        r_set = json_store.add_set(name="测试组", description="", category="发动机")
        c1 = json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        c2 = json_store.add("CARD-002", "工卡2", "发动机", "A", "")
        json_store.update(c1["id"], set_id=r_set["id"])
        json_store.update(c2["id"], set_id=r_set["id"])
        assert len(json_store.get_cards_in_set(r_set["id"])) == 2


class TestAircraftCRUD:
    def test_add_aircraft(self, json_store: JsonStore):
        r = json_store.add_aircraft(reg="B-1234", model="A320", engine="CFM56",
                                     fsn="1234", msn="5678", apu="APU-001")
        ac = json_store.get_aircraft(r["id"])
        assert ac["reg"] == "B-1234"
        assert ac["model"] == "A320"

    def test_get_aircraft_not_found(self, json_store: JsonStore):
        assert json_store.get_aircraft(999) is None

    def test_update_aircraft(self, json_store: JsonStore):
        r = json_store.add_aircraft(reg="B-1234", model="A320", engine="",
                                     fsn="", msn="", apu="")
        json_store.update_aircraft(r["id"], model="B737")
        assert json_store.get_aircraft(r["id"])["model"] == "B737"

    def test_delete_aircraft(self, json_store: JsonStore):
        r = json_store.add_aircraft(reg="B-1234", model="A320", engine="",
                                     fsn="", msn="", apu="")
        assert json_store.delete_aircraft(r["id"]) is True
        assert json_store.get_aircraft(r["id"]) is None

    def test_get_all_aircraft(self, json_store: JsonStore):
        json_store.add_aircraft(reg="B-1234", model="A320", engine="", fsn="", msn="", apu="")
        json_store.add_aircraft(reg="B-5678", model="B737", engine="", fsn="", msn="", apu="")
        assert len(json_store.get_all_aircraft()) == 2

    def test_find_aircraft_by_reg(self, json_store: JsonStore):
        json_store.add_aircraft(reg="B-1234", model="A320", engine="CFM56",
                                 fsn="", msn="", apu="")
        ac = json_store.find_aircraft_by_reg("B-1234")
        assert ac is not None and ac["model"] == "A320"

    def test_find_aircraft_by_reg_not_found(self, json_store: JsonStore):
        assert json_store.find_aircraft_by_reg("NON-EXIST") is None


class TestPersistence:
    def test_data_saved_to_disk(self, tmp_db_path: str):
        store = JsonStore(tmp_db_path)
        store.add("PERSIST-001", "持久性测试", "发动机", "A", "")
        del store
        store2 = JsonStore(tmp_db_path)
        codes = [c["task_code"] for c in store2.get_all()]
        assert "PERSIST-001" in codes

    def test_data_consistency(self, json_store: JsonStore):
        json_store.add("C-001", "工卡1", "发动机", "A", "")
        json_store.add("C-002", "工卡2", "电子", "B", "")
        json_store.delete(1)
        json_store.add_set(name="组1", description="", category="发动机")
        assert len(json_store.get_all()) == 1
        assert json_store.get_all()[0]["task_code"] == "C-002"
        assert len(json_store.get_all_sets()) == 1
