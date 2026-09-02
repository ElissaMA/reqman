"""生成需求单蓝图 — 预览 + 下载 Excel + 提醒单（纯同步）+ 工卡改版下载"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file

from ..config import CATEGORIES, CONDITIONS, OUTPUT_DIR
from ..services.amro_sync import package_report_label
from ..services.form_generator import generate_form
from ..services.reminder_generator import generate_reminder
from ..services.work_package_matcher import match_work_package_items
from ..utils.error_handlers import NotFoundError
from ..utils.response import api_error, api_success

generate_bp = Blueprint("generate", __name__)

logger = logging.getLogger(__name__)


def _get_store():
    return current_app.extensions['store']


def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _ensure_package_matched(pkg_data):
    """若工作包尚未匹配，执行匹配并保存"""
    if pkg_data.get("is_matched"):
        return pkg_data

    store = _get_store()
    service = current_app.extensions['card_service']

    all_items = pkg_data.get("all_items", [])
    matched, new_cards, cancelled = match_work_package_items(all_items, store, service)

    # 后处理：三块（工具/航材/提醒）任一未确认的工卡从已匹配移入新工卡区域
    unconfirmed = []
    still_matched = []
    for item in matched:
        card = store.find_by_code(item["task_code"])
        if card:
            tools_ok = card.get("tools_confirmed", False)
            materials_ok = card.get("materials_confirmed", False)
            reminder_ok = card.get("reminder_confirmed", False)
            if not (tools_ok and materials_ok and reminder_ok):
                item["status"] = "new"
                item["unconfirmed"] = True
                item["reason"] = "工具/航材/提醒未完善"
                unconfirmed.append(item)
            else:
                still_matched.append(item)
        else:
            still_matched.append(item)
    matched[:] = still_matched
    new_cards = unconfirmed + new_cards

    now_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d %H:%M")
    pkg_data["matched"] = matched
    pkg_data["new_cards"] = new_cards
    pkg_data["cancelled"] = cancelled
    pkg_data["routine_count"] = sum(1 for i in all_items if i.get("source") == "例行")
    pkg_data["other_count"] = sum(1 for i in all_items if i.get("source") == "其他")
    pkg_data["is_matched"] = True
    pkg_data["generated_at"] = now_str
    store.save_work_package(pkg_data)

    return pkg_data


@generate_bp.route("/generate", methods=["GET", "POST"])
def generate():
    """生成需求单预览 + 确认下载"""
    package_id = request.args.get("package_id", "") or request.form.get("package_id", "")

    if not package_id:
        if _is_ajax():
            return api_error("缺少工作包参数", "MISSING_PACKAGE_ID", 400)
        return render_template("generate/form.html", has_data=False)

    pkg_data = _get_store().get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("数据已过期，请重新上传工作清单")

    # 延迟匹配：首次访问时匹配数据库并生成预览
    pkg_data = _ensure_package_matched(pkg_data)

    if request.method == "POST":
        try:
            return _handle_generate_post(pkg_data, package_id)
        except Exception:
            logger.exception("生成需求单失败")
            flash("生成失败，请稍后重试", "error")
            return redirect("/generate?package_id=" + package_id)

    # GET: 预览
    if _is_ajax():
        return _handle_generate_json_preview(pkg_data, package_id)
    return _handle_generate_preview(pkg_data, package_id)


def _dedup_matched(matched):
    """按 set_id 去重，每组只取第一条"""
    seen = set()
    for item in matched:
        set_id = item.get("set_id")
        if set_id:
            if set_id in seen:
                continue
            seen.add(set_id)
        yield item


def _handle_generate_post(pkg_data: dict, package_id: str):
    """处理表单提交，生成并返回 Excel"""
    aircraft_info = pkg_data.get("aircraft_info", {})

    # 解析运行条件
    conditions = [
        {
            "name": c,
            "requirement": request.form.get(f"cond_{i}_req", "不需要"),
            "remark": request.form.get(f"cond_{i}_remark", ""),
            "responsible": request.form.get(f"cond_{i}_resp", ""),
        }
        for i, c in enumerate(CONDITIONS)
    ]

    # 解析手动备用航材
    spare_items = []
    names = request.form.getlist("spare_name[]")
    pns = request.form.getlist("spare_pn[]")
    qties = request.form.getlist("spare_qty[]")
    rems = request.form.getlist("spare_remark[]")
    applicants = request.form.getlist("spare_applicant[]")

    for i, name in enumerate(names):
        name = name.strip()
        if name:
            spare_items.append({
                "material_name": name,
                "part_number": pns[i].strip() if i < len(pns) else "",
                "quantity": qties[i].strip() if i < len(qties) else "",
                "remark": rems[i].strip() if i < len(rems) else "",
                "applicant": applicants[i].strip() if i < len(applicants) else "",
            })

    # 组装表单数据
    form_data = {
        "reg": request.form.get("reg", aircraft_info.get("reg", "")),
        "aircraft_type": request.form.get("aircraft_type",
                                          aircraft_info.get("type", "")),
        "package": request.form.get("package",
                                     aircraft_info.get("package", "")),
        "description": request.form.get("description",
                                         aircraft_info.get("description", "")),
        "date": request.form.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d")),
        "conditions": conditions,
        "spare_items": spare_items,
    }

    # 组装匹配数据（按set_id去重，同组只输出一套工具/航材）
    matched_tools, matched_materials, spare_auto = [], [], []

    for item in _dedup_matched(pkg_data.get("matched", [])):
        task_name = item.get("task_name", "")
        category = item.get("category", "")
        set_name = item.get("set_name", "")

        for t in item.get("tools", []):
            matched_tools.append({**t, "category": category, "task_name": task_name, "set_name": set_name})

        for m in item.get("materials", []):
            entry = {**m, "category": category, "task_name": task_name, "set_name": set_name}
            if m.get("usage_type") in ["", "必须使用"]:
                matched_materials.append(entry)
            else:
                spare_auto.append(entry)

    new_cards = pkg_data.get("new_cards", [])
    parsed_data = {
        "matched_tools": matched_tools,
        "matched_materials": matched_materials,
        "spare_auto": spare_auto,
        "new_cards": new_cards,
    }

    # 生成 Excel（返回 BytesIO，不落盘）
    buffer, filename = generate_form(form_data, parsed_data)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _handle_generate_json_preview(pkg_data: dict, package_id: str):
    """AJAX 请求返回预览 JSON"""
    aircraft_info = pkg_data.get("aircraft_info", {})
    matched = pkg_data.get("matched", [])
    new_cards = pkg_data.get("new_cards", [])
    cancelled = pkg_data.get("cancelled", [])

    return api_success(data={
        "package_id": package_id,
        "aircraft_info": aircraft_info,
        "matched_count": len(matched),
        "new_cards_count": len(new_cards),
        "cancelled_count": len(cancelled),
        "routine_count": pkg_data.get("routine_count", 0),
        "other_count": pkg_data.get("other_count", 0),
        "generated_at": pkg_data.get("generated_at"),
        "is_matched": pkg_data.get("is_matched", False),
    })


def _handle_generate_preview(pkg_data: dict, package_id: str):
    """组装预览数据并渲染页面"""
    aircraft_info = pkg_data.get("aircraft_info", {})
    matched = pkg_data.get("matched", [])
    new_cards = pkg_data.get("new_cards", [])

    # 分类排序权重
    cat_order = {"发动机": 0, "机体": 1, "电子": 2}

    # 预览工具/航材/备用（按set_id去重，每组只取第一条代表输出）
    tool_preview, mat_preview, spare_preview = [], [], []

    for item in _dedup_matched(matched):
        category = item.get("category", "")
        task_name = item.get("task_name", "")
        set_name = item.get("set_name", "")

        for t in item.get("tools", []):
            tool_preview.append({**t, "category": category, "task_name": task_name, "set_name": set_name})

        for m in item.get("materials", []):
            entry = {**m, "category": category, "task_name": task_name, "set_name": set_name}
            if m.get("usage_type") in ["", "必须使用"]:
                mat_preview.append(entry)
            else:
                spare_preview.append(entry)

    # 排序
    for lst in [tool_preview, mat_preview, spare_preview]:
        lst.sort(key=lambda x: cat_order.get(x.get("category", ""), 99))

    def _group_by_category(lst):
        """按专业分组，返回 [(category, [items])]"""
        grouped = {}
        for item in lst:
            category = item.get("category", "")
            grouped.setdefault(category, []).append(item)
        return [(category, grouped[category]) for category in CATEGORIES if category in grouped]

    return render_template("generate/form.html",
                           has_data=True,
                           package_id=package_id,
                           aircraft_info=aircraft_info,
                           new_cards=new_cards,
                           conditions=CONDITIONS,
                           tool_groups=_group_by_category(tool_preview),
                           mat_groups=_group_by_category(mat_preview),
                           spare_groups=_group_by_category(spare_preview),
                           now=datetime.now(ZoneInfo("Asia/Shanghai")),
                           categories=CATEGORIES)


@generate_bp.route("/generate/reminder", methods=["POST"])
def reminder_download():
    """生成《定检工作提醒单》（纯同步，v3.6.0 起不再内嵌版本检查）。"""
    package_id = request.form.get("package_id", "")
    if not package_id:
        return api_error("缺少工作包参数", "MISSING_PACKAGE_ID", 400)
    pkg_data = _get_store().get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("数据已过期，请重新上传工作清单")
    pkg_data = _ensure_package_matched(pkg_data)

    items = []
    for item in _dedup_matched(pkg_data.get("matched", [])):
        if item.get("card_ok") and item.get("reminder_confirmed") and item.get("reminder_type"):
            items.append({
                "task_name": item.get("set_name") or item.get("task_name", ""),
                "category": item.get("category", ""),
                "reminder_type": item.get("reminder_type", ""),
                "source": item.get("source", "例行"),
            })

    ac = pkg_data.get("aircraft_info", {})
    reg = ac.get("reg", "")
    level = ac.get("level", "") or ac.get("description", "")
    fsn = msn = apu = ""
    if reg:
        store = _get_store()
        ac_db = store.find_aircraft_by_reg(reg)
        if not ac_db:
            stripped = reg.removeprefix("B-")
            ac_db = store.find_aircraft_by_reg(stripped) or store.find_aircraft_by_reg("B-" + stripped)
        if ac_db:
            fsn = ac_db.get("fsn", "")
            msn = ac_db.get("msn", "")
            apu = ac_db.get("apu", "")
    form_data = {
        "reg": reg,
        "aircraft_type": ac.get("type", ""),
        "description": ac.get("description", ""),
        "level": level,
        "fsn": fsn,
        "msn": msn,
        "apu": apu,
        "date": ac.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d")),
        "routine_count": pkg_data.get("routine_count", 0),
        "other_count": pkg_data.get("other_count", 0),
    }

    buffer, filename = generate_reminder(form_data, items)
    return send_file(
        buffer, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@generate_bp.route("/generate/package-version-report")
def package_version_report():
    """下载某工作包的工卡改版清单（先在工作包页执行「查询工作包工卡版本」生成）。"""
    package_id = request.args.get("package_id", "")
    if not package_id:
        return api_error("缺少工作包参数", "MISSING_PACKAGE_ID", 400)
    path = OUTPUT_DIR / f"amro_pkg_version_report_{package_id}.xlsx"
    if not path.exists():
        return api_error("尚未查询该工作包的工卡版本，请先在工作包页点击「查询工作包工卡版本」",
                         "NO_VERSION_REPORT", 404)
    pkg_data = _get_store().get_work_package(package_id) or {}
    label = package_report_label(pkg_data) or package_id
    finished = datetime.fromtimestamp(
        path.stat().st_mtime, ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d")
    return send_file(path, as_attachment=True,
                     download_name=f"工卡改版清单（{label}）查询日期{finished}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
