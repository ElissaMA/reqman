"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_in_thread 包成 daemon 线程并写 amro_sync_meta 状态位（running/done/error）。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from ..config import AMRO_AC_FLEET
from .connectors import amro

logger = logging.getLogger(__name__)

BJ = ZoneInfo("Asia/Shanghai")


def _now() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")


def _norm_reg(value: str) -> str:
    """注册号对比键：去 B- 前缀、大写、去空白（三段匹配的统一形态）。"""
    s = (value or "").strip().upper()
    s = s.removeprefix("B-")
    return s


def run_in_thread(app, domain: str, job) -> None:
    """daemon 线程执行 job，写 amro_sync_meta 状态位：running → done(含 report) / error。"""
    store = app.extensions["store"]

    def runner():
        store.set_amro_sync_meta(domain, {"status": "running", "started_at": _now()})
        try:
            report = job()
            store.set_amro_sync_meta(domain, {"status": "done", "finished_at": _now(), "report": report})
        except Exception as exc:
            logger.exception("AMRO 同步任务失败: %s", domain)
            store.set_amro_sync_meta(domain, {"status": "error", "finished_at": _now(), "error": str(exc)})

    threading.Thread(target=runner, daemon=True, name=f"amro-{domain}").start()


# ---------- 飞机域 ----------

def _aircraft_fields(row: dict) -> dict:
    """AMRO 行 → 本地六字段映射（APU_TYPE→apu，spec §6.3）。"""
    return {
        "model": str(row.get("CONF_ACTYPE", "")).strip(),
        "engine": str(row.get("ENG_TYPE", "")).strip(),
        "fsn": str(row.get("FSN", "")).strip(),
        "msn": str(row.get("MSN", "")).strip(),
        "apu": str(row.get("APU_TYPE", "")).strip(),
    }


async def sync_aircraft(store, client, cookies, *, fetch=None) -> dict:
    """拉 DA_ACREG_LIST → 在册过滤 → 六字段覆盖/新增 → 在册外清理。

    返回报告 {added, updated, removed:[reg...], total_amro}。
    # ponytail: 逐架走 store 方法（每次全量写盘，134 架 ~15s）；批量合并写待实测慢了再说
    """
    fetch = fetch or amro.fetch_all_pages
    rows = await fetch(client, cookies, "DA_ACREG_LIST", {"rows": 300})
    # 在册判定（决策#3）：MP_ACTYPE == AMRO_AC_FLEET 且 VALID_STATUS == '1'
    fleet = [r for r in rows
             if str(r.get("MP_ACTYPE", "")).strip() == AMRO_AC_FLEET
             and str(r.get("VALID_STATUS", "")).strip() == "1"]
    amro_by_key = {_norm_reg(r.get("ACNO", "")): r for r in fleet}
    amro_by_key.pop("", None)

    existing_by_key = {_norm_reg(a.get("reg", "")): a for a in store.get_all_aircraft()}

    added = updated = 0
    for key, row in amro_by_key.items():
        reg = f"B-{key}"
        fields = _aircraft_fields(row)
        old = existing_by_key.get(key)
        if old is None:
            store.add_aircraft(reg=reg, model=fields["model"], engine=fields["engine"],
                               fsn=fields["fsn"], msn=fields["msn"], apu=fields["apu"])
            added += 1
        elif any(old.get(f) != v for f, v in fields.items()) or old.get("reg") != reg:
            store.update_aircraft(old["id"], reg=reg, **fields)
            updated += 1

    removed = []
    for key, old in existing_by_key.items():
        if key not in amro_by_key:
            store.delete_aircraft(old["id"])
            removed.append(old.get("reg", ""))

    return {"added": added, "updated": updated, "removed": removed,
            "total_amro": len(amro_by_key)}


def start_aircraft_sync(app) -> bool:
    """启动飞机同步后台任务。返回 False = 同域任务已在跑（S1 防重复）。"""
    store = app.extensions["store"]
    if store.get_amro_sync_meta().get("aircraft", {}).get("status") == "running":
        return False
    session_store = app.extensions["inventory_service"].session_store

    def job():
        cookies = (session_store.load() or {}).get("cookies", {})

        async def _inner():
            async with httpx.AsyncClient(verify=True, trust_env=False) as client:
                return await sync_aircraft(store, client, cookies)

        return asyncio.run(_inner())

    run_in_thread(app, "aircraft", job)
    return True
