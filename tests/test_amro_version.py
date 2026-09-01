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


    def test_dp_cards_skipped(self, json_store, fake_amro_cards, monkeypatch):
        """DP 开头工卡（DP 项目）不在 AMRO 清单体系内：全库检查跳过不比对、不报作废。"""
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        r = json_store.add("DP1000000739", "DP项目卡", "机体", "", "")
        rep = _run(amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards))
        assert all(c["task_code"] != "DP1000000739"
                   for c in rep["revised"] + rep["cancelled"])
        assert json_store.get(r["id"]) is not None


class TestVersionReportExcel:
    def test_dot_date(self):
        assert amro_sync._dot_date("20260901_143025") == "2026.09.01"
        assert amro_sync._dot_date("") == ""
        assert amro_sync._dot_date("bad") == ""

    def test_report_excel_reminder_template_layout(self):
        """改版清单以提醒单模板输出：单 sheet、标题带标识+日期、三专业列、蓝底改版/红底作废。"""
        buf = amro_sync.build_version_report_excel({
            "revised": [
                {"task_code": "C-1", "task_name": "卡一", "category": "电子",
                 "old_wd": "2026-07-01 09:00:00", "new_wd": "2026-08-01 09:00:00"},
                {"task_code": "C-2", "task_name": "卡二", "category": "发动机",
                 "old_wd": "", "new_wd": "2026-08-01 09:00:00"},
            ],
            "cancelled": [
                {"task_code": "C-3", "task_name": "卡三", "category": "机体"},
                {"task_code": "C-4", "task_name": "特检卡", "category": "特检"},
            ],
        }, title_label="B-1234 46A", finished_date="2026.09.01")
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        assert wb.sheetnames == ["改版清单"]
        ws = wb["改版清单"]
        assert ws["A1"].value == "工卡改版提醒单（B-1234 46A）2026.09.01"
        assert ws["A5"].value == "蓝色底色为改版工卡，红色底色为作废工卡"
        assert (ws["A6"].value, ws["B6"].value, ws["C6"].value) == ("电子", "发动机", "机体")
        a7 = ws["A7"]   # 电子列：改版卡一（旧→新）蓝底
        assert a7.value == "卡一（2026-07-01→2026-08-01）"
        assert a7.fill.start_color.rgb == "FFBDD7EE"
        assert ws["B7"].value == "卡二（2026-08-01）"   # 旧为空仅显新日期
        c7 = ws["C7"]   # 机体列：作废卡三红底
        assert c7.value == "卡三"
        assert c7.fill.start_color.rgb == "FFFFC7CE"
        assert ws["D6"].value is None and ws["D7"].value is None   # 特检不输出


class TestCheckCardsAgainstAmro:
    """包级版本检查（工作包行级查询）：条目含 task_name/category，无 new_by_category"""

    def test_dp_codes_excluded(self, json_store, monkeypatch):
        """DP 开头工卡不参与包级版本检查：不发查询、不误报作废。"""
        json_store.add("DP1000000739", "DP项目卡", "机体", "", "")
        json_store.add("EOJC-A320-57-2025-002-B", "旧卡", "机体", "EO", "")
        queried = []

        async def query(client, cookies, plugin, form, **kw):
            queried.append(form.get("jcno"))
            return {"code": 200, "data": {}}   # 查无 → 作废

        rep = _run(amro_sync.check_cards_against_amro(
            json_store, None, {}, ["DP1000000739", "EOJC-A320-57-2025-002-B"], query=query))
        assert queried == ["EOJC-A320-57-2025-002-B"]   # DP 不发任何查询
        assert [c["task_code"] for c in rep["cancelled"]] == ["EOJC-A320-57-2025-002-B"]
        assert all(c["task_code"] != "DP1000000739"
                   for c in rep["revised"] + rep["cancelled"])

    def test_revised_and_cancelled_with_fields(self, json_store, fake_amro_cards, monkeypatch):
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        json_store.add("EOJC-A320-57-2025-002-B", "旧卡", "机体", "EO", "")

        async def query(client, cookies, plugin, form, **kw):   # EO 卡逐条直查
            if form.get("jcno") == "EOJC-A320-99-2026-999-Z":
                return {"code": 200, "data": {"JC_NO": "EOJC-A320-99-2026-999-Z",
                                              "WRITE_DATE": "2026-07-20 08:00:00"}}
            return {"code": 200, "data": {}}   # 57-2025-002-B 查无 → 作废

        rep = _run(amro_sync.check_cards_against_amro(
            json_store, None, {},
            ["CSCA320-256652-01-1-X", "EOJC-A320-57-2025-002-B",
             "EOJC-A320-99-2026-999-Z"],   # 库内无此卡（AMRO 有）→ 跳过
            fetch=fake_amro_cards, query=query))
        assert "new_by_category" not in rep
        rev = rep["revised"][0]
        assert rev["task_code"] == "CSCA320-256652-01-1-X"
        assert rev["task_name"] == "检查救生衣" and rev["category"] == "电子"
        can = rep["cancelled"][0]
        assert can["task_code"] == "EOJC-A320-57-2025-002-B"
        assert can["task_name"] == "旧卡" and can["category"] == "机体"
        codes = {r["task_code"] for r in rep["revised"] + rep["cancelled"]}
        assert "EOJC-A320-99-2026-999-Z" not in codes


