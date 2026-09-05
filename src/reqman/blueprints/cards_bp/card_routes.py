"""工卡 CRUD 与作废工卡库 路由。"""

import logging

from flask import current_app, flash, redirect, render_template, request

from ...config import CATEGORIES, REMINDER_TYPES, TASK_TYPES, USAGE_TYPES
from ...services import amro_sync
from ...services.card_service import ServiceError
from ...utils.error_handlers import ValidationError, is_ajax
from ...utils.response import api_error, api_success
from ...utils.validators import validate_required
from . import cards_bp
from .helpers import _card_form_render_kwargs, _parse_and_validate_tools_mats, _parse_reminder, _parse_write_date

logger = logging.getLogger(__name__)


@cards_bp.route("/card/list")
def card_list():
    """工卡列表"""
    try:
        search = request.args.get("search", "").strip()
        category = request.args.get("category", "").strip()
        reminder_type = request.args.get("reminder_type", "").strip()
        cards = current_app.extensions['card_service'].list_cards(
            search=search, category=category, reminder_type=reminder_type)
        # 按「新建/编辑」日志时间倒序（空值排最后）
        cards.sort(key=lambda c: c.get("log_time", ""), reverse=True)
        sets = current_app.extensions['card_service'].list_card_sets()
        set_map = {set["id"]: set.get("name", "") for set in sets}
        for card in cards:
            set_id = card.get("set_id")
            card["set_name"] = set_map.get(set_id, "") if set_id else ""
        return render_template("cards/list.html",
                               cards=cards,
                               categories=CATEGORIES, task_types=TASK_TYPES,
                               reminder_types=REMINDER_TYPES,
                               amro_status=amro_sync.get_query_status("full_version"),
                               amro_last_query=amro_sync.get_last_query_result("full_version"))
    except Exception:
        logger.exception("获取工卡列表失败")
        flash("加载工卡列表失败，请稍后重试", "error")
        return render_template("cards/list.html", cards=[],
                               categories=CATEGORIES, task_types=TASK_TYPES,
                               reminder_types=REMINDER_TYPES, amro_status={},
                               amro_last_query=amro_sync.get_last_query_result("full_version"))


@cards_bp.route("/card/new", methods=["GET", "POST"])
def card_new():
    """新增工卡"""
    if request.method == "POST":
        try:
            task_code = validate_required(request.form, "task_code", "工卡号")

            task_name = validate_required(request.form, "task_name", "工卡名称")

            tools, materials, tools_confirmed, materials_confirmed, err = _parse_and_validate_tools_mats("/card/new")
            if err:
                return err
            reminder_type, reminder_confirmed, rerr = _parse_reminder()
            if rerr:
                return rerr
            current_app.extensions['card_service'].add_card(
                task_code=task_code,
                task_name=task_name,
                category=validate_required(request.form, "category", "专业"),
                task_type=request.form.get("task_type", ""),
                remark=request.form.get("remark", ""),
                tools=tools,
                materials=materials,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
                reminder_type=reminder_type,
                reminder_confirmed=reminder_confirmed,
                write_date=_parse_write_date(),
                card_ok=True,
            )
            if is_ajax():
                return api_success(message="工卡新增成功")
            flash("工卡新增成功", "success")
            return redirect("/card/list")

        except (ServiceError, ValidationError) as e:
            if is_ajax():
                return api_error(e.message, status_code=200, field=getattr(e, "field", None))
            flash(e.message, "error")
            return render_template("cards/form.html",
                                   **_card_form_render_kwargs(request.form, card=None, edit_mode=False))
        except Exception:
            logger.exception("新增工卡失败")
            if is_ajax():
                return api_error("服务器错误，请稍后重试", "SERVER_ERROR", 200)
            flash("服务器错误，请稍后重试", "error")
            return render_template("cards/form.html",
                                   **_card_form_render_kwargs(request.form, card=None, edit_mode=False))

    prefill_code = request.args.get("task_code", "")
    prefill_name = request.args.get("task_name", "")
    prefill_category = request.args.get("category", "")
    prefill_task_type = request.args.get("task_type", "")
    return render_template("cards/form.html",
                           card=None, tools=[], materials=[],
                           categories=CATEGORIES, task_types=TASK_TYPES,
                           usage_types=USAGE_TYPES, edit_mode=False,
                           prefill_code=prefill_code, prefill_name=prefill_name,
                           prefill_category=prefill_category, prefill_task_type=prefill_task_type,
                           reminder_types=REMINDER_TYPES)


