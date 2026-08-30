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
