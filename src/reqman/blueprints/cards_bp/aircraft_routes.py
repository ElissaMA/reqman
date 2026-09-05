"""飞机信息 与 AMRO 版本检查 路由。

OUTPUT_DIR 经包级属性运行时取值（cards_bp_pkg.OUTPUT_DIR），
以便测试 monkeypatch reqman.blueprints.cards_bp.OUTPUT_DIR 生效。
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app, flash, jsonify, redirect, render_template, request, send_file

import reqman.blueprints.cards_bp as cards_bp_pkg

from ...services import amro_sync
from ...services.card_service import ServiceError
from ...utils.error_handlers import ValidationError, is_ajax
from ...utils.messages import MESSAGES
from ...utils.response import api_error, api_success
from ...utils.validators import validate_required
from . import cards_bp
from .helpers import _aircraft_form_render_kwargs

logger = logging.getLogger(__name__)


@cards_bp.route("/card/aircraft/amro-sync", methods=["POST"])
def aircraft_amro_sync():
    """查询飞机数据（后台线程执行，立即返回 started）。"""
    if not amro_sync.require_amro_session():
        return api_error(MESSAGES["P8"], "LOGIN_EXPIRED", 401)
    store = current_app.extensions["store"]
    session_store = current_app.extensions["inventory_service"].session_store
    if not amro_sync.start_aircraft_sync(store, session_store):
        return api_error(amro_sync.query_busy_message()
                         or "已有查询任务进行中，请等待完成后再查询", "QUERY_BUSY", 409)
    return api_success(data={"started": True})


@cards_bp.route("/card/aircraft/amro-status")
def aircraft_amro_status():
    """查询飞机数据进度/简要结果（内存态）。"""
    return api_success(data=amro_sync.get_query_status("aircraft"))


@cards_bp.route("/card/amro-version-check", methods=["POST"])
def amro_version_check():
    """全量查询工卡版本（后台线程：实时拉 AMRO 比对 write_date，约 3~15 分钟）。"""
    if not amro_sync.require_amro_session():
        return api_error(MESSAGES["P8"], "LOGIN_EXPIRED", 401)
    store = current_app.extensions["store"]
    session_store = current_app.extensions["inventory_service"].session_store
    if not amro_sync.start_full_version_check(store, session_store, cards_bp_pkg.OUTPUT_DIR,
                                              current_app.extensions["cancelled_cards"]):
        return api_error(amro_sync.query_busy_message()
                         or "已有查询任务进行中，请等待完成后再查询", "QUERY_BUSY", 409)
    return api_success(data={"started": True})


@cards_bp.route("/card/amro-version-status")
def amro_version_status():
    """全量查询工卡版本进度/简要结果（内存态）。"""
    return api_success(data=amro_sync.get_query_status("full_version"))


@cards_bp.route("/card/amro-version-report")
def amro_version_report_latest():
    """下载最近一次全量查询工卡版本的改版清单（output/ 内最新文件）。"""
    reports = sorted(cards_bp_pkg.OUTPUT_DIR.glob("amro_full_version_report_*.xlsx"))
    if not reports:
        return api_error("尚无改版清单，请先执行「全量查询工卡版本」", "NO_REPORT", 404)
    path = reports[-1]
    finished = datetime.fromtimestamp(
        path.stat().st_mtime, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    return send_file(path, as_attachment=True,
                     download_name=f"工卡改版清单（全量）查询日期{finished}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@cards_bp.route("/card/aircraft")
def aircraft_list():
    """飞机信息列表"""
    try:
        ac_list = current_app.extensions['card_service'].list_aircraft()
        # 按「新建/编辑」日志时间倒序（空值排最后），同名按机号升序
        ac_list.sort(key=lambda ac: ac.get("reg", ""))
        ac_list.sort(key=lambda ac: ac.get("log_time", ""), reverse=True)
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
        if is_ajax():
            return api_success(message="飞机信息新增成功")
        flash("飞机信息新增成功", "success")
        return redirect("/card/aircraft")

    except (ServiceError, ValidationError) as e:
        if is_ajax():
            return api_error(e.message, status_code=200, field=getattr(e, "field", None))
        flash(e.message, "error")
        return render_template("cards/aircraft_form.html",
                               **_aircraft_form_render_kwargs(request.form, ac=None, edit_mode=False))
    except Exception:
        logger.exception("新增飞机信息失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 200)
        flash("服务器错误", "error")
        return render_template("cards/aircraft_form.html",
                               **_aircraft_form_render_kwargs(request.form, ac=None, edit_mode=False))


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
        if is_ajax():
            return api_success(message="飞机信息更新成功")
        flash("飞机信息更新成功", "success")
        return redirect("/card/aircraft")

    except (ServiceError, ValidationError) as e:
        if is_ajax():
            return api_error(e.message, status_code=200, field=getattr(e, "field", None))
        flash(e.message, "error")
        return render_template("cards/aircraft_form.html",
                               **_aircraft_form_render_kwargs(request.form, ac=ac, edit_mode=True))
    except Exception:
        logger.exception("更新飞机信息失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 200)
        flash("服务器错误", "error")
        return render_template("cards/aircraft_form.html",
                               **_aircraft_form_render_kwargs(request.form, ac=ac, edit_mode=True))


@cards_bp.route("/card/aircraft/<int:aircraft_id>/delete", methods=["POST"])
def aircraft_delete(aircraft_id):
    """删除飞机信息"""
    try:
        current_app.extensions['card_service'].delete_aircraft(aircraft_id)
        if is_ajax():
            return api_success(message="飞机信息已删除")
        flash("飞机信息已删除", "success")
    except ServiceError as e:
        if is_ajax():
            return api_error(e.message, status_code=200, field=getattr(e, "field", None))
        flash(e.message, "error")
    except Exception:
        logger.exception("删除飞机信息失败")
        if is_ajax():
            return api_error("服务器错误", "SERVER_ERROR", 200)
        flash("服务器错误", "error")
    return redirect("/card/aircraft")


@cards_bp.route("/card/aircraft/<int:aircraft_id>")
def aircraft_detail(aircraft_id):
    """飞机详情 (AJAX，供操作日志行预览)"""
    try:
        ac = current_app.extensions['card_service'].get_aircraft(aircraft_id)
        if not ac:
            return jsonify({"error": "not found"}), 404
        return jsonify(ac)
    except Exception:
        logger.exception("获取飞机信息详情失败")
        return jsonify({"error": "server error"}), 500
