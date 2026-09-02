"""工卡管理蓝图 — 工卡 CRUD + 工卡组管理"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file

from ..config import CATEGORIES, OUTPUT_DIR, REMINDER_TYPES, TASK_TYPES, USAGE_TYPES
from ..services import amro_sync
from ..services.card_service import ServiceError
from ..utils.error_handlers import ValidationError
from ..utils.validators import validate_required
from .inventory_bp import MESSAGES

logger = logging.getLogger(__name__)

cards_bp = Blueprint("cards", __name__)


# ======================== 工卡 ========================

@cards_bp.route("/card/list")
def card_list():
    """工卡列表"""
    try:
        search = request.args.get("search", "").strip()
        category = request.args.get("category", "").strip()
        reminder_type = request.args.get("reminder_type", "").strip()
        cards = current_app.extensions['card_service'].list_cards(
            search=search, category=category, reminder_type=reminder_type)
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
                               reminder_types=REMINDER_TYPES, amro_status={},
                               amro_last_query=amro_sync.get_last_query_result("full_version"))


def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_and_validate_tools_mats(redirect_url):
    """解析并验证工具/航材，失败时返回 (None, None, None, None, error_response)。"""
    tools, materials = current_app.extensions['card_service'].parse_tools_mats(request.form)
    tools_confirmed = bool(tools) or (not tools and bool(request.form.get("confirm_no_tools")))
    materials_confirmed = bool(materials) or (not materials and bool(request.form.get("confirm_no_mats")))

    if not tools and not tools_confirmed:
        msg = "请添加工具或确认无工具"
        if _is_ajax():
            return None, None, None, None, jsonify({"success": False, "message": msg})
        flash(msg, "error")
        return None, None, None, None, redirect(redirect_url)
    if not materials and not materials_confirmed:
        msg = "请添加航材或确认无航材"
        if _is_ajax():
            return None, None, None, None, jsonify({"success": False, "message": msg})
        flash(msg, "error")
        return None, None, None, None, redirect(redirect_url)

    return tools, materials, tools_confirmed, materials_confirmed, None


def _parse_reminder():
    """解析提醒字段并校验：提醒类型非空 或 确认无需提醒。"""
    reminder_type = request.form.get("reminder_type", "").strip()
    reminder_confirmed = bool(reminder_type) or (not reminder_type and bool(request.form.get("confirm_no_reminder")))
    if not reminder_type and not reminder_confirmed:
        msg = "请选择提醒类型或确认无需提醒"
        if _is_ajax():
            return None, None, jsonify({"success": False, "message": msg})
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
            if _is_ajax():
                return jsonify({"success": True, "message": "工卡新增成功"})
            flash("工卡新增成功", "success")
            return redirect("/card/list")

        except (ServiceError, ValidationError) as e:
            if _is_ajax():
                return jsonify({"success": False, "message": e.message})
            flash(e.message, "error")
            return redirect("/card/new")
        except Exception:
            logger.exception("新增工卡失败")
            if _is_ajax():
                return jsonify({"success": False, "message": "服务器错误，请稍后重试"})
            flash("服务器错误，请稍后重试", "error")
            return redirect("/card/new")

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
            if _is_ajax():
                return jsonify({"success": True, "message": "工卡更新成功"})
            flash("工卡更新成功", "success")
            return redirect("/card/list")

        except (ServiceError, ValidationError) as e:
            if _is_ajax():
                return jsonify({"success": False, "message": e.message})
            flash(e.message, "error")
        except Exception:
            logger.exception("更新工卡失败")
            if _is_ajax():
                return jsonify({"success": False, "message": "服务器错误"})
            flash("服务器错误，请稍后重试", "error")

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
        if _is_ajax():
            return jsonify({"success": True, "message": "工卡已删除"})
        flash("工卡已删除", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    except Exception:
        logger.exception("删除工卡失败")
        if _is_ajax():
            return jsonify({"success": False, "message": "服务器错误"})
        flash("服务器错误", "error")
    return redirect("/card/list")


@cards_bp.route("/card/<int:card_id>")
def card_detail(card_id):
    """工卡详情 (AJAX)"""
    try:
        card = current_app.extensions['card_service'].get_card(card_id)
        if not card:
            return jsonify({"error": "not found"}), 404
        return jsonify(card)
    except Exception:
        logger.exception("获取工卡详情失败")
        return jsonify({"error": "server error"}), 500


@cards_bp.route("/card/<int:card_id>/reset-confirm", methods=["POST"])
def card_reset_confirm(card_id):
    """重置确认：仅置 card_ok=False，不清空内容"""
    try:
        current_app.extensions['card_service'].update_card(card_id, card_ok=False)
        if _is_ajax():
            return jsonify({"success": True, "message": "已重置确认状态", "data": {"card_ok": False}})
        flash("已重置确认状态", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    return redirect("/card/list")



@cards_bp.route("/card/list-json")
def card_list_json():
    """工卡列表 JSON（供 set_form.html 搜索用）"""
    try:
        cards = current_app.extensions['card_service'].list_cards()
        return jsonify([{
                    "id": c["id"],
            "task_code": c["task_code"],
            "task_name": c["task_name"],
            "category": c["category"],
        } for c in cards])
    except Exception:
        logger.exception("获取工卡列表 JSON 失败")
        return jsonify([])

# ======================== 工卡组 ========================

@cards_bp.route("/card/sets")
def card_sets():
    """工卡组列表"""
    try:
        set_list = current_app.extensions['card_service'].list_card_sets()
        card_counts = {}
        sets = []
        for set in set_list:
            cards = current_app.extensions['card_service'].get_cards_in_set(set["id"])
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
                if _is_ajax():
                    return jsonify({"success": False, "message": msg})
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
            if _is_ajax():
                return jsonify({"success": True, "message": "工卡组新增成功"})
            flash("工卡组新增成功，工具/航材已同步至所有子工卡", "success")
            return redirect("/card/sets")
        except (ServiceError, ValidationError) as e:
            if _is_ajax():
                return jsonify({"success": False, "message": e.message})
            flash(e.message, "error")
        except Exception:
            logger.exception("新增工卡组失败")
            if _is_ajax():
                return jsonify({"success": False, "message": "服务器错误"})
            flash("服务器错误", "error")

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
                if _is_ajax():
                    return jsonify({"success": False, "message": msg})
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
            if _is_ajax():
                return jsonify({"success": True, "message": "工卡组更新成功"})
            flash("工卡组更新成功，工具/航材已同步至所有子工卡", "success")
            return redirect("/card/sets")
        except (ServiceError, ValidationError) as e:
            if _is_ajax():
                return jsonify({"success": False, "message": e.message})
            flash(e.message, "error")
        except Exception:
            logger.exception("更新工卡组失败")
            if _is_ajax():
                return jsonify({"success": False, "message": "服务器错误"})
            flash("服务器错误", "error")

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
            return jsonify({"error": "not found"}), 404
        cards_in_set = current_app.extensions['card_service'].get_cards_in_set(set_id)
        card_set["cards"] = [{"task_code": c["task_code"], "task_name": c.get("task_name", "")}
                             for c in cards_in_set]
        return jsonify(card_set)
    except Exception:
        logger.exception("获取工卡组详情失败")
        return jsonify({"error": "server error"}), 500


@cards_bp.route("/card/sets/<int:set_id>/delete", methods=["POST"])
def card_set_delete(set_id):
    """删除工卡组"""
    try:
        current_app.extensions['card_service'].delete_card_set(set_id)
        if _is_ajax():
            return jsonify({"success": True, "message": "工卡组已删除"})
        flash("工卡组已删除，关联工卡已解除绑定", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    except Exception:
        logger.exception("删除工卡组失败")
        if _is_ajax():
            return jsonify({"success": False, "message": "服务器错误"})
        flash("服务器错误", "error")
    return redirect("/card/sets")


@cards_bp.route("/card/sets/<int:set_id>/reset-confirm", methods=["POST"])
def card_set_reset_confirm(set_id):
    """重置确认：仅置 card_ok=False，不清空内容"""
    try:
        current_app.extensions['card_service'].update_card_set(set_id, card_ok=False)
        if _is_ajax():
            return jsonify({"success": True, "message": "已重置确认状态", "data": {"card_ok": False}})
        flash("已重置确认状态", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    return redirect("/card/sets")




# ======================== 飞机信息 ========================

def _require_amro_session() -> bool:
    """AMRO 功能前置检查（spec §3.2）：真实探活一次，失效由路由层 401+P8 阻断。"""
    svc = current_app.extensions["inventory_service"]
    return svc.check_login()


@cards_bp.route("/card/aircraft/amro-sync", methods=["POST"])
def aircraft_amro_sync():
    """查询飞机数据（后台线程执行，立即返回 started）。"""
    if not _require_amro_session():
        return jsonify({"success": False, "message": MESSAGES["P8"]}), 401
    store = current_app.extensions["store"]
    session_store = current_app.extensions["inventory_service"].session_store
    if not amro_sync.start_aircraft_sync(store, session_store):
        return jsonify({"success": False, "message": amro_sync.query_busy_message()
                        or "已有查询任务进行中，请等待完成后再查询"}), 409
    return jsonify({"success": True, "data": {"started": True}})


@cards_bp.route("/card/aircraft/amro-status")
def aircraft_amro_status():
    """查询飞机数据进度/简要结果（内存态）。"""
    return jsonify({"success": True, "data": amro_sync.get_query_status("aircraft")})


# ======================== 工卡版本检查（v3.5.0） ========================

@cards_bp.route("/card/amro-version-check", methods=["POST"])
def amro_version_check():
    """全量查询工卡版本（后台线程：实时拉 AMRO 比对 write_date，约 3~15 分钟）。"""
    if not amro_sync.require_amro_session():
        return jsonify({"success": False, "message": MESSAGES["P8"]}), 401
    store = current_app.extensions["store"]
    session_store = current_app.extensions["inventory_service"].session_store
    if not amro_sync.start_full_version_check(store, session_store, OUTPUT_DIR):
        return jsonify({"success": False, "message": amro_sync.query_busy_message()
                        or "已有查询任务进行中，请等待完成后再查询"}), 409
    return jsonify({"success": True, "data": {"started": True}})


@cards_bp.route("/card/amro-version-status")
def amro_version_status():
    """全量查询工卡版本进度/简要结果（内存态）。"""
    return jsonify({"success": True, "data": amro_sync.get_query_status("full_version")})


@cards_bp.route("/card/amro-version-report")
def amro_version_report_latest():
    """下载最近一次全量查询工卡版本的改版清单（output/ 内最新文件）。"""
    reports = sorted(OUTPUT_DIR.glob("amro_full_version_report_*.xlsx"))
    if not reports:
        return jsonify({"success": False, "message": "尚无改版清单，请先执行「全量查询工卡版本」"}), 404
    path = reports[-1]
    finished = datetime.fromtimestamp(
        path.stat().st_mtime, ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d")
    return send_file(path, as_attachment=True,
                     download_name=f"工卡改版清单（全量）查询日期{finished}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@cards_bp.route("/card/aircraft")
def aircraft_list():
    """飞机信息列表"""
    try:
        ac_list = current_app.extensions['card_service'].list_aircraft()
        amro_status = amro_sync.get_query_status("aircraft")
        amro_last_query = amro_sync.get_last_query_result("aircraft")
        return render_template("cards/aircraft.html",
                               ac_list=ac_list, amro_status=amro_status,
                               amro_last_query=amro_last_query)
    except Exception:
        logger.exception("获取飞机信息列表失败")
        flash("加载飞机信息失败", "error")
        return render_template("cards/aircraft.html",
                               ac_list=[], amro_status={},
                               amro_last_query=amro_sync.get_last_query_result("aircraft"))


@cards_bp.route("/card/aircraft/new", methods=["GET", "POST"])
def aircraft_new():
    """新增飞机"""
    if request.method == "GET":
        return render_template("cards/aircraft_form.html", ac=None, edit_mode=False)

    try:
        reg = validate_required(request.form, "reg", "机号")

        current_app.extensions['card_service'].add_aircraft(
            reg=reg,
            model=request.form.get("model", ""),
            engine=request.form.get("engine", ""),
            fsn=request.form.get("fsn", ""),
            msn=request.form.get("msn", ""),
            apu=request.form.get("apu", ""),
        )
        if _is_ajax():
            return jsonify({"success": True, "message": "飞机信息新增成功"})
        flash("飞机信息新增成功", "success")
        return redirect("/card/aircraft")

    except (ServiceError, ValidationError) as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    except Exception:
        logger.exception("新增飞机信息失败")
        if _is_ajax():
            return jsonify({"success": False, "message": "服务器错误"})
        flash("服务器错误", "error")

    return redirect("/card/aircraft")


@cards_bp.route("/card/aircraft/<int:aircraft_id>/edit", methods=["GET", "POST"])
def aircraft_edit(aircraft_id):
    """编辑飞机信息"""
    try:
        ac = current_app.extensions['card_service'].get_aircraft(aircraft_id)
    except (ServiceError, KeyError):
        ac = None

    if not ac:
        flash("飞机信息不存在", "error")
        return redirect("/card/aircraft")

    if request.method == "GET":
        return render_template("cards/aircraft_form.html", ac=ac, edit_mode=True)

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
        if _is_ajax():
            return jsonify({"success": True, "message": "飞机信息更新成功"})
        flash("飞机信息更新成功", "success")
        return redirect("/card/aircraft")

    except (ServiceError, ValidationError) as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    except Exception:
        logger.exception("更新飞机信息失败")
        if _is_ajax():
            return jsonify({"success": False, "message": "服务器错误"})
        flash("服务器错误", "error")

    return redirect("/card/aircraft")


@cards_bp.route("/card/aircraft/<int:aircraft_id>/delete", methods=["POST"])
def aircraft_delete(aircraft_id):
    """删除飞机信息"""
    try:
        current_app.extensions['card_service'].delete_aircraft(aircraft_id)
        if _is_ajax():
            return jsonify({"success": True, "message": "飞机信息已删除"})
        flash("飞机信息已删除", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    except Exception:
        logger.exception("删除飞机信息失败")
        if _is_ajax():
            return jsonify({"success": False, "message": "服务器错误"})
        flash("服务器错误", "error")
    return redirect("/card/aircraft")
