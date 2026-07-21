"""工卡管理蓝图 — 工卡 CRUD + 工卡组管理"""

import logging
from flask import (Blueprint, current_app, render_template, request, redirect,
                   url_for, flash)

from ..services.card_service import ServiceError
from ..utils.response import api_success, api_error, ApiException
from ..utils.error_handlers import ValidationError, NotFoundError
from ..utils.validators import (validate_required_fields, validate_tools_mats)
from ..config import CATEGORIES, TASK_TYPES, USAGE_TYPES

logger = logging.getLogger(__name__)

cards_bp = Blueprint("cards", __name__)


# ======================== 辅助函数 ========================

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_tools_mats():
    """解析并验证工具/航材，失败时抛出 ValidationError"""
    tools, mats = current_app.extensions['card_service'].parse_tools_mats(request.form)
    tools_confirmed = (not tools) and bool(request.form.get("confirm_no_tools"))
    materials_confirmed = (not mats) and bool(request.form.get("confirm_no_mats"))
    validate_tools_mats(tools, mats, tools_confirmed, materials_confirmed)
    return tools, mats, tools_confirmed, materials_confirmed


def _handle_ajax_or_redirect(success_msg, redirect_url, fallback_redirect=None):
    """根据请求类型返回 AJAX 响应或重定向"""
    if _is_ajax():
        return api_success(message=success_msg)
    flash(success_msg, "success")
    return redirect(fallback_redirect or redirect_url)


def _handle_error_ajax_or_flash(message, redirect_url, error_category="error"):
    """统一处理错误响应"""
    if _is_ajax():
        return api_error(message=message, error_code="REQUEST_ERROR")
    flash(message, error_category)
    return redirect(redirect_url)


# ======================== 工卡 ========================

@cards_bp.route("/card/list")
def card_list():
    """工卡列表"""
    try:
        search = request.args.get("search", "").strip()
        category = request.args.get("category", "").strip()
        items = current_app.extensions['card_service'].list_cards(search=search, category=category)
        all_sets = current_app.extensions['card_service'].list_card_sets()
        set_map = {s["id"]: s.get("name", "") for s in all_sets}
        for item in items:
            sid = item.get("set_id")
            item["set_name"] = set_map.get(sid, "") if sid else ""
        return render_template("cards/list.html",
                               items=items,
                               search=search,
                               category=category,
                               categories=CATEGORIES)
    except Exception as e:
        logger.exception("获取工卡列表失败")
        flash("加载工卡列表失败，请稍后重试", "error")
        return render_template("cards/list.html", items=[],
                               search="", category="",
                               categories=CATEGORIES)


