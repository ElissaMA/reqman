"""工作包蓝图 — 上传工作清单 + 工卡匹配 + AMRO 直读拉包"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from flask import Blueprint, current_app, flash, redirect, render_template, request

from ..config import CATEGORIES, OUTPUT_DIR
from ..services import amro_sync
from ..services.connectors.amro import AmroSessionExpired
from ..services.work_package_matcher import match_work_package_items
from ..services.worklist_parser import WorklistError, merge_aircraft_info, parse_worklist
from ..utils.dates import fmt_date10
from ..utils.error_handlers import NotFoundError, ValidationError, is_ajax
from ..utils.messages import MESSAGES
from ..utils.response import api_error, api_success
from ..utils.validators import validate_file_extension

logger = logging.getLogger(__name__)

packages_bp = Blueprint("packages", __name__)


# ======================== 辅助函数 ========================



def _parse_wp_date(date_str):
    """解析 'YYYY.MM.DD' 格式日期，失败返回 None"""
    try:
        parts = date_str.split(".")
        if len(parts) != 3:
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def _classify_package(wp):
    """判断工作包状态：expired(过期>2天删除) / warning(过期≤2天灰色) / danger(未来4天内红色) / normal"""
    wp_date = _parse_wp_date(wp.get("date", ""))
    if not wp_date:
        return "normal"
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    diff = (wp_date - today).days
    if diff < -2:
        return "expired"
    elif diff < 0:
        return "warning"
    elif diff <= 4:
        return "danger"
    else:
        return "normal"


def _parse_and_save_file(f, label):
    """解析上传的 Excel 文件，返回 (items, aircraft_info)
    如失败抛出 ValidationError
    """
    if not f or not f.filename:
        return [], {}
    validate_file_extension(f.filename, {"xlsx"}, label=f"{label}清单")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = os.path.join(tmp_dir, f"{label}.xlsx")
        f.save(tmp_path)
        result = parse_worklist(tmp_path, label)
    return result["items"], result["aircraft_info"]


# ======================== 路由 ========================


@packages_bp.route("/upload", methods=["GET", "POST"])
def upload():
    """上传工作清单并匹配"""
    if request.method == "POST":
        return _handle_upload_post()
    store = current_app.extensions['store']
    work_packages = store.get_work_packages()
    version_logs = _version_log_rows(store)

    # 自动删除过期>2天的工作包，并标记状态
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    filtered = []
    for wp in work_packages:
        wp_date = _parse_wp_date(wp.get("date", ""))
        if wp_date and (today - wp_date).days > 2:
            store.delete_work_package(wp["package_id"])
            continue
        wp["status"] = _classify_package(wp)
        filtered.append(wp)

    return render_template("packages/upload.html", work_packages=filtered,
                           version_logs=version_logs,
                           amro_pkg_query=amro_sync.get_last_package_query(),
                           amro_last_pkg_query=amro_sync.get_last_query_result("package"),
                           amro_last_pkg_ver=amro_sync.get_last_query_result("package_version"))


def _version_log_rows(store, limit: int = 50) -> list[dict]:
    """card_logs → 工卡版本变动清单行（时间|工卡号|工卡名称|旧编写日期|新编写日期|操作）。"""
    rows = []
    for l in store.get_version_logs(limit=limit):
        change = next((c for c in l.get("changes", []) if c.get("field") == "write_date"), {})
        rows.append({
            "time": str(l.get("timestamp", ""))[:16].replace("T", " "),
            "task_code": l.get("target_identifier", ""),
            "task_name": l.get("target_name", ""),
            "old": fmt_date10(change.get("old", "")),
            "new": fmt_date10(change.get("new", "")),
            "operation": l.get("operation", ""),
        })
    return rows


def _handle_upload_post():
    """处理上传 POST 请求逻辑"""
    store = current_app.extensions['store']
    routine_file = request.files.get("routine_file")
    other_file = request.files.get("other_file")

    if not routine_file and not other_file:
        raise ValidationError("请至少上传一个文件", "NO_FILE")

    all_items = []
    info_list = []
    errors = []

    for f, label in [(routine_file, "例行"), (other_file, "其他")]:
        if not f or not f.filename:
            continue
        try:
            items, info = _parse_and_save_file(f, label)
            all_items.extend(items)
            if info:
                info_list.append(info)
        except (ValidationError, WorklistError) as e:
            msg = e.message if hasattr(e, "message") else str(e)
            errors.append(f"{label}清单: {msg}")
        except Exception:
            errors.append(f"{label}清单解析失败")
            logger.exception(f"解析{label}清单异常")

    if errors:
        for err in errors:
            logger.warning("上传错误: %s", err)
        if not all_items:
            raise ValidationError("；".join(errors), "PARSE_FAILED")
        # 部分成功：仅警告不阻断

    aircraft_info = merge_aircraft_info(info_list) if info_list else {}

    cat_order = {c: i for i, c in enumerate(CATEGORIES)}
    all_items.sort(key=lambda x: cat_order.get(x.get("category", ""), 99))


    package_data = {
        "reg": aircraft_info.get("reg", ""),
        "description": aircraft_info.get("description", ""),
        "date": aircraft_info.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")),
        "aircraft_info": aircraft_info,
        "all_items": all_items,
    }
    package_data = _persist_package(store, package_data)

    if is_ajax():
        return api_success(data={"package_id": package_data.get("package_id")},
                           message="工作包上传成功")
    flash("工作包上传成功，点击工作包即可匹配生成", "success")
    return redirect("/upload")


def _persist_package(store, package_data: dict) -> dict:
    """工作包入库（upload 兜底路径）：保存原始清单，匹配延后到生成页打开时。"""
    package_data["matched"] = []
    package_data["new_cards"] = []
    package_data["cancelled"] = []
    package_data["routine_count"] = sum(1 for i in package_data.get("all_items", []) if i.get("source") == "例行")
    package_data["other_count"] = sum(1 for i in package_data.get("all_items", []) if i.get("source") == "其他")
    package_data["is_matched"] = False
    package_data["generated_at"] = None
    store.save_work_package(package_data)
    return package_data


@packages_bp.route("/packages/<package_id>/rematch", methods=["POST"])
def package_rematch(package_id):
    """重新匹配工作包中的工卡（数据库更新后刷新匹配状态）"""
    store = current_app.extensions['store']
    pkg_data = store.get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("工作包不存在")

    all_items = pkg_data.get("all_items", [])
    service = current_app.extensions['card_service']
    matched, new_cards, cancelled = match_work_package_items(all_items, store, service)

    now_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    pkg_data["matched"] = matched
    pkg_data["new_cards"] = new_cards
    pkg_data["cancelled"] = cancelled
    pkg_data["routine_count"] = sum(1 for i in all_items if i.get("source") == "例行")
    pkg_data["other_count"] = sum(1 for i in all_items if i.get("source") == "其他")
    pkg_data["is_matched"] = True
    pkg_data["generated_at"] = now_str
    store.save_work_package(pkg_data)

    if is_ajax():
        return api_success(message="重新匹配完成")
    flash("重新匹配完成", "success")
    return redirect("/upload")


def _amro_err(kind, exc=None):
    """AMRO 端点统一错误响应（error_code 对齐 inventory_bp 约定）。

    session: 前置登录检查未过 → 401 P8
    busy:    全局查询互斥冲突 → 409 统一 busy 文案
    amro:    AMRO 请求/异常 → 502
    """
    if kind == "session":
        return api_error(MESSAGES["P8"], "LOGIN_EXPIRED", 401)
    if kind == "busy":
        return api_error(amro_sync.query_busy_message()
                         or "已有查询任务进行中，请等待完成后再查询", "QUERY_BUSY", 409)
    if kind == "amro":
        return api_error(f"AMRO 请求失败: {exc}", "AMRO_ERROR", 502)
    raise ValueError(f"未知 AMRO 错误类型: {kind}")


# ======================== AMRO 直读（v3.5.0） ========================

@packages_bp.route("/packages/amro-list", methods=["GET", "POST"])
def amro_package_list():
    """AMRO 任务接收包列表（BM_TSK_LIST，baseCode=KM01，不过滤日期窗）。"""
    if not amro_sync.require_amro_session():
        return _amro_err("session")
    svc = current_app.extensions["inventory_service"]
    cookies = (svc.session_store.load() or {}).get("cookies", {})

    async def _inner():
        async with httpx.AsyncClient(verify=True, trust_env=False) as client:
            return await amro_sync.list_amro_packages(client, cookies)

    try:
        with amro_sync.query_slot("查询工作包"):
            packages = asyncio.run(_inner())
    except amro_sync.QueryBusyError:
        return _amro_err("busy")
    except AmroSessionExpired as e:
        return api_error(str(e), "LOGIN_EXPIRED", 401)
    except (httpx.HTTPError, RuntimeError) as e:
        logger.exception("AMRO 包列表拉取失败")
        return _amro_err("amro", e)
    amro_sync.save_last_query_result("package", "查询工作包",
                                     f"获取到 {len(packages)} 个任务包",
                                     output_dir=OUTPUT_DIR)
    return api_success(data={"packages": packages,
                             "fetched_at": amro_sync.get_last_package_query().get("fetched_at", "")})


@packages_bp.route("/packages/amro-fetch", methods=["POST"])
def amro_package_fetch():
    """revnr + header（BM_TSK_LIST 选中行）→ 拉两清单 → 入库 → package_id（同步请求）。"""
    if not amro_sync.require_amro_session():
        return _amro_err("session")
    revnr = (request.form.get("revnr") or "").strip()
    if not revnr:
        raise ValidationError("缺少包号 revnr", "NO_REVNR")
    header_row = None
    raw_header = request.form.get("header", "")
    if raw_header:
        try:
            header_row = json.loads(raw_header)
        except (ValueError, TypeError):
            header_row = None
    store = current_app.extensions["store"]
    service = current_app.extensions["card_service"]
    svc = current_app.extensions["inventory_service"]
    cookies = (svc.session_store.load() or {}).get("cookies", {})

    async def _inner():
        async with httpx.AsyncClient(verify=True, trust_env=False) as client:
            return await amro_sync.import_amro_package(store, client, cookies, revnr, service,
                                                       header_row=header_row)

    try:
        with amro_sync.query_slot("查询工作包"):
            summary = asyncio.run(_inner())
    except amro_sync.QueryBusyError:
        return _amro_err("busy")
    except AmroSessionExpired as e:
        return api_error(str(e), "LOGIN_EXPIRED", 401)
    except (httpx.HTTPError, RuntimeError) as e:
        logger.exception("AMRO 工作包 %s 导入失败", revnr)
        return _amro_err("amro", e)
    message = (f"工作包 {revnr} 已导入：例行 {summary['routine']} 项，其他 {summary['other']} 项"
               "（请在表格中重新匹配或打开预览页完成匹配）")
    return api_success(data=summary, message=message)


@packages_bp.route("/packages/amro-version-logs")
def amro_version_logs():
    """版本变动日志（card_logs 筛选视图，倒序最近 50 条）。"""
    logs = _version_log_rows(current_app.extensions["store"])
    return api_success(data={"logs": logs})


@packages_bp.route("/packages/<package_id>/amro-version-check", methods=["POST"])
def package_amro_version_check(package_id):
    """查询工作包工卡版本（后台线程，前端轮询状态）：实时比对包内工卡 → 更新版本 → 生成逐包改版清单。

    长任务移出请求线程，避免 gunicorn 120s 杀请求；前端轮询 /amro-version-status 取进度。
    """
    if not amro_sync.require_amro_session():
        return _amro_err("session")
    store = current_app.extensions["store"]
    pkg_data = store.get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("工作包不存在")
    session_store = current_app.extensions["inventory_service"].session_store
    if not amro_sync.start_package_version_check(store, session_store, package_id, pkg_data,
                                                 current_app.extensions["cancelled_cards"]):
        return _amro_err("busy")
    return api_success(data={"started": True})


@packages_bp.route("/packages/amro-version-status")
def package_amro_version_status():
    """逐包工卡版本检查进度/简要结果（全局内存态，前端轮询/恢复加载）。"""
    return api_success(data=amro_sync.get_query_status("package_version"))
