"""AMRO 三域同步编排单测（全 mock 零外呼）— T4 飞机域"""
import asyncio

import pytest

from reqman.services import amro_sync


def _run(coro):
    return asyncio.run(coro)


def _acrow(acno, conf="A320-232", mp="A320", vs="1", eng="V2500-A5",
           fsn="033", msn="6421", apu="131-9(A)"):
    return {"ACNO": acno, "CONF_ACTYPE": conf, "MP_ACTYPE": mp, "VALID_STATUS": vs,
            "ENG_TYPE": eng, "FSN": fsn, "MSN": msn, "APU_TYPE": apu}


@pytest.fixture
def fake_amro_acreg():
    async def fetch(client, cookies, plugin, base_form, **kw):
        assert plugin == "DA_ACREG_LIST"
        return [_acrow("B-1662"), _acrow("B-1663", conf="A320-271N", msn="8888", eng="PW1127G")]
    return fetch


class TestSyncAircraft:
    def test_upsert_and_remove(self, json_store, fake_amro_acreg):
        json_store.add_aircraft("B-1662", "旧机型", "", "", "", "")    # 在册 → 覆盖
        json_store.add_aircraft("B-9999", "A320-232", "", "", "", "")  # 不在在册 → 清理
        rep = _run(amro_sync.sync_aircraft(json_store, None, {}, fetch=fake_amro_acreg))
        ac = next(a for a in json_store.get_all_aircraft() if a["reg"] == "B-1662")
        assert ac["model"] == "A320-232" and ac["apu"] == "131-9(A)"
        assert "B-9999" in rep["removed"]
        assert all(a["reg"] != "B-9999" for a in json_store.get_all_aircraft())
        # 清理必须留日志（更新/新增同理走 store 方法留痕）
        assert any(l["operation"] == "delete" for l in json_store._read()["card_logs"])

    def test_bprefix_match_no_dup(self, json_store, fake_amro_acreg):
        """三段匹配：库内 "1662"（无B-）与 AMRO "B-1662" 视为同一架，不产生重复"""
        json_store.add_aircraft("1662", "A320-232", "", "", "", "")
        rep = _run(amro_sync.sync_aircraft(json_store, None, {}, fetch=fake_amro_acreg))
        assert rep["added"] == rep["total_amro"] - 1
        assert len([a for a in json_store.get_all_aircraft() if "1662" in a["reg"]]) == 1

    def test_filter_fleet_and_status(self, json_store):
        """在册判定：MP_ACTYPE==A320 且 VALID_STATUS=='1'，其余不进同步集合"""
        async def fetch(client, cookies, plugin, base_form, **kw):
            return [_acrow("B-1662"), _acrow("B-3300", mp="A330"), _acrow("B-0000", vs="0")]
        rep = _run(amro_sync.sync_aircraft(json_store, None, {}, fetch=fetch))
        assert rep["total_amro"] == 1
        assert [a["reg"] for a in json_store.get_all_aircraft()] == ["B-1662"]


@pytest.fixture
def routine_row():
    return {"REVNR": "66A", "ACNO": "B-1662", "ACTYPE": "A320-232", "ENGTYPE": "V2500",
            "REVTITLE": "A320 4C检", "CHKTP": "4C", "PLANSTD": "2026-09-01",
            "JCNO": "CSCA320-256652-01-1-X", "TASK": "RST", "ZY": "电子",
            "JCTITLE": "检查救生衣", "PPCBZSM": ""}


class TestPackageItems:
    """T5 工作包直读：AMRO 清单行 → 与 xlsx 解析同构的 item"""

    def test_mapping_and_prefix(self, routine_row):
        routine_row["ZY"] = "机身"
        out = amro_sync.package_items([routine_row], [], header_row=routine_row)
        it = out["all_items"][0]
        assert (it["task_code"], it["task_type"], it["category"], it["source"]) == (
            routine_row["JCNO"], routine_row["TASK"], "机体", "例行")
        assert out["aircraft_info"]["package"] == "66A"
        assert out["aircraft_info"]["reg"] == "B-1662"
        assert out["aircraft_info"]["date"] == "2026.09.01"   # 与解析器同语义（- → .）

    def test_squadron_and_plan_hours(self):
        row = {"REVNR": "66A", "PLANSTD": "2026-09-01 08:00:00",
               "ZRFD": "云南定检中队一分队(主),云南定检中队二分队（主）,云南定检中队三分队",
               "LIMH": "170"}
        info = amro_sync.package_items([], [], header_row=row)["aircraft_info"]
        assert info["squadron"] == "云南定检中队一分队"      # 首个带“(主)”项，剥后缀
        assert info["plan_hours"] == "170"

    def test_squadron_no_mark_uses_first(self):
        row = {"ZRFD": "云南定检中队一分队,云南定检中队二分队", "LIMH": ""}
        info = amro_sync.package_items([], [], header_row=row)["aircraft_info"]
        assert info["squadron"] == "云南定检中队一分队"      # 无主标记取首项
        assert info["plan_hours"] == ""

    def test_cancelled_by_remark(self, routine_row):
        routine_row["PPCBZSM"] = "该卡已撤销|"
        it = amro_sync.package_items([routine_row], [])["all_items"][0]
        assert it["cancelled"] is True and "撤销" in it["remark"]

    def test_qt_rows_other_source_and_dedup(self, routine_row):
        other = dict(routine_row, JCNO="EOJC-A320-31-2026-007-A")
        out = amro_sync.package_items([routine_row, dict(routine_row)], [other])
        assert [i["source"] for i in out["all_items"]] == ["例行", "其他"]  # 重复行去重+来源标注

    def test_empty_rows(self):
        out = amro_sync.package_items([], [])
        assert out["all_items"] == [] and out["aircraft_info"]["package"] == ""