@cards_bp.route("/card/new", methods=["GET", "POST"])
def card_new():
    """新增工卡"""
    if request.method == "POST":
        try:
            task_code = validate_required_fields(
                request.form, "task_code",
                labels={"task_code": "工卡号"}
            )
            tools, mats, tools_confirmed, materials_confirmed = _parse_tools_mats()

            current_app.extensions['card_service'].add_card(
                task_code=task_code,
                task_name=request.form.get("task_name", ""),
                category=request.form.get("category", "机体"),
                task_type=request.form.get("task_type", ""),
                remark=request.form.get("remark", ""),
                tools=tools,
                materials=mats,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
            )
            return _handle_ajax_or_redirect("工卡新增成功", "/card/list")

        except (ValidationError, ServiceError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            if _is_ajax():
                return api_error(message=msg, error_code=getattr(e, 'error_code', 'VALIDATION_ERROR'))
            flash(msg, "error")
            return redirect("/card/new")
        except Exception as e:
            logger.exception("新增工卡失败")
            return _handle_error_ajax_or_flash("服务器错误，请稍后重试", "/card/new")

    prefill_code = request.args.get("task_code", "")
    prefill_name = request.args.get("task_name", "")
    prefill_category = request.args.get("category", "")
    prefill_task_type = request.args.get("task_type", "")
    return render_template("cards/form.html",
                           item=None, tools=[], materials=[],
                           categories=CATEGORIES, task_types=TASK_TYPES,
                           usage_types=USAGE_TYPES, edit_mode=False,
                           prefill_code=prefill_code, prefill_name=prefill_name,
                           prefill_category=prefill_category, prefill_task_type=prefill_task_type)


@cards_bp.route("/card/<int:card_id>/edit", methods=["GET", "POST"])
def card_edit(card_id):
    """编辑工卡"""
    try:
        item = current_app.extensions['card_service'].get_card(card_id)
    except Exception:
        item = None

    if not item:
        flash("工卡不存在", "error")
        return redirect("/card/list")

    if request.method == "POST":
        try:
            tools, mats, tools_confirmed, materials_confirmed = _parse_tools_mats()

            current_app.extensions['card_service'].update_card(
                card_id,
                task_code=request.form.get("task_code", item["task_code"]),
                task_name=request.form.get("task_name", ""),
                category=request.form.get("category", "机体"),
                task_type=request.form.get("task_type", ""),
                remark=request.form.get("remark", ""),
                tools=tools,
                materials=mats,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
            )
            return _handle_ajax_or_redirect("工卡更新成功", "/card/list")

        except (ValidationError, ServiceError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            if _is_ajax():
                return api_error(message=msg, error_code=getattr(e, 'error_code', 'VALIDATION_ERROR'))
            flash(msg, "error")
        except Exception as e:
            logger.exception("更新工卡失败")
            if _is_ajax():
                return api_error(message="服务器错误", error_code="SERVER_ERROR")
            flash("服务器错误，请稍后重试", "error")

    return render_template("cards/form.html",
                           item=item,
                           tools=item.get("tools", []),
                           materials=item.get("materials", []),
                           categories=CATEGORIES,
                           task_types=TASK_TYPES,
                           usage_types=USAGE_TYPES,
                           edit_mode=True,
                           prefill_code="", prefill_name="")


@cards_bp.route("/card/<int:card_id>/delete", methods=["POST"])
def card_delete(card_id):
    """删除工卡"""
    try:
        current_app.extensions['card_service'].delete_card(card_id)
        return _handle_ajax_or_redirect("工卡已删除", "/card/list")
    except ServiceError as e:
        return _handle_error_ajax_or_flash(e.message, "/card/list")
    except Exception as e:
        logger.exception("删除工卡失败")
        return _handle_error_ajax_or_flash("服务器错误", "/card/list")


@cards_bp.route("/card/<int:card_id>")
def card_detail(card_id):
    """工卡详情 (AJAX)"""
    try:
        item = current_app.extensions['card_service'].get_card(card_id)
        if not item:
            return api_error(message="���卡不存在", error_code="NOT_FOUND", status_code=404)
        return api_success(data=item)
    except Exception as e:
        logger.exception("获取工卡详情失败")
        return api_error(message="服务器错误", error_code="SERVER_ERROR", status_code=500)


@cards_bp.route("/card/list-json")
def card_list_json():
    """工卡列表 JSON（供 set_form.html 搜索用）"""
    try:
        items = current_app.extensions['card_service'].list_cards()
        data = [{
            "id": c["id"],
            "task_code": c["task_code"],
            "task_name": c["task_name"],
            "category": c["category"],
        } for c in items]
        return api_success(data=data)
    except Exception as e:
        logger.exception("获取工卡列表 JSON 失败")
        return api_success(data=[])


@cards_bp.route("/card/api/list")
def card_api_list():
    """工卡列表 AJAX API（支持分页+搜索+分类）"""
    try:
        search = request.args.get("search", "").strip()
        category = request.args.get("category", "").strip()
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        per_page = min(per_page, 100)  # 上限保护

        items = current_app.extensions['card_service'].list_cards(search=search, category=category)
        all_sets = current_app.extensions['card_service'].list_card_sets()
        set_map = {s["id"]: s.get("name", "") for s in all_sets}

        for item in items:
            sid = item.get("set_id")
            item["set_name"] = set_map.get(sid, "") if sid else ""

        total = len(items)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        start = (page - 1) * per_page
        end = start + per_page
        page_items = items[start:end]

        return api_success(data={
            "items": page_items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
            }
        })
    except Exception as e:
        logger.exception("AJAX 获取工卡列表失败")
        return api_error(message="获取工卡列表失败", error_code="SERVER_ERROR", status_code=500)


# ======================== 工卡组 ========================

@cards_bp.route("/card/sets")
def card_sets():
    """工卡组列表"""
    try:
        sets = current_app.extensions['card_service'].list_card_sets()
        card_counts = {}
        set_data = []
        for s in sets:
            cards = current_app.extensions['card_service'].get_cards_in_set(s["id"])
            card_counts[s["id"]] = len(cards)
            set_data.append({
                "id": s["id"], "name": s["name"],
                "description": s.get("description", ""),
                "category": s.get("category", ""),
                "tools": s.get("tools", []),
                "materials": s.get("materials", []),
                "tools_confirmed": s.get("tools_confirmed", False),
                "materials_confirmed": s.get("materials_confirmed", False),
                "cards": [{"task_code": cd["task_code"],
                            "task_name": cd.get("task_name", "")}
                           for cd in cards]
            })
        return render_template("cards/sets.html", sets=sets,
                               card_counts=card_counts, set_data=set_data)
    except Exception as e:
        logger.exception("获取工卡组列表失败")
        flash("加载失败", "error")
        return render_template("cards/sets.html", sets=[],
                               card_counts={}, set_data=[])


@cards_bp.route("/card/sets/new", methods=["GET", "POST"])
def card_set_new():
    """新增工卡组"""
    if request.method == "POST":
        try:
            validate_required_fields(
                request.form, "name",
                labels={"name": "工卡组名称"}
            )
            tools, mats, tools_confirmed, materials_confirmed = _parse_tools_mats()
            card_codes = request.form.getlist("card_codes[]")

            current_app.extensions['card_service'].add_card_set(
                name=request.form.get("name", ""),
                description=request.form.get("description", ""),
                category=request.form.get("category", "机体"),
                card_codes=card_codes,
                tools=tools,
                materials=mats,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
            )
            return _handle_ajax_or_redirect(
                "工卡组新增成功，工具/航材已同步至所有子工卡",
                "/card/sets"
            )
        except (ValidationError, ServiceError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            if _is_ajax():
                return api_error(message=msg, error_code=getattr(e, 'error_code', 'VALIDATION_ERROR'))
            flash(msg, "error")
        except Exception as e:
            logger.exception("新增工卡组失败")
            if _is_ajax():
                return api_error(message="服务器错误", error_code="SERVER_ERROR")
            flash("服务器错误", "error")

    all_cards = current_app.extensions['card_service'].list_cards()
    return render_template("cards/set_form.html",
                           set_item=None,
                           set_card_codes=[],
                           all_cards=all_cards,
                           categories=CATEGORIES,
                           usage_types=USAGE_TYPES)


@cards_bp.route("/card/sets/<int:set_id>/edit", methods=["GET", "POST"])
def card_set_edit(set_id):
    """编辑工卡组"""
    try:
        s = current_app.extensions['card_service'].get_card_set(set_id)
    except Exception:
        s = None

    if not s:
        flash("工卡组不存在", "error")
        return redirect("/card/sets")

    if request.method == "POST":
        try:
            tools, mats, tools_confirmed, materials_confirmed = _parse_tools_mats()
            card_codes = request.form.getlist("card_codes[]")

            current_app.extensions['card_service'].update_card_set(
                set_id,
                name=request.form.get("name", s.get("name", "")),
                description=request.form.get("description", ""),
                category=request.form.get("category", s.get("category", "机体")),
                card_codes=card_codes,
                tools=tools,
                materials=mats,
                tools_confirmed=tools_confirmed,
                materials_confirmed=materials_confirmed,
            )
            return _handle_ajax_or_redirect(
                "工卡组更新成功，工具/航材已同步至所有子工卡",
                "/card/sets"
            )
        except (ValidationError, ServiceError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            if _is_ajax():
                return api_error(message=msg, error_code=getattr(e, 'error_code', 'VALIDATION_ERROR'))
            flash(msg, "error")
        except Exception as e:
            logger.exception("更新工卡组失败")
            if _is_ajax():
                return api_error(message="服务器错误", error_code="SERVER_ERROR")
            flash("服务器错误", "error")

    all_cards = current_app.extensions['card_service'].list_cards()
    cards_in_set = current_app.extensions['card_service'].get_cards_in_set(set_id)
    set_card_codes = [c["task_code"] for c in cards_in_set]
    return render_template("cards/set_form.html",
                           set_item=s,
                           all_cards=all_cards,
                           set_card_codes=set_card_codes,
                           categories=CATEGORIES,
                           usage_types=USAGE_TYPES)


@cards_bp.route("/card/sets/<int:set_id>/delete", methods=["POST"])
def card_set_delete(set_id):
    """删除工卡组"""
    try:
        current_app.extensions['card_service'].delete_card_set(set_id)
        return _handle_ajax_or_redirect("工卡组已删除，关联工卡已解除绑定", "/card/sets")
    except ServiceError as e:
        return _handle_error_ajax_or_flash(e.message, "/card/sets")
    except Exception as e:
        logger.exception("删除工卡组失��")
        return _handle_error_ajax_or_flash("服务器错误", "/card/sets")


# ======================== 飞机信息 ========================

@cards_bp.route("/card/aircraft")
def aircraft_list():
    """飞机信息列表"""
    try:
        aircraft_list = current_app.extensions['card_service'].list_aircraft()
        return render_template("cards/aircraft.html",
                               aircraft_list=aircraft_list)
    except Exception as e:
        logger.exception("获取飞机信息列表失败")
        flash("加载飞机信息失败", "error")
        return render_template("cards/aircraft.html",
                               aircraft_list=[])


@cards_bp.route("/card/aircraft/new", methods=["GET", "POST"])
def aircraft_new():
    """新增飞机"""
    if request.method == "POST":
        try:
            reg = validate_required_fields(
                request.form, "reg",
                labels={"reg": "机号"}
            )
            current_app.extensions['card_service'].add_aircraft(
                reg=reg,
                model=request.form.get("model", ""),
                engine=request.form.get("engine", ""),
                fsn=request.form.get("fsn", ""),
                msn=request.form.get("msn", ""),
                apu=request.form.get("apu", ""),
            )
            flash("飞机信息新增成功", "success")
            return redirect("/card/aircraft")

        except (ValidationError, ServiceError) as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            flash(msg, "error")
        except Exception as e:
            logger.exception("新增飞机信息失败")
            flash("服务器错误", "error")

    return redirect("/card/aircraft")


@cards_bp.route("/card/aircraft/<int:aircraft_id>/edit", methods=["GET", "POST"])
def aircraft_edit(aircraft_id):
    """编辑飞机信息"""
    try:
        ac = current_app.extensions['card_service'].get_aircraft(aircraft_id)
    except Exception:
        ac = None

    if not ac:
        flash("飞机信息不存在", "error")
        return redirect("/card/aircraft")

    if request.method == "POST":
        try:
            current_app.extensions['card_service'].update_aircraft(
                aircraft_id,
                reg=request.form.get("reg", ac.get("reg", "")),
                model=request.form.get("model", ""),
                engine=request.form.get("engine", ""),
                fsn=request.form.get("fsn", ""),
                msn=request.form.get("msn", ""),
                apu=request.form.get("apu", ""),
            )
            flash("飞机信息更新成功", "success")
            return redirect("/card/aircraft")

        except ServiceError as e:
            flash(e.message, "error")
        except Exception as e:
            logger.exception("更新飞机信息失败")
            flash("服务器错误", "error")

    return redirect("/card/aircraft")


@cards_bp.route("/card/aircraft/<int:aircraft_id>/delete", methods=["POST"])
def aircraft_delete(aircraft_id):
    """删除飞机信息"""
    try:
        current_app.extensions['card_service'].delete_aircraft(aircraft_id)
        flash("飞机信息已删除", "success")
    except ServiceError as e:
        flash(e.message, "error")
    except Exception as e:
        logger.exception("删除飞机信息失败")
        flash("服��器错误", "error")
    return redirect("/card/aircraft")
