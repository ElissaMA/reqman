"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_query 包成 daemon 线程并写 QUERY_STATUS 内存态（running/done/error）；
全局查询互斥（try_begin_query）保证一次只跑一个 AMRO 查询，不排队。
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
from contextlib import contextmanager
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


# ---------- 全局查询互斥（v3.6.0：一次只跑一个 AMRO 查询，不排队） ----------

_query_lock = threading.Lock()
_running_query: dict | None = None  # {label, started_at}


def try_begin_query(label: str) -> bool:
    """尝试占用全局查询槽。成功返回 True；已有查询在跑返回 False（不排队）。"""
    global _running_query
    got = _query_lock.acquire(blocking=False)
    if got:
        _running_query = {"label": label, "started_at": _now()}
    return got


def end_query() -> None:
    """释放全局查询槽。"""
    global _running_query
    _running_query = None
    if _query_lock.locked():
        _query_lock.release()


def query_busy_message() -> str | None:
    """有查询在跑时返回统一提示文案；空闲返回 None。"""
    if _running_query:
        return (f"已有查询任务进行中：{_running_query['label']}"
                f"（{_running_query['started_at']}），请等待完成后再查询")
    return None


@contextmanager
def query_slot(label: str):
    """同步请求的查询槽上下文：进入时占用，退出时释放。"""
    if not try_begin_query(label):
        raise QueryBusyError(query_busy_message() or "已有查询任务进行中")
    try:
        yield
    finally:
        end_query()


class QueryBusyError(RuntimeError):
    """全局查询互斥冲突（已有查询在跑）。"""


# 内存任务状态注册表（v3.6.0：统一承载各查询任务状态；服务重启即清空）
QUERY_STATUS: dict[str, dict] = {}


def run_query(key: str, label: str, job) -> bool:
    """daemon 线程执行 job（占全局查询槽全程），QUERY_STATUS：running → done/error。

    返回 False = 已有查询在跑（未启动）。
    """
    if not try_begin_query(label):
        return False

    def runner():
        try:
            summary = job()
            QUERY_STATUS[key] = {"status": "done", "label": label,
                                 "finished_at": _now(), "summary": summary}
        except Exception as exc:
            logger.exception("AMRO 查询任务失败: %s", label)
            QUERY_STATUS[key] = {"status": "error", "label": label,
                                 "finished_at": _now(), "error": str(exc)}
        finally:
            end_query()

    QUERY_STATUS[key] = {"status": "running", "label": label, "started_at": _now()}
    threading.Thread(target=runner, daemon=True, name=f"amro-{key}").start()
    return True


def get_query_status(key: str) -> dict:
    """读取某查询任务的内存状态（无记录返回空 dict）。"""
    return QUERY_STATUS.get(key, {})


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


def start_aircraft_sync(store, session_store) -> bool:
    """启动飞机同步后台任务。返回 False = 已有查询在跑（全局互斥，不排队）。"""
    def job():
        cookies = (session_store.load() or {}).get("cookies", {})

        async def _inner():
            async with httpx.AsyncClient(verify=True, trust_env=False) as client:
                rep = await sync_aircraft(store, client, cookies)
            return {"added": rep["added"], "updated": rep["updated"],
                    "removed": len(rep["removed"]), "total_amro": rep["total_amro"]}

        return asyncio.run(_inner())

    return run_query("aircraft", "查询飞机数据", job)


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


# ---------- 工卡版本域 ----------

async def _pull_card_versions(client, cookies, *, fetch=None) -> dict[str, dict]:
    """拉 SMJC + EOJC 两清单（JC_STATUS=Y & ISSUED 由查询参数保证）→ {task_code: row}。

    WRITE_DATE 两清单零缺失（amro-research 实测）；EOJC 深分页 38~105s/页 → timeout=150。
    """
    fetch = fetch or amro.fetch_all_pages
    base = {"status": "ISSUED", "jcStatus": "Y", "rows": 500}
    smjc = await fetch(client, cookies, "TD_JC_SMJC_LIST", dict(base), timeout=150)
    eojc = await fetch(client, cookies, "TD_JC_ALL_EOJC_LIST", dict(base), timeout=150)
    by_code: dict[str, dict] = {}
    for row in smjc + eojc:
        code = str(row.get("JC_NO", "")).strip()
        if code:
            by_code[code] = row
    return by_code


def _wd(row: dict | None) -> str:
    return str((row or {}).get("WRITE_DATE", "")).strip()


