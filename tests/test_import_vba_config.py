"""VBA 配置迁移测试"""
import openpyxl

from reqman.models.json_store import JsonStore
from scripts.lib.import_vba_config import import_vba_config


def _build_config(tmp_path):
    """构建 VBA 配置样例 xlsx：飞机信息/电子提醒/发动机提醒/机体提醒/重点工卡"""
    path = tmp_path / "vba_config.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "飞机信息"
    ws.append(["飞机号", "构型", "机队序列号", "制造商序列号", "APU型号"])
    ws.append(["B-1661", "A320-232/V2500-A5", "33", "6421", "131-9(A)"])
    ws.append(["B-1662", "A320-232/V2500-A5", "34", "6486", "131-9(A)"])

    ws2 = wb.create_sheet("电子提醒")
    ws2.append(["工卡号", "工卡名称", "专业", "类型"])
    ws2.append(["E-001", "电子卡一", "电子", ""])

    ws3 = wb.create_sheet("发动机提醒")
    ws3.append(["工卡号", "工卡名称", "专业", "类型"])
    ws3.append(["F-001", "发动机卡", "发动机", ""])

    ws4 = wb.create_sheet("机体提醒")
    ws4.append(["工卡号", "工卡名称", "专业", "类型"])
    ws4.append(["J-001", "机体卡", "机体", ""])

    ws5 = wb.create_sheet("重点工卡")
    ws5.append(["工卡号"])
    ws5.append(["F-001"])   # 与发动机表同卡号 → 覆盖为重点

    wb.save(path)
    return path


def _prepare_store(tmp_db_path):
    store = JsonStore(tmp_db_path)
    store.add(task_code="E-001", task_name="库电子卡", category="电子")
    store.add(task_code="F-001", task_name="库发动机卡", category="发动机")
    return store


class TestImportVbaConfig:
    def test_import_basic(self, tmp_path, tmp_db_path):
        store = _prepare_store(tmp_db_path)
        result = import_vba_config(str(_build_config(tmp_path)), store)
        assert result.general == 2          # E-001 一般、J-001（库无 J-001 → 弃用）
        assert result.key == 1              # F-001 重点
        assert any("J-001" in d for d in result.discarded)  # 库中不存在 → 弃用
        card_e = store.find_by_code("E-001")
        assert card_e["reminder_type"] == "一般提醒"
        assert card_e["card_ok"] is False    # 初始未确认
        card_f = store.find_by_code("F-001")
        assert card_f["reminder_type"] == "重点提醒"   # 覆盖一般
        assert result.aircraft_added == 2
        ac = store.find_aircraft_by_reg("B-1661")
        assert ac["model"] == "A320-232/V2500-A5"

    def test_import_aircraft_no_duplicate(self, tmp_path, tmp_db_path):
        store = _prepare_store(tmp_db_path)
        store.add_aircraft(reg="B-1661", model="OLD")
        result = import_vba_config(str(_build_config(tmp_path)), store)
        assert result.aircraft_added == 1
        assert result.aircraft_updated == 1   # B-1661 更新而非重复
        ac = store.find_aircraft_by_reg("B-1661")
        assert ac["model"] == "A320-232/V2500-A5"