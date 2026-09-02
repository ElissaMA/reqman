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


class TestReminderFields:
    def test_card_defaults(self, json_store: JsonStore):
        card = json_store.add(task_code="R-001", task_name="提醒卡")
        assert card["card_ok"] is False
        assert card["reminder_confirmed"] is False
        assert card["reminder_type"] == ""

    def test_card_update_reminder_fields(self, json_store: JsonStore):
        card = json_store.add(task_code="R-002", task_name="卡")
        updated = json_store.update(card["id"], reminder_type="重点提醒", card_ok=True, reminder_confirmed=False)
        assert updated["reminder_type"] == "重点提醒"
        assert updated["card_ok"] is True
        assert updated["reminder_confirmed"] is False

    def test_card_add_with_reminder_type(self, json_store: JsonStore):
        card = json_store.add(task_code="R-003", task_name="卡", reminder_type="一般提醒")
        assert card["reminder_type"] == "一般提醒"

    def test_set_defaults_and_update(self, json_store: JsonStore):
        s = json_store.add_set(name="提醒组", description="", category="发动机")
        assert s["card_ok"] is False
        assert s["reminder_type"] == ""
        updated = json_store.update_set(s["id"], reminder_type="重点提醒", card_ok=True, reminder_confirmed=False)
        assert updated["reminder_type"] == "重点提醒"
        assert updated["card_ok"] is True


class TestSyncSetReminder:
    def test_sync_propagates_reminder_fields(self, json_store: JsonStore):
        card = json_store.add(task_code="S-001", task_name="卡")
        s = json_store.add_set(name="组A", description="", category="发动机",
                               reminder_type="重点提醒", card_ok=True, reminder_confirmed=False)
        json_store.update(card["id"], set_id=s["id"])
        json_store.sync_set_to_cards(s["id"])
        synced = json_store.get(card["id"])
        assert synced["reminder_type"] == "重点提醒"
        assert synced["card_ok"] is True
        assert synced["reminder_confirmed"] is False
        assert synced["category"] == "发动机"


class TestNextIdHeal:
    def test_next_id_lag_does_not_overwrite(self, tmp_path):
        """next_id 落后于现存实体时，新增不得覆盖现有实体（服务器数据实证：1032 vs 1036）"""
        db_path = str(tmp_path / "lag.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({
                "next_id": 1032,
                "cards": {str(i): {"id": i, "task_code": f"C-{i}"} for i in range(1028, 1033)},
                "card_sets": {str(i): {"id": i, "name": f"S-{i}"} for i in range(1033, 1037)},
                "aircraft": {},
            }, f)
        store = JsonStore(db_path)
        r = store.add("NEW-001", "新卡", "机体", "", "")
        assert r["id"] == 1037
        # 现有实体原样保留
        assert store.get(1032)["task_code"] == "C-1032"
        assert store.get_set(1036)["name"] == "S-1036"