class TestGlobalQueryMutex:
    """v3.6.0 全局查询互斥：一次只跑一个 AMRO 查询，不排队"""

    def test_begin_end_roundtrip(self):
        token = amro_sync.try_begin_query("查询飞机数据")
        assert token is not None
        assert amro_sync.query_busy_message() is not None
        assert "查询飞机数据" in amro_sync.query_busy_message()
        amro_sync.end_query(token)
        assert amro_sync.query_busy_message() is None

    def test_second_query_rejected_while_busy(self):
        token = amro_sync.try_begin_query("查询飞机数据")
        assert token is not None
        try:
            assert amro_sync.try_begin_query("查询库存") is None
            msg = amro_sync.query_busy_message()
            assert "查询飞机数据" in msg and "请等待完成后再查询" in msg
        finally:
            amro_sync.end_query(token)

    def test_query_slot_context_raises_busy(self):
        # 保持嵌套：外层占用槽、内层冲突抛 QueryBusyError（不可合并 with）
        with amro_sync.query_slot("查询工作包"), pytest.raises(amro_sync.QueryBusyError):  # noqa: SIM117
            with amro_sync.query_slot("查询库存"):
                pass
        assert amro_sync.query_busy_message() is None

    def test_run_query_releases_slot_after_done(self):
        release = amro_sync.run_query("aircraft", "查询飞机数据", lambda: {"added": 1})
        assert release is True
        # 等待 daemon 线程跑完并释放全局槽
        import time as _time
        deadline = _time.time() + 3
        while amro_sync.query_busy_message() is not None and _time.time() < deadline:
            _time.sleep(0.02)
        assert amro_sync.query_busy_message() is None
        assert amro_sync.get_query_status("aircraft")["status"] == "done"

    def test_run_query_false_when_busy(self):
        token = amro_sync.try_begin_query("查询飞机数据")
        assert token is not None
        try:
            assert amro_sync.run_query("busy_reject", "全量查询工卡版本", dict) is False
            assert amro_sync.get_query_status("busy_reject") == {}  # 未启动不落状态
        finally:
            amro_sync.end_query(token)


class TestLastQueryResult:
    """v3.6.0 查询结果简述持久化：output/last_query_<key>.json（重启保留）"""

    def test_save_and_get_roundtrip(self, tmp_path):
        amro_sync.save_last_query_result("aircraft", "查询飞机数据",
                                         "新增 1 架，更新 2 架，清理 0 架",
                                         output_dir=tmp_path)
        meta = amro_sync.get_last_query_result("aircraft", output_dir=tmp_path)
        assert meta["label"] == "查询飞机数据"
        assert meta["summary"] == "新增 1 架，更新 2 架，清理 0 架"
        assert meta["finished_at"]
        assert meta["download_url"] == ""

    def test_save_with_download_url(self, tmp_path):
        amro_sync.save_last_query_result(
            "full_version", "全量查询工卡版本", "改版 2 张，作废 0 张",
            download_url="/card/amro-version-report", output_dir=tmp_path)
        meta = amro_sync.get_last_query_result("full_version", output_dir=tmp_path)
        assert meta["download_url"] == "/card/amro-version-report"

    def test_get_missing_returns_empty(self, tmp_path):
        assert amro_sync.get_last_query_result("nope", output_dir=tmp_path) == {}

    def test_overwrite_keeps_latest(self, tmp_path):
        amro_sync.save_last_query_result("package", "查询工作包", "获取到 1 个任务包",
                                         output_dir=tmp_path)
        amro_sync.save_last_query_result("package", "查询工作包", "获取到 5 个任务包",
                                         output_dir=tmp_path)
        meta = amro_sync.get_last_query_result("package", output_dir=tmp_path)
        assert meta["summary"] == "获取到 5 个任务包"   # 只留最近一份


class TestPackageDisplayLabel:
    """工作包展示标识（机号+描述，aircraft_info 优先、顶层兜底）。"""

    def test_prefers_aircraft_info_then_top_level(self):
        assert amro_sync.package_display_label(
            {"aircraft_info": {"reg": "B-1234", "description": "46A"},
             "reg": "X", "description": "Y"}) == "B-1234 46A"
        assert amro_sync.package_display_label(
            {"reg": "B-1234", "description": "46A"}) == "B-1234 46A"

    def test_mixed_and_empty(self):
        assert amro_sync.package_display_label(
            {"aircraft_info": {"reg": "B-1"}, "description": "D"}) == "B-1 D"
        assert amro_sync.package_display_label({"reg": "", "description": ""}) == ""
        assert amro_sync.package_display_label({}) == ""
