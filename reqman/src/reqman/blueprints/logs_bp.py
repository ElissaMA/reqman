"""日志蓝图 —— 操作日志的浏览、导出与删除"""

import logging

from flask import Blueprint, current_app, flash, redirect, render_template, request

from ..utils.error_handlers import ServerError, _wants_json
from ..utils.response import api_error, api_success

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

    # 按操作类型筛选
    operation = args.get("operation", "").strip()
    if operation:
        logs = [l for l in logs if l.get("operation") == operation]

    # 按目标类型筛选
    target_type = args.get("target_type", "").strip()
    if target_type:
        logs = [l for l in logs if l.get("target_type") == target_type]

    # 按关键词搜索（目标标识/目标名称）
    keyword = args.get("keyword", "").strip()
    if keyword:
        kw = keyword.lower()
        logs = [l for l in logs if kw in (l.get("target_identifier") or "").lower() or kw in (l.get("target_name") or "").lower()]

    # 按日期筛选
    date_from = args.get("date_from", "").strip()
    if date_from:
        logs = [l for l in logs if (l.get("timestamp") or "")[:10] >= date_from]

    logs.sort(key=lambda l: l.get("timestamp", ""), reverse=True)
    return logs


# ===================== 路由 =====================


@bp.route("/logs")
def list_logs():
    """操作日志列表 - 全量传前端做客户端筛选"""
    try:
        service = _get_service()
        if not service:
            raise ServerError("服务不可用")
        all_logs = list(service.get_logs())
        # 按时间倒序
        all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return render_template("cards/logs.html",
                               logs=all_logs,
                               total=len(all_logs),
                               operation_labels=OPERATION_LABELS,
                               target_type_labels=TARGET_TYPE_LABELS,
                               field_labels=FIELD_LABELS,
                               format_changes=_format_changes)
    except Exception:
        logger.exception("获取操作日志失败")
        flash("加载操作日志失败", "error")
        return render_template("cards/logs.html",
                               logs=[], total=0,
                               operation_labels=OPERATION_LABELS,
                               target_type_labels=TARGET_TYPE_LABELS,
                               field_labels=FIELD_LABELS,
                               format_changes=_format_changes)


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
