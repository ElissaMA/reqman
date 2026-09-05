"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_query 包成 daemon 线程并写 QUERY_STATUS 内存态（running/done/error）；
全局查询互斥（try_begin_query）保证一次只跑一个 AMRO 查询，不排队。
"""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

# OUTPUT_DIR 通过包级属性运行时取值，以便测试 monkeypatch amro_sync.OUTPUT_DIR 生效
from reqman.services import amro_sync

from ...config import (
    AMRO_CARD_FLEET,
    CATEGORY_ORDER,
    CHECK_TEMPLATE_FILE,
)
from ...utils.template_cache import load_template
from ..connectors import amro
from ..reminder_generator import COL_MAP

logger = logging.getLogger(__name__)

BJ = ZoneInfo("Asia/Shanghai")

AMRO_FLA_PLUGIN = "TD_JC_NRCJC_LIST"

from .packages import build_package_label
from .query_runner import run_query, save_last_query_result


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
        (amro_sync.OUTPUT_DIR / filename).write_bytes(build_version_report_excel(
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
            output_dir=amro_sync.OUTPUT_DIR)
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
            download_url=f"/inventory/download?file={quote(filename)}", output_dir=amro_sync.OUTPUT_DIR,
        )
        return {"filename": filename, "total": result.total, "success": result.success,
                "fail": result.fail, "shortage": result.shortage, "warning": result.warning}

    return run_query("inventory_query", "查询库存", job)

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


# 飞机维护工卡（FLA）批量端点：已实时只读探测确认（code=200、返回 FLA* 前缀、fleet=A320 过滤 646→356），
# 已加入 READONLY_PLUGINS 白名单（见 connectors/amro.py），FLA 族走全量拉取。



async def _get_entity_by_jcno(client, cookies, jcno, *, query=None) -> dict | None:
    """TD_JC_ALL_GET_ENTITY_BY_JCNO 按卡号直查工卡实体 → row（查无返回 None）。

    单次 0.25~0.34s（2026-09-01 amro-research 实测）；定检 CSCA-* 与 EOJC-* 两族通用。
    响应 data 为单对象 dict（total 恒 0 属正常）；空 data 视为查无此卡。
    """
    query = query or amro.query_plugin
    body = await query(client, cookies, "TD_JC_ALL_GET_ENTITY_BY_JCNO", {"jcno": str(jcno)})
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) and data else None



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
