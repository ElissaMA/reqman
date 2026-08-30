"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_in_thread 包成 daemon 线程并写 amro_sync_meta 状态位（running/done/error）。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
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


# ---------- AMRO 会话前置检查 ----------

def require_amro_session() -> bool:
    """AMRO 功能前置检查（spec §3.2）：真实探活一次，失效由路由层 401+P8 阻断。"""
    from flask import current_app
    svc = current_app.extensions["inventory_service"]
    return svc.check_login()


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


# ---------- 工作包域 ----------

def _package_header(rows: list[dict]) -> dict:
    """从清单行取包头（REVNR/ACNO/ACTYPE/ENGTYPE/REVTITLE/CHKTP/PLANSTD ↔ xlsx Row2）。"""
    first = rows[0] if rows else {}
    raw_date = str(first.get("PLANSTD", "")).strip()
    return {
        "package": str(first.get("REVNR", "")).strip(),
        "reg": str(first.get("ACNO", "")).strip(),
        "type": str(first.get("ACTYPE", "")).strip(),
        "description": str(first.get("REVTITLE", "")).strip(),
        "level": str(first.get("CHKTP", "")).strip(),
        "date": raw_date.split()[0].replace("-", ".") if raw_date else "",  # 与解析器同语义
        "engine": str(first.get("ENGTYPE", "")).strip(),
    }


def _item_from_row(row: dict, source: str) -> dict:
    """AMRO 清单行 → item（JCNO/TASK/ZY/JCTITLE/PPCBZSM，机身→机体，撤销标记）。"""
    category = str(row.get("ZY", "")).strip()
    if category == "机身":
        category = "机体"
    remark = str(row.get("PPCBZSM", "")).strip()
    return {
        "task_code": str(row.get("JCNO", "")).strip(),
        "task_name": str(row.get("JCTITLE", "")).strip(),
        "category": category,
        "task_type": str(row.get("TASK", "")).strip(),
        "remark": remark,
        "source": source,
        "cancelled": "撤销" in remark,
    }


def package_items(rows_routine: list[dict], rows_other: list[dict]) -> dict:
    """AMRO 两清单行 → 与 xlsx 解析同构的 {all_items, aircraft_info}。

    例行来源 BM_TSK_002_LIST、其他来源 BM_TSK_002_LIST_QT（EO/NRC/LS）；
    按 task_code 去重（保留首现），与解析器一致。
    """
    all_items = [_item_from_row(r, "例行") for r in rows_routine]
    all_items += [_item_from_row(r, "其他") for r in rows_other]
    all_items = [it for it in all_items if it["task_code"]]
    seen, uniq = set(), []
    for it in all_items:
        if it["task_code"] in seen:
            continue
        seen.add(it["task_code"])
        uniq.append(it)
    return {"all_items": uniq, "aircraft_info": _package_header(rows_routine or rows_other)}


def persist_amro_package(store, service, package_data: dict) -> dict:
    """AMRO 直读入库：立即匹配（供 S3 计数）+ 保存。返回摘要 {package_id, routine, other, new_cards}。"""
    from .work_package_matcher import match_work_package_items

    all_items = package_data.get("all_items", [])
    matched, new_cards, cancelled = match_work_package_items(all_items, store, service)
    package_data.update({
        "matched": matched, "new_cards": new_cards, "cancelled": cancelled,
        "is_matched": True, "generated_at": _now(),
        "routine_count": sum(1 for i in all_items if i.get("source") == "例行"),
        "other_count": sum(1 for i in all_items if i.get("source") == "其他"),
    })
    store.save_work_package(package_data)
    return {"package_id": package_data.get("package_id"),
            "routine": package_data["routine_count"], "other": package_data["other_count"],
            "new_cards": len(new_cards)}


async def import_amro_package(store, client, cookies, revnr, service=None, *, fetch=None) -> dict:
    """拉 BM_TSK_002_LIST + BM_TSK_002_LIST_QT → package_items → 入库 → 摘要。"""
    fetch = fetch or amro.fetch_all_pages
    base = {"revnr": str(revnr), "rows": 50}
    rows_routine = await fetch(client, cookies, "BM_TSK_002_LIST", dict(base), timeout=60)
    rows_other = await fetch(client, cookies, "BM_TSK_002_LIST_QT", dict(base), timeout=60)
    out = package_items(rows_routine, rows_other)
    info = out["aircraft_info"]
    package_data = {
        "reg": info.get("reg", ""),
        "description": info.get("description", ""),
        "date": info.get("date", "") or datetime.now(BJ).strftime("%Y.%m.%d"),
        "aircraft_info": info,
        "all_items": out["all_items"],
        "source": "AMRO",
    }
    return persist_amro_package(store, service, package_data)


async def list_amro_packages(client, cookies, *, base=None, days=7) -> list[dict]:
    """BM_TSK_LIST 任务接收包列表（total 恒 0 单页返回；日期窗今±days）。"""
    from ..config import AMRO_BASE_DEFAULT
    base = base or AMRO_BASE_DEFAULT
    today = datetime.now(BJ).date()
    form = {
        "gjzStr": "", "initBase": "", "baseCode1": "", "baseCode": base,
        "chktp": "",
        "planstdstr": (today - timedelta(days=days)).isoformat(),
        "planstdEnd": (today + timedelta(days=days)).isoformat(),
        "revst": "WJS|ZB|YZB|KG", "xfdw": "", "actype": "", "acno": "",
        "gjz": "", "iftj": "", "ifgzrz": "", "page": 1, "rows": 50,
    }
    body = await amro.query_plugin(client, cookies, "BM_TSK_LIST", form)
    return body.get("data") or []