class TestVersionPullSplit:
    """v3.6.0 版本查询提速：SMJC/EOJC 机队筛选 + 例行卡包跳过 EOJC 深分页 + EO 逐卡直查"""

    def test_pull_card_versions_fleet_filter(self, monkeypatch):
        """SMJC/EOJC 表单均带 fleet=A320（2026-09-01 实测 SMJC 1319→745）。"""
        seen = {}

        async def fetch(client, cookies, plugin, base_form, **kw):
            seen[plugin] = dict(base_form)
            if plugin == "TD_JC_SMJC_LIST":
                return [_jcrow("CSCA320-256652-01-1-X", "2026-08-01 09:00:00")]
            return []

        _run(amro_sync._pull_card_versions(None, {}, fetch=fetch))
        assert seen["TD_JC_ALL_EOJC_LIST"]["fleet"] == "A320"
        assert seen["TD_JC_SMJC_LIST"]["fleet"] == "A320"

    def test_get_entity_by_jcno_returns_row_or_none(self, monkeypatch):
        """实体端点：data 单对象 → 行 dict；空 data → None。"""
        seen = {}

        async def query(client, cookies, plugin, form, **kw):
            seen[plugin] = dict(form)
            if form.get("jcno") == "HAS":
                return {"code": 200, "data": {"JC_NO": "HAS", "WRITE_DATE": "2026-08-01 09:00:00"}}
            return {"code": 200, "data": {}}

        row = _run(amro_sync._get_entity_by_jcno(None, {}, "HAS", query=query))
        assert row == {"JC_NO": "HAS", "WRITE_DATE": "2026-08-01 09:00:00"}
        assert seen == {"TD_JC_ALL_GET_ENTITY_BY_JCNO": {"jcno": "HAS"}}
        assert _run(amro_sync._get_entity_by_jcno(None, {}, "MISS", query=query)) is None

    def test_csca_only_package_skips_eojc(self, json_store, monkeypatch):
        """包内全为定检例行卡（CSCA 前缀）→ 只拉 SMJC，跳过 EOJC 深分页（秒级返回）。"""
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        called = []

        async def fetch(client, cookies, plugin, base_form, **kw):
            called.append(plugin)
            if plugin == "TD_JC_SMJC_LIST":
                return [_jcrow("CSCA320-256652-01-1-X", "2026-08-01 09:00:00")]
            return []

        rep = _run(amro_sync.check_cards_against_amro(
            json_store, None, {}, ["CSCA320-256652-01-1-X"], fetch=fetch))
        assert called == ["TD_JC_SMJC_LIST"]
        assert len(rep["revised"]) == 1

    def test_eo_package_uses_per_jcno_query(self, json_store, monkeypatch):
        """含 EO 卡 → SMJC 全量拉 + EO 逐个按卡号直查（不再全量拉 EOJC 深分页）。"""
        monkeypatch.setattr(amro_sync.amro.time, "monotonic", lambda: 1e9)
        monkeypatch.setattr(amro_sync.amro.time, "sleep", lambda s: None)
        json_store.add("EOJC-A320-31-2026-007-A", "改装卡", "电子", "EO", "")
        fetched, queried = [], []

        async def fetch(client, cookies, plugin, base_form, **kw):
            fetched.append((plugin, dict(base_form)))
            if plugin == "TD_JC_SMJC_LIST":
                return [_jcrow("CSCA320-256652-01-1-X", "2026-08-01 09:00:00")]
            return []

        async def query(client, cookies, plugin, form, **kw):
            queried.append((plugin, dict(form)))
            return {"code": 200, "data": {"JC_NO": "EOJC-A320-31-2026-007-A",
                                          "WRITE_DATE": "2026-07-15 14:00:00"}}

        rep = _run(amro_sync.check_cards_against_amro(
            json_store, None, {},
            ["CSCA320-256652-01-1-X", "EOJC-A320-31-2026-007-A"],
            fetch=fetch, query=query))
        assert [p for p, _ in fetched] == ["TD_JC_SMJC_LIST"]          # 无 EOJC 全量拉取
        assert queried == [("TD_JC_ALL_GET_ENTITY_BY_JCNO",
                            {"jcno": "EOJC-A320-31-2026-007-A"})]      # EO 逐卡直查
        assert [r["task_code"] for r in rep["revised"]] == ["EOJC-A320-31-2026-007-A"]
