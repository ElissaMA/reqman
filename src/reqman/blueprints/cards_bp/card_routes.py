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
        # 版本检查待人工确认作废清单（仍在用的卡才显示，确认后自动消失）
        active_codes = {c.get("task_code", "") for c in cards}
        pending_cancelled = amro_sync.pending_cancel_confirmations("full_version", active_codes)
        return render_template("cards/list.html",
                               cards=cards,
                               categories=CATEGORIES, task_types=TASK_TYPES,
                               reminder_types=REMINDER_TYPES,
                               amro_status=amro_sync.get_query_status("full_version"),
                               amro_last_query=amro_sync.get_last_query_result("full_version"),
                               pending_cancelled=pending_cancelled)
    except Exception:
        logger.exception("获取工卡列表失败")
        flash("加载工卡列表失败，请稍后重试", "error")
        return render_template("cards/list.html", cards=[],
                               categories=CATEGORIES, task_types=TASK_TYPES,
                               reminder_types=REMINDER_TYPES, amro_status={},
                               amro_last_query=amro_sync.get_last_query_result("full_version"),
                               pending_cancelled=[])


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


@cards_bp.route("/card/reference-search")
def card_reference_search():
    """搜索可引用工卡摘要（只返回工卡信息，不返回工具/航材明细）。"""
    query = request.args.get("q", "").strip()
    if not query:
        return api_error("请输入工卡号或工卡名称", "MISSING_QUERY", 400)
    exclude_id = request.args.get("exclude_id", "").strip()
    try:
        excluded = int(exclude_id) if exclude_id else None
    except ValueError:
        return api_error("当前工卡编号无效", "INVALID_EXCLUDE_ID", 400)
    cards = current_app.extensions['card_service'].list_cards(search=query)
    if excluded is not None:
        cards = [card for card in cards if card.get("id") != excluded]
    cards = cards[:30]
    return api_success(data=[{
        "id": card["id"],
        "task_code": card.get("task_code", ""),
        "task_name": card.get("task_name", ""),
        "category": card.get("category", ""),
        "task_type": card.get("task_type", ""),
        "tools_count": len(card.get("tools", [])),
        "materials_count": len(card.get("materials", [])),
    } for card in cards])


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
    """作废工卡清单（数据管理子页：编辑 / 恢复 / 彻底删除）。"""
    records = [c for c in current_app.extensions['card_service'].list_cards(
        include_cancelled=True) if c.get("cancelled")]
    return render_template("cards/cancelled.html",
                           cards=records,
                           categories=CATEGORIES, reminder_types=REMINDER_TYPES,
                           task_types=TASK_TYPES, usage_types=USAGE_TYPES)


@cards_bp.route("/card/cancelled/<int:card_id>/delete", methods=["POST"])
def cancelled_card_delete(card_id):
    """彻底删除作废工卡（仅允许删除已作废的卡）"""
    card = current_app.extensions['card_service'].get_card(card_id)
    if card is None or not card.get("cancelled"):
        if is_ajax():
            return api_error("作废工卡不存在", status_code=404)
        flash("作废工卡不存在", "error")
        return redirect("/card/cancelled")
    current_app.extensions['card_service'].delete_card(card_id)
    if is_ajax():
        return api_success(message=f"作废工卡 {card.get('task_code', '')} 已彻底删除")
    flash("作废工卡已彻底删除", "success")
    return redirect("/card/cancelled")


@cards_bp.route("/card/cancelled/confirm", methods=["POST"])
def cancelled_cards_confirm():
    """人工确认作废：批量标记 cancelled=True（版本检查报告确认入口）"""
    task_codes = request.form.getlist("task_codes[]") or request.form.getlist("task_codes")
    source = request.form.get("source", "manual").strip() or "manual"
    if not task_codes:
        if is_ajax():
            return api_error("未选择待作废工卡", status_code=400)
        flash("未选择待作废工卡", "error")
        return redirect("/card/cancelled")
    service = current_app.extensions['card_service']
    confirmed, missing = [], []
    for code in task_codes:
        code = str(code).strip()
        card = service.store.find_by_code(code) if code else None
        if card is None:
            missing.append(code)
            continue
        if card.get("cancelled"):
            continue   # 已作废，幂等跳过
        set_name = ""
        if card.get("set_id"):
            set_data = service.store.get_set(card["set_id"])
            set_name = set_data.get("name", "") if set_data else ""
        try:
            service.store.mark_cancelled(
                card["id"], source=source, set_name=set_name)
            confirmed.append(code)
        except ValueError:
            missing.append(code)
    message = f"已确认作废 {len(confirmed)} 张工卡"
    if missing:
        message += f"；{len(missing)} 张未找到或无法作废"
    if is_ajax():
        return api_success(message=message, data={
            "confirmed": confirmed, "missing": missing})
    flash(message, "success" if confirmed else "error")
    return redirect("/card/cancelled")


