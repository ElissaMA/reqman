"""日志蓝图 —— 操作日志的浏览、导出与删除"""

import logging
from datetime import datetime
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, jsonify, flash, redirect
from flask import current_app

from ..utils.response import api_success, api_error
from ..utils.error_handlers import _wants_json, raise_or_flash, NotFoundError, ServerError

logger = logging.getLogger(__name__)

bp = Blueprint("logs", __name__, url_prefix="/card")

# 操作类型中文显示
OPERATION_LABELS = {
    "add": "新增",
    "update": "修改",
    "delete": "删除",
}

# 目标类型中文显示
TARGET_TYPE_LABELS = {
    "card": "工卡",
    "set": "工卡组",
    "aircraft": "飞机信息",
}

# 字段中文标签（用于展示变更内容）
FIELD_LABELS = {
    "task_code": "工卡编码",
    "task_name": "工卡名称",
    "category": "分类",
    "tools": "工具",
    "materials": "航材",
    "name": "名称",
    "description": "描述",
}


def _get_service():
    """获取 CardService 实例"""
    return current_app.extensions.get("card_service")


def _format_changes(changes: list) -> str:
    """将 changes 列表转为可读字符串"""
    if not changes:
        return ""
    parts = []
    for c in changes:
        field = c.get("field", "")
        label = FIELD_LABELS.get(field, field)
        old_val = c.get("old", "")
        new_val = c.get("new", "")
        if isinstance(old_val, list):
            old_val = f"[{len(old_val)} 项]"
        if isinstance(new_val, list):
            new_val = f"[{len(new_val)} 项]"
        parts.append(f"{label}: {old_val} → {new_val}")
    return "; ".join(parts)


def _build_filtered_logs(args: dict) -> list:
    """根据筛选条件返回日志列表"""
    service = _get_service()
    if not service:
        return []
    logs = list(service.store.get_logs())

    # 按日期筛选
    date_from = args.get("date_from", "").strip()
    if date_from:
        logs = [l for l in logs if (l.get("timestamp") or "")[:10] >= date_from]

    logs.sort(key=lambda l: l.get("timestamp", ""), reverse=True)
    return logs


# ===================== 路由 =====================


@bp.route("/logs")
def list_logs():
    """日志列表页面"""
    logs = _build_filtered_logs(request.args)

    page = request.args.get("page", 1, type=int)
    per_page = 20
    total = len(logs)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_logs = logs[start:end]

    # 保留筛选参数（除 page 外）用于分页链接
    qp = {k: v for k, v in request.args.items() if k != "page"}
    query_params = "&" + urlencode(qp) if qp else ""

    return render_template(
        "cards/logs.html",
        logs=page_logs,
        page=page,
        total_pages=total_pages,
        total=total,
        query_params=query_params,
        operation_labels=OPERATION_LABELS,
        target_type_labels=TARGET_TYPE_LABELS,
        field_labels=FIELD_LABELS,
        format_changes=_format_changes,
    )


@bp.route("/logs/delete", methods=["POST"])
def delete_logs():
    """删除选中日志"""
    log_ids = request.form.getlist("log_ids[]")

    if not log_ids:
        if _wants_json():
            return api_error("请选择要删除的日志", "NO_LOGS_SELECTED")
        flash("请选择要删除的日志", "error")
        return redirect(request.headers.get("Referer", "/"))

    service = _get_service()
    if not service:
        if _wants_json():
            return api_error("服务不可用", "SERVICE_UNAVAILABLE", 500)
        flash("服务不可用", "error")
        return redirect(request.headers.get("Referer", "/"))

    try:
        count = service.delete_logs([int(lid) for lid in log_ids if lid.isdigit()])
    except Exception as e:
        logger.exception("删除日志失败")
        if _wants_json():
            return api_error(f"删除日志失败: {e}", "DELETE_FAILED", 500)
        flash(f"删除日志失败: {e}", "error")
        return redirect(request.headers.get("Referer", "/"))

    if _wants_json():
        return api_success({"deleted_count": count}, f"成功删除 {count} 条日志")

    flash(f"成功删除 {count} 条日志", "success")
    return redirect("/card/logs")
