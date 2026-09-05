"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_query 包成 daemon 线程并写 QUERY_STATUS 内存态（running/done/error）；
全局查询互斥（try_begin_query）保证一次只跑一个 AMRO 查询，不排队。
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..connectors import amro
from .query_runner import _now

logger = logging.getLogger(__name__)

BJ = ZoneInfo("Asia/Shanghai")

_last_package_query: dict = {}

def _main_squadron(zrfd: str) -> str:
    """ZRFD 责任分队串（逗号分隔，主责带“(主)”）→ 主分队名（剥掉“(主)”，无标记取首项）。"""
    parts = [p.strip() for p in str(zrfd or "").replace("，", ",").split(",") if p.strip()]
    for name in parts:
        if name.endswith(("（主）", "(主)")):
            return name[:-3].strip()
    return parts[0] if parts else ""



def _package_header(row: dict | None) -> dict:
    """BM_TSK_LIST 选中行 → 包头（ACNO/ACTYPE/ENGTYPE/REVTITLE/CHKTP/PLANSTD/ZRFD/LIMH）。

    包头字段只存在于包列表端点（BM_TSK_LIST 41 字段）；包内容清单（BM_TSK_002_LIST）无这些键，
    必须由列表行构建（2026-08-31 修复：此前从清单行取包头导致机号/描述空、日期兜底成导入日）。
    """
    row = row or {}
    raw_date = str(row.get("PLANSTD", "")).strip()
    raw_end = str(row.get("PLANEND", "")).strip()
    return {
        "package": str(row.get("REVNR", "")).strip(),
        "reg": str(row.get("ACNO", "")).strip(),
        "type": str(row.get("ACTYPE", "")).strip(),
        "description": str(row.get("REVTITLE", "")).strip(),
        "level": str(row.get("CHKTP", "")).strip(),
        "date": raw_date.split()[0].replace("-", ".") if raw_date else "",  # 与解析器同语义
        "engine": str(row.get("ENGTYPE", "")).strip(),
        "plan_end": raw_end.split()[0].replace("-", ".") if raw_end else "",
        "squadron": _main_squadron(str(row.get("ZRFD", ""))),
        "plan_hours": str(row.get("LIMH", "")).strip(),  # 语义待真实冒烟校准
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



def package_items(rows_routine: list[dict], rows_other: list[dict], header_row: dict | None = None) -> dict:
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
    return {"all_items": uniq, "aircraft_info": _package_header(header_row)}



def persist_amro_package(store, service, package_data: dict) -> dict:
    """AMRO 直读入库：仅入库不匹配（与 Excel 导入一致），生成日期留空待匹配时再记。

    匹配动作由「重新匹配」或打开生成页触发；摘要返回 routine/other 计数（不再有 new_cards）。
    """
    all_items = package_data.get("all_items", [])
    package_data.update({
        "matched": [], "new_cards": [], "cancelled": [],
        "is_matched": False, "generated_at": None,
        "routine_count": sum(1 for i in all_items if i.get("source") == "例行"),
        "other_count": sum(1 for i in all_items if i.get("source") == "其他"),
    })
    store.save_work_package(package_data)
    return {"package_id": package_data.get("package_id"),
            "routine": package_data["routine_count"], "other": package_data["other_count"]}



async def import_amro_package(store, client, cookies, revnr, service=None, *, fetch=None,
                              header_row: dict | None = None) -> dict:
    """拉 BM_TSK_002_LIST + BM_TSK_002_LIST_QT → package_items → 入库 → 摘要。

    header_row 为前端选中的 BM_TSK_LIST 行（含 ACNO/REVTITLE/PLANSTD 等包头字段）；
    未传时兜底调 list_amro_packages 按 REVNR 匹配。
    """
    fetch = fetch or amro.fetch_all_pages
    base = {"revnr": str(revnr), "rows": 50}
    rows_routine = await fetch(client, cookies, "BM_TSK_002_LIST", dict(base), timeout=60)
    rows_other = await fetch(client, cookies, "BM_TSK_002_LIST_QT", dict(base), timeout=60)
    if not header_row:
        listing = await list_amro_packages(client, cookies)
        header_row = next((r for r in listing if str(r.get("REVNR", "")) == str(revnr)), None)
    out = package_items(rows_routine, rows_other, header_row)
    info = out["aircraft_info"]
    package_data = {
        "reg": info.get("reg", ""),
        "description": info.get("description", ""),
        "date": info.get("date", "") or datetime.now(BJ).strftime("%Y-%m-%d"),
        "aircraft_info": info,
        "all_items": out["all_items"],
        "source": "AMRO",
    }
    return persist_amro_package(store, service, package_data)



async def list_amro_packages(client, cookies, *, base=None) -> list[dict]:
    """BM_TSK_LIST 任务接收包列表（total 恒 0 单页返回；不过滤日期窗，返回接收页面全部任务包）。"""
    from ...config import AMRO_BASE_DEFAULT
    base = base or AMRO_BASE_DEFAULT
    form = {
        "gjzStr": "", "initBase": "", "baseCode1": "", "baseCode": base,
        "chktp": "",
        "revst": "WJS|ZB|YZB|KG", "xfdw": "", "actype": "", "acno": "",
        "gjz": "", "iftj": "", "ifgzrz": "", "page": 1, "rows": 50,
    }
    body = await amro.query_plugin(client, cookies, "BM_TSK_LIST", form)
    rows = body.get("data") or []
    _last_package_query.clear()
    _last_package_query.update({"rows": rows, "fetched_at": _now()})
    return rows


# ---------- 工卡版本域 ----------


def get_last_package_query() -> dict:
    """最近一次工作包查询快照（rows + fetched_at），供 /upload 渲染注入。"""
    if not _last_package_query:
        return {}
    return {"rows": list(_last_package_query.get("rows", [])),
            "fetched_at": _last_package_query.get("fetched_at", "")}



def build_package_label(pkg_data: dict, *, with_date: bool = False) -> str:
    """工作包标识：机号+描述（aircraft_info 优先、顶层兜底），可选附开工日期。

    统一替代原 package_display_label / package_report_label：提示、下载文件名、
    版本报告标题共用同一构造，避免两处散落的字符串拼接再漂移。日期归一化为点分格式。
    """
    info = pkg_data.get("aircraft_info") or {}
    reg = str(info.get("reg") or pkg_data.get("reg") or "").strip()
    desc = str(info.get("description") or pkg_data.get("description") or "").strip()
    parts = [x for x in (reg, desc) if x]
    if with_date:
        date = str(pkg_data.get("date") or info.get("date") or "").strip().replace("-", ".")
        if date:
            parts.append(date)
    return " ".join(parts)


# ---------- AMRO 会话前置检查 ----------
