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


class TestVersionReportExcel:
    def test_report_excel_has_two_sheets(self):
        buf = amro_sync.build_version_report_excel({
            "revised": [{"task_code": "C-1", "old_wd": "", "new_wd": "2026-08-01"}],
            "cancelled": [{"task_code": "C-2"}],
        })
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        assert wb.sheetnames == ["改版工卡", "作废工卡"]


class TestApplyReminderVersionSection:
    def test_revised_and_new_cards_blue_fill(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        report = {"revised": [{"task_code": "CSCA320-256652-01-1-X", "old_wd": "",
                               "new_wd": "2026-08-01 09:00:00"}],
                  "cancelled": [{"task_code": "EOJC-A320-57-2025-002-B"}],
                  "new_by_category": {"电子": [{"task_code": "EOJC-A320-31-2026-007-A",
                                               "task_name": "实时数据改装"}]}}
        amro_sync.apply_reminder_version_section(ws, report)

        def blue_rows():
            out = set()
            for row in ws.iter_rows():
                for c in row:
                    fill = getattr(c, "fill", None)
                    rgb = getattr(getattr(fill, "fgColor", None), "rgb", None)
                    if rgb in ("FF0000FF", "0000FF"):
                        out.add(c.row)
            return out

        codes_by_row = {r: ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)}
        assert "CSCA320-256652-01-1-X" in {codes_by_row[r] for r in blue_rows()}   # 改版蓝底
        assert "EOJC-A320-31-2026-007-A" in {codes_by_row[r] for r in blue_rows()}  # 新工卡蓝底
        cancelled_rows = [r for r, v in codes_by_row.items()
                          if "EOJC-A320-57-2025-002-B" in str(v) and "已作废" in str(v)]
        assert cancelled_rows, "作废工卡应列出（行首已作废标注）"