class TestIndexHeal:
    def test_dirty_index_heals_on_read(self, tmp_path):
        """悬挂索引（指向 task_code 不匹配的卡）读取即自愈（服务器数据实证）"""
        db_path = str(tmp_path / "dirty.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({
                "next_id": 2,
                "cards": {"1": {"id": 1, "task_code": "REAL-CODE"}},
                "code_index": {"GHOST-CODE": 1, "REAL-CODE": 1},
            }, f)
        store = JsonStore(db_path)
        assert store.find_by_code("GHOST-CODE") is None
        assert store.find_by_code("REAL-CODE")["id"] == 1
        store.update(1, task_name="触发写入")  # 写后索引自愈持久化
        with open(str(tmp_path / "dirty_runtime.json"), encoding="utf-8") as f:
            assert "GHOST-CODE" not in json.load(f).get("code_index", {})

    def test_index_missing_rebuilt(self, tmp_path):
        db_path = str(tmp_path / "noidx.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({"cards": {"1": {"id": 1, "task_code": "C-001"}}}, f)
        store = JsonStore(db_path)
        assert store.find_by_code("C-001")["id"] == 1


class TestAtomicWriteFailure:
    def test_write_failure_keeps_target(self, json_store, monkeypatch):
        """os.replace 失败时目标文件必须原样保留且抛异常（而非被截断覆盖）"""
        import reqman.models.json_store as jsm

        json_store.add("SAFE-001", "卡", "发动机", "A", "")
        with open(json_store._path, encoding="utf-8") as f:
            good = json.load(f)

        def boom(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(jsm.os, "replace", boom)
        with pytest.raises(OSError):
            json_store.add("SAFE-002", "卡2", "发动机", "A", "")
        monkeypatch.undo()
        with open(json_store._path, encoding="utf-8") as f:
            after = json.load(f)
        assert after["cards"] == good["cards"]  # 好文件未被截断/覆盖


class TestWriteConsistency:
    def test_save_work_package_threaded_no_loss(self, tmp_path):
        """多线程并发保存工作包不得互相丢失（save_work_package 曾是唯一无锁的读改写）"""
        import threading

        store = JsonStore(str(tmp_path / "wp.json"))

        def save(i):
            store.save_work_package({"reg": f"B-{i:04d}", "description": "d", "date": "2026.08.28"})

        ts = [threading.Thread(target=save, args=(i,)) for i in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(store.get_work_packages()) == 10

    def test_update_duplicate_code_rejected(self, json_store):
        """编辑工卡号不得占用其他卡已有的工卡号（脏索引的产生源头）"""
        a = json_store.add("CODE-A", "卡A", "机体", "", "")
        b = json_store.add("CODE-B", "卡B", "机体", "", "")
        with pytest.raises(ValueError):
            json_store.update(b["id"], task_code="CODE-A")
        # 拒绝且无副作用
        assert json_store.get(b["id"])["task_code"] == "CODE-B"
        assert json_store.get(a["id"])["task_code"] == "CODE-A"
        assert json_store.find_by_code("CODE-A")["id"] == a["id"]


class TestCorruptRefuseWrite:
    def test_corrupt_runtime_refuses_write(self, json_store):
        """运行时文件损坏后拒绝一切写入，防止残缺库被合法化持久化"""
        json_store.add("CORR-001", "卡", "机体", "", "")
        with open(json_store._runtime_path, "w", encoding="utf-8") as f:
            f.write("{corrupted")
        with pytest.raises(RuntimeError):
            json_store.add("CORR-002", "卡2", "机体", "", "")
        # 核心文件未被"半张库"覆盖
        with open(json_store._path, encoding="utf-8") as f:
            core = json.load(f)
        assert "CORR-002" not in [c["task_code"] for c in core["cards"].values()]
        assert "CORR-001" in [c["task_code"] for c in core["cards"].values()]


class TestQuickFixes:
    def test_get_all_missing_key_safe(self, tmp_path):
        """数据缺 task_code 键时 get_all 不得 500（KeyError 防护）"""
        db_path = str(tmp_path / "missing.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({"cards": {"1": {"id": 1}}}, f)  # 缺 task_code
        store = JsonStore(db_path)
        cards = store.get_all()
        assert len(cards) == 1 and cards[0]["id"] == 1
        assert len(store.get_all(search="任意")) == 0

    def test_aircraft_reg_dup_and_required(self, json_store):
        """机号必填且不得重复（find_aircraft_by_reg 依赖唯一性）"""
        from reqman.services.card_service import CardService, ServiceError

        svc = CardService(json_store)
        svc.add_aircraft(reg="B-1111", model="A320")
        with pytest.raises(ServiceError):
            svc.add_aircraft(reg="B-1111", model="B737")  # 重复
        with pytest.raises(ServiceError):
            svc.add_aircraft(reg="   ", model="A320")  # 空
        ac = svc.get_aircraft(1)
        with pytest.raises(ServiceError):
            svc.update_aircraft(ac["id"], reg="")  # 编辑清空
        svc.add_aircraft(reg="B-2222", model="A320")
        with pytest.raises(ServiceError):
            svc.update_aircraft(ac["id"], reg="B-2222")  # 编辑撞已有机号
        assert svc.get_aircraft(ac["id"])["reg"] == "B-1111"


class TestLogAutoTrim:
    def test_add_log_auto_trims_to_500(self, json_store):
        """每次新增日志自动清理：仅保留最新500条（本地/服务器同一行为）"""
        db = json_store._read()
        for i in range(505):
            json_store._add_log(db, "add", "card", i, f"C-{i}", "", [])
        json_store._write(db)
        logs = json_store.get_logs(limit=1000)
        assert len(logs) == 500
        ids = {l["id"] for l in logs}
        assert 505 in ids  # 最新保留
        assert 1 not in ids and 5 not in ids  # 最旧丢弃


class TestAmroRuntime:
    """v3.5.0 T3：卡版本字段 + 同步状态键 + 版本日志筛选"""

    def test_card_write_date_backcompat(self, json_store):
        """write_date 字段 _norm 自动补默认，旧数据零迁移"""
        r = json_store.add("NEW-100", "卡", "机体", "", "")
        assert r["write_date"] == ""
        got = json_store.get(r["id"])
        assert got["write_date"] == ""

    def test_update_write_date_changes_logged(self, json_store):
        """update 支持 write_date 且产生版本日志所需的 changes 条目"""
        r = json_store.add("WD-1", "卡", "机体", "", "")
        json_store.update(r["id"], write_date="2026-08-01 09:00:00")
        logs = json_store.get_logs()
        assert any(c["field"] == "write_date" for l in logs for c in l["changes"])

    def test_version_logs_filters_card_logs(self, json_store):
        """版本日志=card_logs 中 changes 含 write_date 的条目（无新存储）"""
        r = json_store.add("C-1", "卡", "机体", "", "")
        json_store.update(r["id"], task_name="改名")          # 非版本日志
        json_store.update(r["id"], write_date="2026-08-01 09:00:00")  # 版本日志
        logs = json_store.get_version_logs()
        assert len(logs) == 1 and logs[0]["target_identifier"] == "C-1"
