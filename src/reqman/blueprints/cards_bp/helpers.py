"""工卡蓝图共享解析/校验辅助函数。"""

import logging
from datetime import datetime

from flask import current_app, flash, redirect, request

from ...utils.error_handlers import ValidationError, is_ajax
from ...utils.response import api_error

logger = logging.getLogger(__name__)


def _parse_and_validate_tools_mats(redirect_url):
    """解析并验证工具/航材，失败时返回 (None, None, None, None, error_response)。"""
    tools, materials = current_app.extensions['card_service'].parse_tools_mats(request.form)
    tools_confirmed = bool(tools) or (not tools and bool(request.form.get("confirm_no_tools")))
    materials_confirmed = bool(materials) or (not materials and bool(request.form.get("confirm_no_mats")))

    if not tools and not tools_confirmed:
        msg = "请添加工具或确认无工具"
        if is_ajax():
            return None, None, None, None, api_error(msg, status_code=200)
        flash(msg, "error")
        return None, None, None, None, redirect(redirect_url)
    if not materials and not materials_confirmed:
        msg = "请添加航材或确认无航材"
        if is_ajax():
            return None, None, None, None, api_error(msg, status_code=200)
        flash(msg, "error")
        return None, None, None, None, redirect(redirect_url)

    return tools, materials, tools_confirmed, materials_confirmed, None


def _parse_reminder():
    """解析提醒字段并校验：提醒类型非空 或 确认无需提醒。"""
    reminder_type = request.form.get("reminder_type", "").strip()
    reminder_confirmed = bool(reminder_type) or (not reminder_type and bool(request.form.get("confirm_no_reminder")))
    if not reminder_type and not reminder_confirmed:
        msg = "请选择提醒类型或确认无需提醒"
        if is_ajax():
            return None, None, api_error(msg, status_code=200)
        flash(msg, "error")
        return None, None, redirect(request.referrer or "/card/list")
    return reminder_type, reminder_confirmed, None


def _parse_write_date() -> str:
    """编写日期（date 输入 → YYYY-MM-DD；留空返回空串）。"""
    v = (request.form.get("write_date") or "").strip()
    if not v:
        return ""
    try:
        return datetime.fromisoformat(v).date().isoformat()
    except ValueError as e:
        raise ValidationError("编写日期格式不正确，应为 YYYY-MM-DD", "write_date") from e
