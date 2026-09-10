"""生成需求单蓝图 — 预览 + 下载 Excel + 提醒单（纯同步）+ 工卡改版下载"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file

from ..config import CATEGORIES, CATEGORY_ORDER, CONDITION_DEFAULTS, CONDITIONS, OUTPUT_DIR
from ..services.amro_sync import build_package_label
from ..services.checklist_generator import generate_chemical_list, generate_tool_list
from ..services.form_generator import generate_form
from ..services.reminder_generator import generate_reminder
from ..services.work_package_matcher import match_work_package_items
from ..utils.error_handlers import NotFoundError, TemplateContractError, is_ajax
from ..utils.response import api_error, api_success

generate_bp = Blueprint("generate", __name__)

logger = logging.getLogger(__name__)


def _get_store():
    return current_app.extensions['store']



def _ensure_package_matched(pkg_data):
    """若工作包尚未匹配，执行匹配并保存"""
    if pkg_data.get("is_matched"):
        return pkg_data

    store = _get_store()
    service = current_app.extensions['card_service']

    all_items = pkg_data.get("all_items", [])
    matched, new_cards, cancelled = match_work_package_items(all_items, store, service)

    # 后处理：三块（工具/航材/提醒）任一未确认的工卡从已匹配移入新工卡区域
    # 一次性批量查卡，避免循环内逐条 find_by_code 的 N+1 整库重读
    codes = [item["task_code"] for item in matched if item.get("task_code")]
    cards_by_code = store.find_by_codes(codes)
    unconfirmed = []
    still_matched = []
    for item in matched:
        card = cards_by_code.get(item.get("task_code", ""))
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

    now_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    pkg_data["matched"] = matched
    pkg_data["new_cards"] = new_cards
    pkg_data["cancelled"] = cancelled
    pkg_data["cancelled_count"] = len(cancelled)
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
        if is_ajax():
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
        except TemplateContractError as exc:
            # 模板契约失败：AJAX 下载返回 400 JSON，普通请求才重定向展示 flash。
            logger.error("需求单模板契约失败: %s", exc)
            if is_ajax():
                return api_error(str(exc), "TEMPLATE_CONTRACT", 400)
            flash(str(exc), "error")
            return redirect("/generate?package_id=" + package_id)
        except (AttributeError, RuntimeError, ValueError) as exc:
            logger.exception("需求单模板结构异常")
            message = f"需求单模板结构异常：{exc}"
            if is_ajax():
                return api_error(message, "TEMPLATE_CONTRACT", 400)
            flash(message, "error")
            return redirect("/generate?package_id=" + package_id)
        except Exception:
            logger.exception("生成需求单失败")
            if is_ajax():
                return api_error("需求单生成失败，请检查模板后重试", "GENERATE_ERROR", 500)
            flash("生成失败，请稍后重试", "error")
            return redirect("/generate?package_id=" + package_id)

    # GET: 预览
    if is_ajax():
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


def _flatten_matched(matched):
    """按 set_id 去重铺平：每组一套工具/航材。返回 (tools, matched_materials, spare_auto)。

    matched_materials = usage_type 为空/必须使用；spare_auto = 检查有问题领用（备用区）。
    """
    matched_tools, matched_materials, spare_auto = [], [], []
    for item in _dedup_matched(matched):
        category = item.get("category", "")
        task_name = item.get("task_name", "")
        set_name = item.get("set_name", "")

        for t in item.get("tools", []):
            matched_tools.append({**t, "category": category, "task_name": task_name, "set_name": set_name})

        for m in item.get("materials", []):
            entry = {**m, "category": category, "task_name": task_name, "set_name": set_name}
            if m.get("usage_type") in ["", "必须使用"]:
                matched_materials.append(entry)
            else:
                spare_auto.append(entry)
    return matched_tools, matched_materials, spare_auto


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
        "date": request.form.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")),
        "conditions": conditions,
        "spare_items": spare_items,
    }

    # 组装匹配数据（按set_id去重，同组只输出一套工具/航材）
    matched_tools, matched_materials, spare_auto = _flatten_matched(pkg_data.get("matched", []))

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

    # 分类排序权重（统一来源 config.CATEGORY_ORDER）
    cat_order = CATEGORY_ORDER

    # 预览工具/航材/备用（按set_id去重，每组只取第一条代表输出）
    tool_preview, mat_preview, spare_preview = _flatten_matched(matched)

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
                           condition_defaults=CONDITION_DEFAULTS,
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
    db_type = db_engine = ""
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
            db_type = ac_db.get("model", "")
            db_engine = ac_db.get("engine", "")
    # 机型/发动机/FSN/MSN/APU 统一以本地航空器数据库为唯一来源；
    # 工作包 aircraft_info 仅作为机号、描述、日期等业务上下文，不回退其 type/engine。
    aircraft_type = db_type
    engine = db_engine
    form_data = {
        "reg": reg,
        "aircraft_type": aircraft_type,
        "engine": engine,
        "description": ac.get("description", ""),
        "level": level,
        "fsn": fsn,
        "msn": msn,
        "apu": apu,
        "date": ac.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")),
        "routine_count": pkg_data.get("routine_count", 0),
        "other_count": pkg_data.get("other_count", 0),
    }

    buffer, filename = generate_reminder(form_data, items)
    return send_file(
        buffer, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _checklist_package():
    """借用清单共用：解析 package_id → 取包 → 确保已匹配。"""
    package_id = request.form.get("package_id", "")
    if not package_id:
        return api_error("缺少工作包参数", "MISSING_PACKAGE_ID", 400)
    pkg_data = _get_store().get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("数据已过期，请重新上传工作清单")
    return _ensure_package_matched(pkg_data)


def _checklist_form_data(pkg_data: dict) -> dict:
    """借用清单表头数据：机号/描述/日期（与需求单表单字段同义）。"""
    ac = pkg_data.get("aircraft_info", {})
    return {
        "reg": ac.get("reg", ""),
        "description": ac.get("description", ""),
        "date": ac.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")),
    }


@generate_bp.route("/generate/tool-list", methods=["POST"])
def tool_list_download():
    """生成《定检中队零散工具借用清单》（按匹配结果自动汇总，系统匹配后预览页下载）。"""
    pkg_data = _checklist_package()
    if not isinstance(pkg_data, dict):   # api_error 短路
        return pkg_data
    tools, _, _ = _flatten_matched(pkg_data.get("matched", []))
    try:
        buffer, filename = generate_tool_list(_checklist_form_data(pkg_data), tools)
    except (RuntimeError, ValueError) as exc:
        # 模板契约失败（如区标签被改动）→ 友好中文提示而非 500
        raise TemplateContractError(f"工具借用清单生成失败：{exc}") from exc
    return send_file(
        buffer, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@generate_bp.route("/generate/chemical-list", methods=["POST"])
def chemical_list_download():
    """生成《定检中队开封航化借用清单》（remark 含"开封航化"的航材汇总）。"""
    pkg_data = _checklist_package()
    if not isinstance(pkg_data, dict):   # api_error 短路
        return pkg_data
    _, materials, _ = _flatten_matched(pkg_data.get("matched", []))
    try:
        buffer, filename = generate_chemical_list(_checklist_form_data(pkg_data), materials)
    except (RuntimeError, ValueError) as exc:
        raise TemplateContractError(f"航化借用清单生成失败：{exc}") from exc
    return send_file(
        buffer, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@generate_bp.route("/generate/package-version-report")
def package_version_report():
    """下载某工作包的工卡改版清单（先在工作包页执行「检查工作包工卡版本」生成）。"""
    package_id = request.args.get("package_id", "").strip()
    if not package_id:
        return api_error("缺少工作包参数", "MISSING_PACKAGE_ID", 400)
    # 防路径穿越：仅允许安全字符，且解析后父目录必须仍在 OUTPUT_DIR 内
    if not re.fullmatch(r"[A-Za-z0-9_-]+", package_id):
        return api_error("工作包参数非法", "INVALID_PACKAGE_ID", 400)
    path = OUTPUT_DIR / f"amro_pkg_version_report_{package_id}.xlsx"
    if path.resolve().parent != OUTPUT_DIR.resolve():
        return api_error("工作包参数非法", "INVALID_PACKAGE_ID", 400)
    if not path.exists():
        return api_error("尚未检查该工作包的工卡版本，请先在工作包页点击「检查工作包工卡版本」",
                         "NO_VERSION_REPORT", 404)
    pkg_data = _get_store().get_work_package(package_id) or {}
    # 文件名安全化：去除路径分隔/非法字符，压缩空白；工作包记录被清理后回退「工作包」而非 UUID
    label = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", build_package_label(pkg_data, with_date=True))
    label = re.sub(r"\s+", " ", label).strip(" .-")[:60].strip()
    if not label:
        label = "工作包"
    finished = datetime.fromtimestamp(
        path.stat().st_mtime, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    return send_file(path, as_attachment=True,
                     download_name=f"工卡改版清单（{label}）检查日期{finished}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