@cards_bp.route("/card/<int:card_id>/edit", methods=["GET", "POST"])
def card_edit(card_id):
    """编辑工卡"""
    try:
        card = current_app.extensions['card_service'].get_card(card_id)
    except (ServiceError, KeyError):
        card = None

    if not card:
        flash("工卡不存在", "error")
        return redirect("/card/list")

    if request.method == "POST":
        try:
            task_name = validate_required(request.form, "task_name", "工卡名称")
            tools, materials, tools_confirmed, materials_confirmed, err = _parse_and_validate_tools_mats(f"/card/{card_id}/edit")
            if err:
                return err
            reminder_type, reminder_confirmed, rerr = _parse_reminder()
            if rerr:
                return rerr
            current_app.extensions['card_service'].update_card(
                card_id,
                task_code=request.form.get("task_code", card["task_code"]),
                task_name=task_name,
                category=validate_required(request.form, "category", "专业"),
                task_type=request.form.get("task_type", ""),
                remark=request.form.get("remark", ""),
                tools=tools,
                materials=materials,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
                reminder_type=reminder_type,
                reminder_confirmed=reminder_confirmed,
                write_date=_parse_write_date(),
                card_ok=True,
            )
            if is_ajax():
                return api_success(message="工卡更新成功")
            flash("工卡更新成功", "success")
            return redirect("/card/list")

        except (ServiceError, ValidationError) as e:
            if is_ajax():
                return api_error(e.message, status_code=200, field=getattr(e, "field", None))
            flash(e.message, "error")
            return render_template("cards/form.html",
                                   **_card_form_render_kwargs(request.form, card=card, edit_mode=True))
        except Exception:
            logger.exception("更新工卡失败")
            if is_ajax():
                return api_error("服务器错误", "SERVER_ERROR", 200)
            flash("服务器错误，请稍后重试", "error")
            return render_template("cards/form.html",
                                   **_card_form_render_kwargs(request.form, card=card, edit_mode=True))

    return render_template("cards/form.html",
                           card=card,
                           tools=card.get("tools", []),
                           materials=card.get("materials", []),
                           categories=CATEGORIES,
                           task_types=TASK_TYPES,
                           usage_types=USAGE_TYPES,
                           edit_mode=True,
                           prefill_code="", prefill_name="",
                           prefill_category="", prefill_task_type="",
                           reminder_types=REMINDER_TYPES)


@cards_bp.route("/card/<int:card_id>/delete", methods=["POST"])
def card_delete(card_id):
    """删除工卡"""
    try:
        current_app.extensions['card_service'].delete_card(card_id)
        if is_ajax():
            return api_success(message="工卡已删除")
        flash("工卡已删除", "success")
    except ServiceError as e:
        if is_ajax():
            return api_error(e.message, status_code=200)
        flash(e.message, "error")
    except Exception:
        logger.exception("删除工卡失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 200)
        flash("服务器错误", "error")
    return redirect("/card/list")


@cards_bp.route("/card/<int:card_id>")
def card_detail(card_id):
    """工卡详情 (AJAX)"""
    try:
        card = current_app.extensions['card_service'].get_card(card_id)
        if not card:
            return api_error("工卡不存在", "NOT_FOUND", 404)
        return api_success(data=card)
    except Exception:
        logger.exception("获取工卡详情失败")
        return api_error("服务器错误", "SERVER_ERROR", 500)


@cards_bp.route("/card/<int:card_id>/reset-confirm", methods=["POST"])
def card_reset_confirm(card_id):
    """重置确认：仅置 card_ok=False，不清空内容"""
    try:
        current_app.extensions['card_service'].update_card(card_id, card_ok=False)
        if is_ajax():
            return api_success(message="已重置确认状态", data={"card_ok": False})
        flash("已重置确认状态", "success")
    except ServiceError as e:
        if is_ajax():
            return api_error(e.message, status_code=200)
        flash(e.message, "error")
    return redirect("/card/list")


@cards_bp.route("/card/cancelled")
def cancelled_cards_page():
    """作废工卡清单（数据管理子页，只读归档：查看 + 彻底删除）"""
    records = current_app.extensions["cancelled_cards"].get_all()
    return render_template("cards/cancelled.html",
                           cards=records,
                           categories=CATEGORIES, reminder_types=REMINDER_TYPES,
                           task_types=TASK_TYPES)


@cards_bp.route("/card/cancelled/<int:card_id>/delete", methods=["POST"])
def cancelled_card_delete(card_id):
    """彻底删除作废工卡"""
    record = current_app.extensions["cancelled_cards"].remove(card_id)
    if record is None:
        if is_ajax():
            return api_error("作废工卡不存在", status_code=200)
        flash("作废工卡不存在", "error")
        return redirect("/card/cancelled")
    if is_ajax():
        return api_success(message=f"作废工卡 {record.get('task_code', '')} 已彻底删除")
    flash("作废工卡已彻底删除", "success")
    return redirect("/card/cancelled")


@cards_bp.route("/card/list-json")
def card_list_json():
    """工卡列表 JSON（供 set_form.html 搜索用）"""
    try:
        cards = current_app.extensions['card_service'].list_cards()
        return api_success(data=[{
            "id": c["id"],
            "task_code": c["task_code"],
            "task_name": c["task_name"],
            "category": c["category"],
        } for c in cards])
    except Exception:
        logger.exception("获取工卡列表 JSON 失败")
        return api_error("获取工卡列表失败", "SERVER_ERROR", 500)