async def full_version_check(store, client, cookies, *, fetch=None) -> dict:
    """全库版本检查：库内卡逐一比对 AMRO 编写日期；作废只入报告不删卡（决策#7/#8）。"""
    versions = await _pull_card_versions(client, cookies, fetch=fetch)
    revised, cancelled = [], []
    for card in store.get_all():
        code = card.get("task_code", "")
        row = versions.get(code)
        if row is None:
            cancelled.append({"task_code": code,
                              "task_name": card.get("task_name", ""),
                              "category": card.get("category", "")})
            continue
        new_wd = _wd(row)
        old_wd = str(card.get("write_date", "")).strip()
        if new_wd and new_wd != old_wd:
            store.update(card["id"], write_date=new_wd)
            revised.append({"task_code": code,
                            "task_name": card.get("task_name", ""),
                            "category": card.get("category", ""),
                            "old_wd": old_wd, "new_wd": new_wd})
    return {"revised": revised, "cancelled": cancelled, "total_amro": len(versions)}


async def check_cards_against_amro(store, client, cookies, task_codes, *, fetch=None) -> dict:
    """包级版本检查：拉两清单 → 对指定工卡比对 AMRO 编写日期 → {revised, cancelled}。

    仅处理卡库已存在的卡（包内新卡由匹配流程负责，不进版本报告）。
    """
    wanted = {str(c).strip() for c in task_codes if str(c).strip()}
    versions = await _pull_card_versions(client, cookies, fetch=fetch)
    all_cards = {c.get("task_code", ""): c for c in store.get_all()}
    revised, cancelled = [], []
    for code in sorted(wanted):
        card = all_cards.get(code)
        if card is None:
            continue
        row = versions.get(code)
        if row is None:
            cancelled.append({"task_code": code,
                              "task_name": card.get("task_name", ""),
                              "category": card.get("category", "")})
            continue
        new_wd = _wd(row)
        old_wd = str(card.get("write_date", "")).strip()
        if new_wd and new_wd != old_wd:
            store.update(card["id"], write_date=new_wd)
            revised.append({"task_code": code,
                            "task_name": card.get("task_name", ""),
                            "category": card.get("category", ""),
                            "old_wd": old_wd, "new_wd": new_wd})
    return {"revised": revised, "cancelled": cancelled}


def _group_by_category(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """按专业分组（发动机→机体→电子→其他，稳定顺序）—— 与提醒单分专业同构。"""
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        cat = str(r.get("category", "")).strip() or "其他"
        grouped.setdefault(cat, []).append(r)
    priority = {"发动机": 0, "机体": 1, "电子": 2}
    return [(c, grouped[c]) for c in sorted(grouped, key=lambda c: (priority.get(c, 99), c))]


def build_version_report_excel(report: dict) -> bytes:
    """改版清单 Excel（提醒单式分专业，两处查询同款格式，不标底色）。

    「改版工卡」sheet 分专业，行 = 工卡号 | 工卡名称 | 编写日期（旧→新）；
    「作废工卡」sheet 分专业，行 = 工卡号 | 工卡名称。
    """
    from openpyxl import Workbook

    def _date_span(wd: str) -> str:
        return (wd or "").strip()[:10]

    def write_sections(ws, rows: list[dict], with_dates: bool) -> None:
        ws.append(["工卡号", "工卡名称"] + (["编写日期"] if with_dates else []))
        for cat, items in _group_by_category(rows):
            ws.append([f"【{cat}】"])
            for it in items:
                row = [it.get("task_code", ""), it.get("task_name", "")]
                if with_dates:
                    old, new = _date_span(it.get("old_wd", "")), _date_span(it.get("new_wd", ""))
                    row.append(f"{old}→{new}" if old and new else (new or old))
                ws.append(row)

    wb = Workbook()
    ws = wb.active
    ws.title = "改版工卡"
    write_sections(ws, report.get("revised", []), with_dates=True)
    ws2 = wb.create_sheet("作废工卡")
    write_sections(ws2, report.get("cancelled", []), with_dates=False)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def start_full_version_check(store, session_store, output_dir) -> bool:
    """启动全量查询工卡版本后台任务。返回 False = 已有查询在跑（全局互斥，不排队）。"""
    def job():
        cookies = (session_store.load() or {}).get("cookies", {})

        async def _inner():
            async with httpx.AsyncClient(verify=True, trust_env=False) as client:
                rep = await full_version_check(store, client, cookies)
            ts = datetime.now(BJ).strftime("%Y%m%d_%H%M%S")
            filename = f"amro_full_version_report_{ts}.xlsx"
            (output_dir / filename).write_bytes(build_version_report_excel(rep))
            rep["filename"] = filename
            return rep

        rep = asyncio.run(_inner())
        return {"revised": len(rep["revised"]), "cancelled": len(rep["cancelled"]),
                "total_amro": rep["total_amro"], "filename": rep["filename"]}

    return run_query("full_version", "全量查询工卡版本", job)
