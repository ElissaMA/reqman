"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_query 包成 daemon 线程并写 QUERY_STATUS 内存态（running/done/error）；
全局查询互斥（try_begin_query）保证一次只跑一个 AMRO 查询，不排队。
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..config import (
    AMRO_AC_FLEET,
    AMRO_CARD_FLEET,
    CATEGORY_ORDER,
    CHECK_TEMPLATE_FILE,
    OUTPUT_DIR,
)
from ..utils.template_cache import load_template
from .connectors import amro
from .reminder_generator import COL_MAP

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
_running_query: dict | None = None
_query_token: str | None = None  # 持有者令牌：仅持令牌者能释放，防误释放/跨任务串扰


def try_begin_query(label: str) -> str | None:
    """占用全局查询槽。成功返回令牌（释放时回传），失败返回 None（已有查询在跑，不排队）。"""
    global _running_query, _query_token
    got = _query_lock.acquire(blocking=False)
    if got:
        _query_token = secrets.token_hex(8)
        _running_query = {"label": label, "started_at": _now()}
        return _query_token
    return None


def end_query(token: str | None = None) -> None:
    """释放全局查询槽（仅持有者令牌可释放；无令牌调用兼容旧路径但需与当前令牌一致）。"""
    global _running_query, _query_token
    if token is not None and token != _query_token:
        return
    _running_query = None
    _query_token = None
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
    """同步请求的查询槽上下文：进入时占用，退出时释放（持有令牌）。"""
    token = try_begin_query(label)
    if token is None:
        raise QueryBusyError(query_busy_message() or "已有查询任务进行中")
    try:
        yield
    finally:
        end_query(token)


class QueryBusyError(RuntimeError):
    """全局查询互斥冲突（已有查询在跑）。"""


# 内存任务状态注册表（v3.6.0：统一承载各查询任务状态；服务重启即清空）
QUERY_STATUS: dict[str, dict] = {}


def run_query(key: str, label: str, job, extra: dict | None = None) -> bool:
    """daemon 线程执行 job（占全局查询槽全程），QUERY_STATUS：running → done/error。

    extra 透传进每条状态记录（如 package_id），便于前端按标识恢复轮询。
    返回 False = 已有查询在跑（未启动）。
    """
    token = try_begin_query(label)
    if token is None:
        return False
    extra = extra or {}

    def runner():
        try:
            summary = job()
            QUERY_STATUS[key] = {"status": "done", "label": label,
                                 "finished_at": _now(), "summary": summary, **extra}
        except Exception as exc:
            logger.exception("AMRO 查询任务失败: %s", label)
            QUERY_STATUS[key] = {"status": "error", "label": label,
                                 "finished_at": _now(), "error": str(exc), **extra}
        finally:
            end_query(token)

    QUERY_STATUS[key] = {"status": "running", "label": label, "started_at": _now(), **extra}
    threading.Thread(target=runner, daemon=True, name=f"amro-{key}").start()
    return True


def get_query_status(key: str) -> dict:
    """读取某查询任务的内存状态（无记录返回空 dict）。"""
    return QUERY_STATUS.get(key, {})


