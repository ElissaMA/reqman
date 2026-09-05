"""工卡蓝图共享解析/校验辅助函数。"""

import logging
from datetime import datetime

from flask import current_app, flash, redirect, request

from ...config import CATEGORIES, REMINDER_TYPES, TASK_TYPES, USAGE_TYPES
from ...services.card_service import ServiceError
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


def _card_form_render_kwargs(form, card=None, edit_mode=False):
    """校验失败 re-render 时回填已填值，避免整张表单重填（A3）。

    - 新增：以提交值构造 card 字典，模板按 card.* 渲染。
    - 编辑：以原记录为底，覆盖用户已改字段。
    - 工具/航材：尽力从提交解析；半空行解析失败时降级为空（用户需重填该行）。
    """
    submitted = {
        "task_code": form.get("task_code", ""),
        "task_name": form.get("task_name", ""),
        "category": form.get("category", ""),
        "task_type": form.get("task_type", ""),
        "write_date": (form.get("write_date", "") or "")[:10],
        "reminder_type": form.get("reminder_type", ""),
        "reminder_confirmed": bool(form.get("reminder_type")) or bool(form.get("confirm_no_reminder")),
        "tools_confirmed": bool(form.get("confirm_no_tools")),
        "materials_confirmed": bool(form.get("confirm_no_mats")),
        "remark": form.get("remark", ""),
        "card_ok": bool(card and card.get("card_ok")) if card else False,
    }
    if edit_mode and card:
        merged = dict(card)
        merged.update(submitted)
        card_for_render = merged
    else:
        card_for_render = submitted

    tools, materials = [], []
    try:
        tools, materials = current_app.extensions['card_service'].parse_tools_mats(form)
    except ServiceError:
        tools, materials = [], []

    return {
        "card": card_for_render,
        "tools": tools,
        "materials": materials,
        "categories": CATEGORIES,
        "task_types": TASK_TYPES,
        "usage_types": USAGE_TYPES,
        "edit_mode": edit_mode,
        "prefill_code": "",
        "prefill_name": "",
        "prefill_category": "",
        "prefill_task_type": "",
        "reminder_types": REMINDER_TYPES,
    }


def _set_form_render_kwargs(form, set=None, edit_mode=False):
    """工卡组校验失败 re-render 回填（A3），结构与 _card_form_render_kwargs 一致。"""
    submitted = {
        "name": form.get("name", ""),
        "description": form.get("description", ""),
        "category": form.get("category", ""),
        "reminder_type": form.get("reminder_type", ""),
        "reminder_confirmed": bool(form.get("reminder_type")) or bool(form.get("confirm_no_reminder")),
        "tools_confirmed": bool(form.get("confirm_no_tools")),
        "materials_confirmed": bool(form.get("confirm_no_mats")),
        "card_ok": bool(set and set.get("card_ok")) if set else False,
    }
    if edit_mode and set:
        merged = dict(set)
        merged.update(submitted)
        set_for_render = merged
    else:
        set_for_render = submitted

    codes = form.getlist("card_codes[]")
    all_cards = current_app.extensions['card_service'].list_cards()
    code_map = {c["task_code"]: c.get("task_name", "") for c in all_cards}
    set_card_codes = [{"code": c, "name": code_map.get(c, "")} for c in codes]

    return {
        "set": set_for_render,
        "set_card_codes": set_card_codes,
        "categories": CATEGORIES,
        "usage_types": USAGE_TYPES,
        "reminder_types": REMINDER_TYPES,
    }


def _aircraft_form_render_kwargs(form, ac=None, edit_mode=False):
    """飞机信息校验失败 re-render 回填（A3）。"""
    submitted = {
        "reg": form.get("reg", ""),
        "model": form.get("model", ""),
        "engine": form.get("engine", ""),
        "fsn": form.get("fsn", ""),
        "msn": form.get("msn", ""),
        "apu": form.get("apu", ""),
    }
    if edit_mode and ac:
        merged = dict(ac)
        merged.update(submitted)
        ac_for_render = merged
    else:
        ac_for_render = submitted
    return {"ac": ac_for_render, "edit_mode": edit_mode}
