"""日志蓝图 —— 操作日志的浏览、导出与删除"""

import logging

from flask import Blueprint, current_app, flash, redirect, render_template, request

from ..utils.error_handlers import _wants_json
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

# 分页配置
PAGE_SIZE_OPTIONS = (10, 20, 50, 100)
DEFAULT_PAGE_SIZE = 20

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
    logs = list(service.store.get_logs(limit=None))

    # 按操作类型筛选
    operation = args.get("operation", "").strip()
    if operation:
        logs = [log for log in logs if log.get("operation") == operation]

    # 按目标类型筛选
    target_type = args.get("target_type", "").strip()
    if target_type:
        logs = [log for log in logs if log.get("target_type") == target_type]

    # 按关键词搜索（目标标识/目标名称）
    keyword = args.get("keyword", "").strip()
    if keyword:
        kw = keyword.lower()
        logs = [log for log in logs if kw in (log.get("target_identifier") or "").lower() or kw in (log.get("target_name") or "").lower()]

    # 按日期筛选
    date_from = args.get("date_from", "").strip()
    if date_from:
        logs = [log for log in logs if (log.get("timestamp") or "")[:10] >= date_from]

    logs.sort(key=lambda log: log.get("timestamp", ""), reverse=True)
    return logs


# ===================== 路由 =====================


@bp.route("/logs")
def list_logs():
    """操作日志列表 - 服务端筛选 + 分页"""
    args = {
        "operation": request.args.get("operation", "").strip(),
        "target_type": request.args.get("target_type", "").strip(),
        "keyword": request.args.get("keyword", "").strip(),
        "date_from": request.args.get("date_from", "").strip(),
    }
    page, page_size = _parse_page_args(request.args)
    try:
        filtered = _build_filtered_logs(args)
        total = len(filtered)
    except Exception:
        logger.exception("获取操作日志失败")
        flash("加载操作日志失败", "error")
        filtered, total = [], 0

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    # 展示序号：全列表全局编号（1..total），跨页连续
    for i, log in enumerate(filtered, 1):
        log["display_id"] = i
    start = (page - 1) * page_size
    logs = filtered[start:start + page_size]

    return render_template("cards/logs.html",
                           logs=logs,
                           total=total,
                           page=page,
                           page_size=page_size,
                           total_pages=total_pages,
                           page_window=_build_page_window(page, total_pages),
                           page_size_options=PAGE_SIZE_OPTIONS,
                           filters=args,
                           operation_labels=OPERATION_LABELS,
                           target_type_labels=TARGET_TYPE_LABELS,
                           field_labels=FIELD_LABELS,
                           format_changes=_format_changes)


def _parse_page_args(args) -> tuple[int, int]:
    """解析页码与每页条数（非法值回落默认）"""
    page = 1
    if str(args.get("page", "")).isdigit():
        page = max(1, int(args["page"]))
    page_size = DEFAULT_PAGE_SIZE
    raw_ps = args.get("page_size", "")
    if str(raw_ps).isdigit() and int(raw_ps) in PAGE_SIZE_OPTIONS:
        page_size = int(raw_ps)
    return page, page_size


def _build_page_window(page: int, total_pages: int, window: int = 5) -> list:
    """生成分页按钮序列，None 表示省略号"""
    if total_pages <= 1:
        return [1]
    if total_pages <= window + 2:
        return list(range(1, total_pages + 1))
    pages = [1]
    start = max(2, page - window // 2)
    end = min(total_pages - 1, start + window - 1)
    start = max(2, end - window + 1)
    if start > 2:
        pages.append(None)
    pages.extend(range(start, end + 1))
    if end < total_pages - 1:
        pages.append(None)
    pages.append(total_pages)
    return pages


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
        count = service.delete_logs([int(log_id) for log_id in log_ids if log_id.isdigit()])
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
