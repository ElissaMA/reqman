"""T6/T7 工卡版本域：全库检查、改版清单 Excel、提醒单附加区块（全 mock）"""
import asyncio
import io

import openpyxl
import pytest

from reqman.services import amro_sync


def _run(coro):
    return asyncio.run(coro)


def _jcrow(jcno, wd, task="RST", zy="电子", title="检查救生衣"):
    """TD_JC_*_LIST 行（WRITE_DATE 为版本主轴，两清单零缺失）"""
    return {"JC_NO": jcno, "WRITE_DATE": wd, "TASK": task, "ZY": zy, "JCTITLE": title}


@pytest.fixture
def fake_amro_cards():
    """SMJC：库内例行卡（含改版 1 张）；EOJC：库内 EO 卡 + 非库内卡"""
    async def fetch(client, cookies, plugin, base_form, **kw):
        if plugin == "TD_JC_SMJC_LIST":
            return [_jcrow("CSCA320-256652-01-1-X", "2026-08-01 09:00:00")]
        return [_jcrow("EOJC-A320-31-2026-007-A", "2026-07-15 14:00:00", task="EO"),
                _jcrow("EOJC-A320-99-2026-999-Z", "2026-07-20 08:00:00", task="EO")]
    return fetch


class TestFullVersionCheck:
    def test_revised_updates_card_and_logs(self, json_store, fake_amro_cards, monkeypatch):
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        r = json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        rep = _run(amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards))
        card = json_store.get(r["id"])
        assert card["write_date"] == "2026-08-01 09:00:00"
        assert rep["revised"][0]["old_wd"] == "" and rep["revised"][0]["new_wd"] == "2026-08-01 09:00:00"
        assert any(c["field"] == "write_date" for l in json_store._read()["card_logs"]
                   for c in l["changes"])

    def test_cancelled_detected_not_deleted(self, json_store, fake_amro_cards, monkeypatch):
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        r = json_store.add("EOJC-A320-57-2025-002-B", "卡", "机体", "", "")
        rep = _run(amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards))
        assert "EOJC-A320-57-2025-002-B" in [c["task_code"] for c in rep["cancelled"]]
        assert json_store.get(r["id"]) is not None   # 标记不删除（决策#8）

    def test_unchanged_card_not_relogged(self, json_store, fake_amro_cards, monkeypatch):
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        r = json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        json_store.update(r["id"], write_date="2026-08-01 09:00:00")   # 已是最新
        logs_before = len(json_store.get_version_logs())
        rep = _run(amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards))
        assert rep["revised"] == []
        assert len(json_store.get_version_logs()) == logs_before   # 不重复记版本日志

    def test_same_date_different_time_not_relogged(self, json_store, fake_amro_cards, monkeypatch):
        """日期部分比对：界面 date 只存 YYYY-MM-DD，AMRO 同日不同时间不再误报版本变动。"""
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        r = json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        json_store.update(r["id"], write_date="2026-08-01")   # 手动录入仅日期
        logs_before = len(json_store.get_version_logs())
        rep = _run(amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards))
        assert rep["revised"] == []
        assert len(json_store.get_version_logs()) == logs_before

        async def fetch_revised(client, cookies, plugin, base_form, **kw):  # 真正跨日期改版
            if plugin == "TD_JC_SMJC_LIST":
                return [_jcrow("CSCA320-256652-01-1-X", "2026-08-05 09:00:00")]
            return []
        rep2 = _run(amro_sync.full_version_check(json_store, None, {}, fetch=fetch_revised))
        assert len(rep2["revised"]) == 1
        assert json_store.get(r["id"])["write_date"] == "2026-08-05 09:00:00"


class TestVersionReportExcel:
    def test_report_excel_grouped_by_category(self):
        buf = amro_sync.build_version_report_excel({
            "revised": [
                {"task_code": "C-1", "task_name": "卡一", "category": "电子",
                 "old_wd": "2026-07-01 09:00:00", "new_wd": "2026-08-01 09:00:00"},
                {"task_code": "C-2", "task_name": "卡二", "category": "发动机",
                 "old_wd": "", "new_wd": "2026-08-01 09:00:00"},
            ],
            "cancelled": [
                {"task_code": "C-3", "task_name": "卡三", "category": "机体"},
            ],
        })
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        assert wb.sheetnames == ["改版工卡", "作废工卡"]
        ws = wb["改版工卡"]
        assert ws["A1"].value == "工卡号" and ws["C1"].value == "编写日期"  # 卡号|卡名|日期
        rows = [[ws.cell(row=r, column=c).value for c in range(1, 4)]
                for r in range(1, ws.max_row + 1)]
        assert ["【发动机】", None, None] in rows          # 分专业分节（发动机优先）
        assert ["C-1", "卡一", "2026-07-01→2026-08-01"] in rows  # 旧→新
        assert ["C-2", "卡二", "2026-08-01"] in rows              # 旧为空仅显新日期
        ws2 = wb["作废工卡"]
        assert ws2["A1"].value == "工卡号" and ws2.max_column == 2  # 无日期列
        rows2 = [[ws2.cell(row=r, column=c).value for c in range(1, 3)]
                 for r in range(1, ws2.max_row + 1)]
        assert ["【机体】", None] in rows2 and ["C-3", "卡三"] in rows2


class TestCheckCardsAgainstAmro:
    """包级版本检查（工作包行级查询）：条目含 task_name/category，无 new_by_category"""

    def test_revised_and_cancelled_with_fields(self, json_store, fake_amro_cards, monkeypatch):
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        json_store.add("EOJC-A320-57-2025-002-B", "旧卡", "机体", "EO", "")
        rep = _run(amro_sync.check_cards_against_amro(
            json_store, None, {},
            ["CSCA320-256652-01-1-X", "EOJC-A320-57-2025-002-B",
             "EOJC-A320-99-2026-999-Z"],   # 库内无此卡（AMRO 有）→ 跳过
            fetch=fake_amro_cards))
        assert "new_by_category" not in rep
        rev = rep["revised"][0]
        assert rev["task_code"] == "CSCA320-256652-01-1-X"
        assert rev["task_name"] == "检查救生衣" and rev["category"] == "电子"
        can = rep["cancelled"][0]
        assert can["task_code"] == "EOJC-A320-57-2025-002-B"
        assert can["task_name"] == "旧卡" and can["category"] == "机体"
        codes = {r["task_code"] for r in rep["revised"] + rep["cancelled"]}
        assert "EOJC-A320-99-2026-999-Z" not in codes