@cards_bp.route("/card/cancelled/<int:card_id>/update", methods=["POST"])
def cancelled_card_update(card_id):
    """编辑作废工卡（弹窗内保存，仍保留作废标记）。

    工具/航材解析沿用主库清洗规则，但不强制"至少有内容或确认无"——
    作废卡允许清空清单；确认状态直接取弹窗勾选。
    """
    service = current_app.extensions['card_service']
    card = service.get_card(card_id)
    if card is None or not card.get("cancelled"):
        if is_ajax():
            return api_error("作废工卡不存在", status_code=404)
        flash("作废工卡不存在", "error")
        return redirect("/card/cancelled")
    if not request.form.get("task_code", "").strip():
        if is_ajax():
            return api_error("工卡号不能为空", status_code=400)
        flash("工卡号不能为空", "error")
        return redirect("/card/cancelled")
    if not request.form.get("task_name", "").strip():
        if is_ajax():
            return api_error("工卡名称不能为空", status_code=400)
        flash("工卡名称不能为空", "error")
        return redirect("/card/cancelled")
    if not request.form.get("category", "").strip():
        if is_ajax():
            return api_error("专业不能为空", status_code=400)
        flash("专业不能为空", "error")
        return redirect("/card/cancelled")
    tools, materials = service.parse_tools_mats(request.form)
    fields = {
        "task_code": request.form.get("task_code", "").strip(),
        "task_name": request.form.get("task_name", "").strip(),
        "category": request.form.get("category", ""),
        "task_type": request.form.get("task_type", ""),
        "remark": request.form.get("remark", ""),
        "tools": tools,
        "materials": materials,
        "tools_confirmed": bool(request.form.get("tools_confirmed")),
        "materials_confirmed": bool(request.form.get("materials_confirmed")),
        "reminder_type": request.form.get("reminder_type", "").strip(),
        "reminder_confirmed": bool(request.form.get("reminder_confirmed")),
        "write_date": request.form.get("write_date", "").strip(),
    }
    try:
        record = service.update_card(card_id, **fields)
    except ServiceError as e:
        if is_ajax():
            return api_error(e.message, status_code=400)
        flash(e.message, "error")
        return redirect("/card/cancelled")
    except Exception:
        logger.exception("编辑作废工卡失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 500)
        flash("服务器错误", "error")
        return redirect("/card/cancelled")
    if is_ajax():
        return api_success(message="作废工卡已更新", data={
            "id": record["id"], "task_code": record.get("task_code", "")})
    flash("作废工卡已更新", "success")
    return redirect("/card/cancelled")


@cards_bp.route("/card/cancelled/<int:card_id>/restore", methods=["POST"])
def cancelled_card_restore(card_id):
    """恢复作废工卡：同 id 保留，cancelled=False，card_ok=False 待复核。"""
    service = current_app.extensions['card_service']
    try:
        restored = service.store.restore_cancelled(card_id)
    except ValueError as e:
        if is_ajax():
            return api_error(str(e), status_code=404)
        flash(str(e), "error")
        return redirect("/card/cancelled")
    except Exception:
        logger.exception("恢复作废工卡失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 500)
        flash("服务器错误", "error")
        return redirect("/card/cancelled")
    message = f"工卡 {restored.get('task_code', '')} 已恢复，请复核确认状态"
    if is_ajax():
        return api_success(message=message, data={"card_id": restored["id"]})
    flash(message, "success")
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
