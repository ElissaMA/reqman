"""工卡组 路由。"""

import logging

from flask import current_app, flash, redirect, render_template, request

from ...config import CATEGORIES, REMINDER_TYPES, USAGE_TYPES
from ...services.card_service import ServiceError
from ...utils.error_handlers import ValidationError, is_ajax
from ...utils.response import api_error, api_success
from ...utils.validators import validate_required
from . import cards_bp
from .helpers import _parse_and_validate_tools_mats, _parse_reminder, _set_form_render_kwargs

logger = logging.getLogger(__name__)


@cards_bp.route("/card/sets")
def card_sets():
    """工卡组列表"""
    try:
        set_list = current_app.extensions['card_service'].list_card_sets_with_cards()
        card_counts = {}
        sets = []
        for set in set_list:
            cards = set.get("cards", [])
            card_counts[set["id"]] = len(cards)
            sets.append({
                "id": set["id"], "name": set["name"],
                "description": set.get("description", ""),
                "category": set.get("category", ""),
                "tools": set.get("tools", []),
                "materials": set.get("materials", []),
                "tools_confirmed": set.get("tools_confirmed", False),
                "materials_confirmed": set.get("materials_confirmed", False),
                "reminder_type": set.get("reminder_type", ""),
                "card_ok": set.get("card_ok", False),
                "reminder_confirmed": set.get("reminder_confirmed", False),
                "cards": [{"task_code": cd["task_code"],
                            "task_name": cd.get("task_name", "")}
                           for cd in cards]
            })
        # 按「新建/编辑」日志时间倒序（空值排最后），同名按名称升序
        sets.sort(key=lambda s: s.get("name", ""))
        sets.sort(key=lambda s: s.get("log_time", ""), reverse=True)
        return render_template("cards/sets.html", sets=sets,
                               card_counts=card_counts,
                               categories=CATEGORIES,
                               reminder_types=REMINDER_TYPES)
    except Exception:
        logger.exception("获取工卡组列表失败")
        flash("加载失败", "error")
        return render_template("cards/sets.html", sets=[],
                               card_counts={},
                               reminder_types=REMINDER_TYPES)


@cards_bp.route("/card/sets/new", methods=["GET", "POST"])
def card_set_new():
    """新增工卡组"""
    if request.method == "POST":
        try:
            category = validate_required(request.form, "category", "专业")
            card_codes = request.form.getlist("card_codes[]")
            if len(card_codes) < 2:
                msg = "工卡组至少需要2个工卡"
                if is_ajax():
                    return api_error(msg, status_code=200)
                flash(msg, "error")
                return redirect("/card/sets/new")
            tools, materials, tools_confirmed, materials_confirmed, err = _parse_and_validate_tools_mats("/card/sets/new")
            if err:
                return err
            reminder_type, reminder_confirmed, rerr = _parse_reminder()
            if rerr:
                return rerr
            current_app.extensions['card_service'].add_card_set(
                name=request.form.get("name", ""),
                description=request.form.get("description", ""),
                category=category,
                card_codes=card_codes,
                tools=tools,
                materials=materials,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
                reminder_type=reminder_type,
                reminder_confirmed=reminder_confirmed,
                card_ok=True,
            )
            if is_ajax():
                return api_success(message="工卡组新增成功")
            flash("工卡组新增成功，工具/航材已同步至所有子工卡", "success")
            return redirect("/card/sets")
        except (ServiceError, ValidationError) as e:
            if is_ajax():
                return api_error(e.message, status_code=200, field=getattr(e, "field", None))
            flash(e.message, "error")
            return render_template("cards/set_form.html",
                                   **_set_form_render_kwargs(request.form, set=None, edit_mode=False))
        except Exception:
            logger.exception("新增工卡组失败")
            if is_ajax():
                return api_error("服务器错误", "SERVER_ERROR", 200)
            flash("服务器错误", "error")
            return render_template("cards/set_form.html",
                                   **_set_form_render_kwargs(request.form, set=None, edit_mode=False))

    return render_template("cards/set_form.html",
                           set=None,
                           set_card_codes=[],
                           categories=CATEGORIES,
                           usage_types=USAGE_TYPES,
                           reminder_types=REMINDER_TYPES)