# 最近一次查询结果简述持久化（output/last_query_<key>.json，重启保留）——
# 学习库存查询模式：每次查询结果可恢复显示在页面状态栏，报告类附下载链接。
def save_last_query_result(key: str, label: str, summary: str, download_url: str = "",
                           output_dir=None) -> None:
    """写入最近一次查询结果简述（只留最新一份）。"""
    out = output_dir or OUTPUT_DIR
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"last_query_{key}.json").write_text(json.dumps(
            {"label": label, "finished_at": _now(),
             "summary": summary, "download_url": download_url},
            ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.warning("查询结果简述写入失败: last_query_%s", key)


def get_last_query_result(key: str, output_dir=None) -> dict:
    """读取最近一次查询结果简述（无记录返回空 dict）。"""
    out = output_dir or OUTPUT_DIR
    path = out / f"last_query_{key}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


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


# 向后兼容别名（内部调用请直接用 build_package_label）
def package_display_label(pkg_data: dict) -> str:
    return build_package_label(pkg_data)


def package_report_label(pkg_data: dict) -> str:
    return build_package_label(pkg_data, with_date=True)


# ---------- AMRO 会话前置检查 ----------

def require_amro_session() -> bool:
    """AMRO 功能前置检查：仅 无凭证/明确失效 阻断；网络未知（probe_error）放行，
    避免偶发网络抖动/限流被误判未登录（真实失效由查询自身的 AMRO 调用暴露并 401）。"""
    from flask import current_app
    svc = current_app.extensions["inventory_service"]
    return svc.check_login_state() in ("valid", "probe_error")


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

        summary = asyncio.run(_inner())
        save_last_query_result("aircraft", "查询飞机数据",
                               f"新增 {summary['added']} 架，更新 {summary['updated']} 架，"
                               f"清理 {summary['removed']} 架（AMRO 在册 {summary['total_amro']} 架）")
        return summary

    return run_query("aircraft", "查询飞机数据", job)


# ---------- 工作包域 ----------

# 最近一次工作包列表查询快照（内存态，重启清空）：跨页面/刷新保留查询结果
_last_package_query: dict = {}


def get_last_package_query() -> dict:
    """最近一次工作包查询快照（rows + fetched_at），供 /upload 渲染注入。"""
    if not _last_package_query:
        return {}
    return {"rows": list(_last_package_query.get("rows", [])),
            "fetched_at": _last_package_query.get("fetched_at", "")}


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
    from ..config import AMRO_BASE_DEFAULT
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

async def _pull_smjc_versions(client, cookies, *, fetch=None) -> dict[str, dict]:
    """拉定检例行卡（SMJC）版本清单 → {task_code: row}。

    WRITE_DATE 零缺失（amro-research 实测）；fleet=AMRO_CARD_FLEET 服务端过滤
    （2026-09-01 实测 1319→745，约 2 页秒级）。EO/其他卡版本由
    TD_JC_ALL_GET_ENTITY_BY_JCNO 逐卡直查（_get_entity_by_jcno），不再全量拉
    EOJC 深分页（2026-09-03 教训：深分页延迟逐页递增不可控，击穿 150s 超时，
    全量 12 页约 12 分钟亦慢于逐卡）。
    """
    fetch = fetch or amro.fetch_all_pages
    rows = await fetch(client, cookies, "TD_JC_SMJC_LIST",
                       {"status": "ISSUED", "jcStatus": "Y", "rows": 500,
                        "fleet": AMRO_CARD_FLEET}, timeout=150)
    return {code: row for row in rows
            if (code := str(row.get("JC_NO", "")).strip())}


async def _pull_amro_family(client, cookies, plugin, form, prefixes, *, fetch=None) -> dict[str, dict]:
    """通用实时全量拉取某 AMRO 端点 → {task_code: row}（fleet 已在 form 内过滤）。

    prefix 过滤避免邻族误并入（如 EOJC 端点也会带回 QECJC/ERJC）。拉取异常由调用方
    回退逐卡 _get_entity_by_jcno，避免误判作废。
    """
    fetch = fetch or amro.fetch_all_pages
    rows = await fetch(client, cookies, plugin, dict(form), timeout=150)
    return {code: row for row in rows
            if (code := str(row.get("JC_NO", "")).strip())
            and code.startswith(prefixes)}


# 飞机维护工卡（FLA）批量端点候选：待实时只读探测确认后加入 READONLY_PLUGINS。
# 探测前保持不在白名单，_collect_card_versions 对其回退逐卡查询（功能不降级）。
AMRO_FLA_PLUGIN = "TD_JC_NRCJC_LIST"


async def _get_entity_by_jcno(client, cookies, jcno, *, query=None) -> dict | None:
    """TD_JC_ALL_GET_ENTITY_BY_JCNO 按卡号直查工卡实体 → row（查无返回 None）。

    单次 0.25~0.34s（2026-09-01 amro-research 实测）；定检 CSCA-* 与 EOJC-* 两族通用。
    响应 data 为单对象 dict（total 恒 0 属正常）；空 data 视为查无此卡。
    """
    query = query or amro.query_plugin
    body = await query(client, cookies, "TD_JC_ALL_GET_ENTITY_BY_JCNO", {"jcno": str(jcno)})
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) and data else None


def _wd(row: dict | None) -> str:
    return str((row or {}).get("WRITE_DATE", "")).strip()


def _family_of(code: str) -> str:
    """工卡所属权威源家族：CSC=定检，FLA=飞机维护，EO=EO工卡，QEC=QEC/ER。

    前缀兼容实际数据（如 CSCA* 归入 CSC 族）。非四家族 / 空 → 空串。
    """
    code = str(code).strip().upper()
    if code.startswith("CSC"):
        return "CSC"
    if code.startswith("FLA"):
        return "FLA"
    if code.startswith("EOJC"):
        return "EO"
    if code.startswith(("QECJC", "ERJC")):
        return "QEC"
    return ""


def _is_in_scope(code: str) -> bool:
    """仅四权威源家族参与版本检查（其余/DP 跳过，不查不判作废）。"""
    return bool(_family_of(code))


async def _collect_card_versions(store, client, cookies, codes, *, fetch=None, query=None) -> dict[str, dict]:
    """按卡号收集 AMRO 版本行（实时四端点，全量/逐包两处共用）。

    定检 CSC* → SMJC 全量拉；飞机维护 FLA* → FLA 端点全量拉（未确认前回退逐卡）；
    QEC/ER（QECJC*/ERJC*）→ EOJC 端点全量拉；EO（EOJC*）→ 仅对候选集存在的号逐卡直查；
    非四家族 / DP 不进 versions。各端点均按 fleet=A320 服务端过滤。
    任一全量拉取失败 → 该家族回退逐卡 _get_entity_by_jcno，避免误判作废。
    """
    wanted = {str(c).strip() for c in codes if str(c).strip()}
    fam: dict[str, set[str]] = {"CSC": set(), "FLA": set(), "QEC": set(), "EO": set()}
    for c in wanted:
        f = _family_of(c)
        if f:
            fam[f].add(c)
    versions: dict[str, dict] = {}

    async def _fallback_per_card(codes_in: set[str]) -> None:
        for code in sorted(codes_in):
            row = await _get_entity_by_jcno(client, cookies, code, query=query)
            if row is not None:
                versions[code] = row

    if fam["CSC"]:
        try:
            versions.update(await _pull_smjc_versions(client, cookies, fetch=fetch))
        except (httpx.HTTPError, ValueError, RuntimeError):
            await _fallback_per_card(fam["CSC"])
    if fam["FLA"]:
        # FLA 端点待实时只读探测确认后加入 amro.READONLY_PLUGINS；未确认前直走逐卡（不误判作废）。
        if AMRO_FLA_PLUGIN in getattr(amro, "READONLY_PLUGINS", frozenset()):
            try:
                versions.update(await _pull_amro_family(
                    client, cookies, AMRO_FLA_PLUGIN,
                    {"rows": 500, "fleet": AMRO_CARD_FLEET}, ("FLA",), fetch=fetch))
            except (httpx.HTTPError, ValueError, RuntimeError):
                await _fallback_per_card(fam["FLA"])
        else:
            await _fallback_per_card(fam["FLA"])
    if fam["QEC"]:
        try:
            versions.update(await _pull_amro_family(
                client, cookies, "TD_JC_ALL_QECJC_LIST",
                {"rows": 500, "fleet": AMRO_CARD_FLEET}, ("QECJC", "ERJC"), fetch=fetch))
        except (httpx.HTTPError, ValueError, RuntimeError):
            await _fallback_per_card(fam["QEC"])
    if fam["EO"]:
        await _fallback_per_card(fam["EO"])
    return versions


def _move_to_cancelled(store, cancelled_store, card: dict, source: str) -> None:
    """作废工卡移库：整卡入作废库（承接全部原字段）→ 主库删除。

    先入作废库再删主库；作废库按 task_code upsert，中断重跑不会重复。
    cancelled_store 为 None 时仅报告不移库（保持旧行为）。
    """
    if cancelled_store is None:
        return
    set_name = ""
    set_id = card.get("set_id")
    if set_id:
        set_data = store.get_set(set_id)
        set_name = set_data.get("name", "") if set_data else ""
    cancelled_store.add(card, source=source, set_name=set_name)
    store.delete(card["id"])


def _version_summary(revised_n: int, cancelled_n: int, checked_n: int, new_added_n: int = 0) -> str:
    """两处版本检查共用的基础摘要文案。

    new_added_n 为原库无编写日期、本次版本检查被新填入的工卡数（不计入「改版」）。
    """
    return f"改版 {revised_n} 张，新增 {new_added_n} 张，作废 {cancelled_n} 张，共检查 {checked_n} 张"


async def full_version_check(store, client, cookies, *, fetch=None, query=None,
                             cancelled_store=None) -> dict:
    """全库版本检查：库内卡逐一比对 AMRO 编写日期；作废整卡移入作废工卡库（决策#7 修订）。

    仅四权威源家族（CSC/FLA/EO/QEC-R）参与比对，其余（含 DP 项目）跳过不比对、不报作废。
    checked = 参与比对的四家族卡数；cancelled_store=None 时作废仅入报告不删卡。
    """
    all_cards = store.get_all()
    versions = await _collect_card_versions(store, client, cookies,
                                            [c.get("task_code", "") for c in all_cards],
                                            fetch=fetch, query=query)
    revised, new_added, cancelled = [], [], []
    checked = 0
    for card in all_cards:
        code = card.get("task_code", "")
        if not _is_in_scope(code):
            continue
        checked += 1
        row = versions.get(code)
        if row is None:
            cancelled.append({"task_code": code,
                              "task_name": card.get("task_name", ""),
                              "category": card.get("category", "")})
            _move_to_cancelled(store, cancelled_store, card, "full_version")
            continue
        new_wd = _wd(row)
        old_wd = str(card.get("write_date", "")).strip()
        if new_wd:
            if not old_wd:   # 原库无编写日期 → 本次新增（不计入改版）
                store.update(card["id"], write_date=new_wd)
                new_added.append({"task_code": code,
                                  "task_name": card.get("task_name", ""),
                                  "category": card.get("category", ""),
                                  "old_wd": "", "new_wd": new_wd})
            elif new_wd[:10] != old_wd[:10]:   # 按日期部分比对（界面 date 只存 YYYY-MM-DD）
                store.update(card["id"], write_date=new_wd)
                revised.append({"task_code": code,
                                "task_name": card.get("task_name", ""),
                                "category": card.get("category", ""),
                                "old_wd": old_wd, "new_wd": new_wd})
    return {"revised": revised, "new_added": new_added, "cancelled": cancelled, "checked": checked}


async def check_cards_against_amro(store, client, cookies, task_codes, *, fetch=None, query=None,
                                   cancelled_store=None) -> dict:
    """包级版本检查：拉清单 → 对指定工卡比对 AMRO 编写日期 → {revised, cancelled, checked}。

    仅处理卡库已存在的卡（包内新卡由人工前置入主库，不进版本报告）；
    作废整卡移入作废工卡库（cancelled_store=None 时仅入报告不删卡）。
    取数复用 _collect_card_versions（四家族实时取数：CSC 走 SMJC 全量拉、FLA 走 FLA 端点、
    QEC-R 走 EOJC 端点全量拉、EO 按卡号直查）；仅四家族参与，其余不查询、不误报作废。
    """
    wanted = {str(c).strip() for c in task_codes if _is_in_scope(str(c).strip())}
    versions = await _collect_card_versions(store, client, cookies, wanted,
                                            fetch=fetch, query=query)
    all_cards = {c.get("task_code", ""): c for c in store.get_all()}
    revised, new_added, cancelled = [], [], []
    for code in sorted(wanted):
        card = all_cards.get(code)
        if card is None:
            continue
        row = versions.get(code)
        if row is None:
            cancelled.append({"task_code": code,
                              "task_name": card.get("task_name", ""),
                              "category": card.get("category", "")})
            _move_to_cancelled(store, cancelled_store, card, "package_version")
            continue
        new_wd = _wd(row)
        old_wd = str(card.get("write_date", "")).strip()
        if new_wd:
            if not old_wd:   # 原库无编写日期 → 本次新增（不计入改版）
                store.update(card["id"], write_date=new_wd)
                new_added.append({"task_code": code,
                                  "task_name": card.get("task_name", ""),
                                  "category": card.get("category", ""),
                                  "old_wd": "", "new_wd": new_wd})
            elif new_wd[:10] != old_wd[:10]:   # 按日期部分比对（界面 date 只存 YYYY-MM-DD）
                store.update(card["id"], write_date=new_wd)
                revised.append({"task_code": code,
                                "task_name": card.get("task_name", ""),
                                "category": card.get("category", ""),
                                "old_wd": old_wd, "new_wd": new_wd})
    return {"revised": revised, "new_added": new_added, "cancelled": cancelled, "checked": len(wanted)}


def _group_by_category(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """按专业分组（发动机→机体→电子→其他，稳定顺序）—— 与提醒单分专业同构。

    排序优先级统一取自 config.CATEGORY_ORDER（单一来源）。
    """
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        cat = str(r.get("category", "")).strip() or "其他"
        grouped.setdefault(cat, []).append(r)
    return [(c, grouped[c]) for c in sorted(grouped, key=lambda c: (CATEGORY_ORDER.get(c, 99), c))]


def _ymd_date(ts: str) -> str:
    """时间戳 YYYY-MM-DD[_HH-MM-SS] 或 YYYYMMDD[_HHMMSS] → 统一日期 2026-09-01（非法输入返回空串）。"""
    ts = (ts or "").strip()
    d = ts.split("_")[0].replace("-", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else ""


def build_version_report_excel(report: dict, title_label: str = "",
                               finished_date: str = "") -> bytes:
    """改版清单 Excel —— 以专用模板《工卡改版清单》输出（两处查询共用）。

    模板（assets/check_template.xlsx）结构：行1 标题（A1:C1 合并）、行2 专业表头
    （A 电子 / B 发动机 / C 机体，深绿白字）、行3+ 数据区（已删飞机信息块与图例，
    每列预置绿底）。条目从行 3 起按专业列堆叠，同列先改版、再新增、最后作废——每个
    条目单单元格三行：工卡号 / 工卡名称（黑字）/ 标记（按类型着色）。标记行：改版=旧→新、
    新增=新增 <日期>、作废=作废。第三行配色：新增=红、改版=蓝、作废=黑（宋体 11），
    保留每列原绿底；单元格显式 wrap_text，三行稳定显示。
    """
    from openpyxl.cell.rich_text import CellRichText, InlineFont, TextBlock
    from openpyxl.styles import Alignment

    def _date_span(wd: str) -> str:
        return (wd or "").strip()[:10]

    def _next_row(ws, col: int, start: int = 3) -> int:
        """找到该列数据区下一个空行（从 start 起）。"""
        row = start
        while ws.cell(row=row, column=col).value not in (None, ""):
            row += 1
        return row

    label_part = f"（{title_label}）" if title_label else ""
    title = f"工卡改版清单{label_part}查询日期{finished_date}"

    wb = load_template(CHECK_TEMPLATE_FILE)
    ws = wb["改版清单"]
    ws["A1"] = title

    # 单元格三行：工卡号 / 工卡名称（黑）/ 标记（分类型色）。仅第三行着色。
    # 第三行标记配色：新增=红、改版=蓝、作废=黑。
    BLACK = InlineFont(rFont="宋体", sz=11, color="FF000000")
    RED = InlineFont(rFont="宋体", sz=11, color="FFFF0000")
    BLUE = InlineFont(rFont="宋体", sz=11, color="FF0000FF")

    def write_entries(rows: list[dict], *, color, with_dates: bool, prefix: str = "") -> None:
        for cat, items in _group_by_category(rows):
            col = COL_MAP.get(cat)
            if col is None:   # 特检/支援/其他：与提醒单一致不输出
                continue
            for it in items:
                cell = ws.cell(row=_next_row(ws, col), column=col)
                seq: list = [
                    TextBlock(BLACK, str(it.get("task_code", ""))),
                    "\n",
                    TextBlock(BLACK, str(it.get("task_name", ""))),
                    "\n",
                ]
                if with_dates:
                    old, new = _date_span(it.get("old_wd", "")), _date_span(it.get("new_wd", ""))
                    if old and new:
                        span = f"{old}→{new}"
                    elif new:
                        span = new
                    else:
                        span = old
                    if prefix and span:
                        span = f"{prefix} {span}"
                    if span:
                        seq.append(TextBlock(color, span))
                else:
                    seq.append(TextBlock(color, prefix or "作废"))
                cell.value = CellRichText(*seq)
                # 显式换行（不依赖模板样式），超出行也保证三行显示
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    write_entries(report.get("revised", []), color=BLUE, with_dates=True)
    write_entries(report.get("new_added", []), color=RED, with_dates=True, prefix="新增")
    write_entries(report.get("cancelled", []), color=BLACK, with_dates=False)
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    buf.seek(0)
    return buf.getvalue()


def start_full_version_check(store, session_store, output_dir, cancelled_store=None) -> bool:
    """启动全量查询工卡版本后台任务。返回 False = 已有查询在跑（全局互斥，不排队）。"""
    def job():
        cookies = (session_store.load() or {}).get("cookies", {})

        async def _inner():
            async with httpx.AsyncClient(verify=True, trust_env=False) as client:
                rep = await full_version_check(store, client, cookies, cancelled_store=cancelled_store)
            ts = datetime.now(BJ).strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"amro_full_version_report_{ts}.xlsx"
            (output_dir / filename).write_bytes(
                build_version_report_excel(rep, title_label="全量",
                                           finished_date=_ymd_date(ts)))
            rep["filename"] = filename
            return rep

        rep = asyncio.run(_inner())
        save_last_query_result("full_version", "全量查询工卡版本",
                               _version_summary(len(rep["revised"]), len(rep["cancelled"]),
                                                rep["checked"], len(rep["new_added"])),
                               download_url="/card/amro-version-report", output_dir=output_dir)
        return {"revised": len(rep["revised"]), "new_added": len(rep["new_added"]),
                "cancelled": len(rep["cancelled"]),
                "checked": rep["checked"], "filename": rep["filename"]}

    return run_query("full_version", "全量查询工卡版本", job)


def start_package_version_check(store, session_store, package_id: str, pkg_data: dict,
                                cancelled_store=None) -> bool:
    """启动逐包工卡版本检查后台任务。返回 False = 已有查询在跑（全局互斥，不排队）。

    长任务（逐卡直查 EO/NRC 约 2 分钟/50 张）移出请求线程，前端轮询
    get_query_status("package_version") 获取进度，避免 gunicorn 120s 杀请求。
    """
    label = build_package_label(pkg_data) or package_id
    cookies = (session_store.load() or {}).get("cookies", {})
    finished_date = datetime.now(BJ).strftime("%Y-%m-%d")

    def job():
        task_codes = list(dict.fromkeys(
            it.get("task_code") for it in pkg_data.get("all_items", []) if it.get("task_code")))

        async def _inner():
            async with httpx.AsyncClient(verify=True, trust_env=False) as client:
                return await check_cards_against_amro(store, client, cookies, task_codes,
                                                      cancelled_store=cancelled_store)

        report = asyncio.run(_inner())
        filename = f"amro_pkg_version_report_{package_id}.xlsx"
        (OUTPUT_DIR / filename).write_bytes(build_version_report_excel(
            report, title_label=build_package_label(pkg_data, with_date=True) or package_id,
            finished_date=finished_date))
        summary = {"revised": len(report["revised"]), "new_added": len(report["new_added"]),
                   "cancelled": len(report["cancelled"]),
                   "checked": report["checked"], "filename": filename}
        save_last_query_result(
            "package_version", "查询工作包工卡版本",
            f"版本检查完成（{label}）："
            f"{_version_summary(summary['revised'], summary['cancelled'], summary['checked'], summary['new_added'])}"
            f"（预览页可下载改版清单）",
            download_url=f"/generate/package-version-report?package_id={package_id}",
            output_dir=OUTPUT_DIR)
        return summary

    return run_query("package_version", "查询工作包工卡版本", job,
                     extra={"package_id": package_id, "label": label})


def start_inventory_query(svc, staged_path: Path, output_stem: str,
                         warning_thresholds: dict | None = None,
                         warning_pns: list | None = None,
                         store=None) -> bool:
    """启动库存查询后台任务。返回 False = 已有查询在跑（全局互斥，不排队）。

    ≥1s 节流下大需求单（>50 件号）仍可能接近 gunicorn 120s 请求超时，故移出请求线程，
    前端轮询 get_query_status("inventory_query") 获取进度/结果，避免请求被杀死。
    staged_path 为请求内持久化的上传暂存，job 内 finally 清理（请求结束不得删除）。
    warning_thresholds/warning_pns/store 用于把预警库件号纳入查询并回写缓存库存。
    """

    def job():
        try:
            _dest, filename, result = svc.run_query(
                staged_path, output_stem=output_stem,
                warning_thresholds=warning_thresholds,
                warning_pns=warning_pns, store=store,
            )
        finally:
            try:
                staged_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("清理库存上传暂存失败: %s", staged_path)
        summary = (f"查询完成：共 {result.total} 件号，成功 {result.success}，"
                   f"失败 {result.fail}，标红 {result.shortage}，标黄 {result.warning}")
        save_last_query_result(
            "inventory_query", "查询库存", summary,
            download_url=f"/inventory/download?file={quote(filename)}", output_dir=OUTPUT_DIR,
        )
        return {"filename": filename, "total": result.total, "success": result.success,
                "fail": result.fail, "shortage": result.shortage, "warning": result.warning}

    return run_query("inventory_query", "查询库存", job)