@cards_bp.route("/card/sets/<int:set_id>/edit", methods=["GET", "POST"])
def card_set_edit(set_id):
    """编辑工卡组"""
    try:
        set = current_app.extensions['card_service'].get_card_set(set_id)
    except (ServiceError, KeyError):
        set = None

    if not set:
        flash("工卡组不存在", "error")
        return redirect("/card/sets")

    if request.method == "POST":
        try:
            category = validate_required(request.form, "category", "专业")
            card_codes = request.form.getlist("card_codes[]")
            if len(card_codes) < 2:
                msg = "工卡组至少需要2个工卡"
                if is_ajax():
                    return api_error(msg, status_code=200)
                flash(msg, "error")
                return redirect(f"/card/sets/{set_id}/edit")
            tools, materials, tools_confirmed, materials_confirmed, err = _parse_and_validate_tools_mats(f"/card/sets/{set_id}/edit")
            if err:
                return err
            reminder_type, reminder_confirmed, rerr = _parse_reminder()
            if rerr:
                return rerr
            current_app.extensions['card_service'].update_card_set(
                set_id,
                name=request.form.get("name", set.get("name", "")),
                description=request.form.get("description", ""),
                category=category,
                card_codes=card_codes,
                tools=tools,
                materials=materials,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
                reminder_type=reminder_type,
                reminder_confirmed=reminder_confirmed,
                card_ok=True,
            )
            if is_ajax():
                return api_success(message="工卡组更新成功")
            flash("工卡组更新成功，工具/航材已同步至所有子工卡", "success")
            return redirect("/card/sets")
        except (ServiceError, ValidationError) as e:
            if is_ajax():
                return api_error(e.message, status_code=200, field=getattr(e, "field", None))
            flash(e.message, "error")
            return render_template("cards/set_form.html",
                                   **_set_form_render_kwargs(request.form, set=set, edit_mode=True))
        except Exception:
            logger.exception("更新工卡组失败")
            if is_ajax():
                return api_error("服务器错误", "SERVER_ERROR", 200)
            flash("服务器错误", "error")
            return render_template("cards/set_form.html",
                                   **_set_form_render_kwargs(request.form, set=set, edit_mode=True))

    cards_in_set = current_app.extensions['card_service'].get_cards_in_set(set_id)
    set_card_codes = [{"code": c["task_code"], "name": c.get("task_name", "")} for c in cards_in_set]
    return render_template("cards/set_form.html",
                           set=set,
                           set_card_codes=set_card_codes,
                           categories=CATEGORIES,
                           usage_types=USAGE_TYPES,
                           reminder_types=REMINDER_TYPES)


@cards_bp.route("/card/sets/<int:set_id>")
def card_set_detail(set_id):
    """工卡组详情 (AJAX)"""
    try:
        card_set = current_app.extensions['card_service'].get_card_set(set_id)
        if not card_set:
            return api_error("工卡组不存在", "NOT_FOUND", 404)
        cards_in_set = current_app.extensions['card_service'].get_cards_in_set(set_id)
        card_set["cards"] = [{"task_code": c["task_code"], "task_name": c.get("task_name", "")}
                             for c in cards_in_set]
        return api_success(data=card_set)
    except Exception:
        logger.exception("获取工卡组详情失败")
        return api_error("服务器错误", "SERVER_ERROR", 500)


@cards_bp.route("/card/sets/<int:set_id>/delete", methods=["POST"])
def card_set_delete(set_id):
    """删除工卡组"""
    try:
        current_app.extensions['card_service'].delete_card_set(set_id)
        if is_ajax():
            return api_success(message="工卡组已删除")
        flash("工卡组已删除，关联工卡已解除绑定", "success")
    except ServiceError as e:
        if is_ajax():
            return api_error(e.message, status_code=200)
        flash(e.message, "error")
    except Exception:
        logger.exception("删除工卡组失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 200)
        flash("服务器错误", "error")
    return redirect("/card/sets")


@cards_bp.route("/card/sets/<int:set_id>/reset-confirm", methods=["POST"])
def card_set_reset_confirm(set_id):
    """重置确认：仅置 card_ok=False，不清空内容"""
    try:
        current_app.extensions['card_service'].update_card_set(set_id, card_ok=False)
        if is_ajax():
            return api_success(message="已重置确认状态", data={"card_ok": False})
        flash("已重置确认状态", "success")
    except ServiceError as e:
        if is_ajax():
            return api_error(e.message, status_code=200)
        flash(e.message, "error")
    return redirect("/card/sets")
