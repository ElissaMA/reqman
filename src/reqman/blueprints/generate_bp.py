"""生成需求单蓝图 — 预览 + 下载 Excel"""

import logging
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_file, current_app)

from ..services.form_generator import generate_form
from ..services.work_package_matcher import match_work_package_items
from ..config import CONDITIONS, CATEGORIES

generate_bp = Blueprint("generate", __name__)

logger = logging.getLogger(__name__)

def _get_store():
    """懒加载获取 store 实例"""
    return current_app.extensions['store']

def _ensure_package_matched(pkg_data):
    """若工作包尚未匹配，执行匹配并保存"""
    if pkg_data.get("is_matched"):
        return pkg_data

    store = _get_store()
    svc = current_app.extensions['card_service']

    all_items = pkg_data.get("all_items", [])
    matched, new_cards, cancelled = match_work_package_items(all_items, store, svc)

    # 后处理：空工具+空航材+未确认的工卡从已匹配移入新工卡区域
    unconfirmed = []
    still_matched = []
    for item in matched:
        db_card = store.find_by_code(item["task_code"])
        if db_card:
            tools = db_card.get("tools", [])
            mats = db_card.get("materials", [])
            tools_ok = db_card.get("tools_confirmed", False)
            mats_ok = db_card.get("materials_confirmed", False)
            if (not tools) and (not mats) and (not tools_ok) and (not mats_ok):
                item["status"] = "new"
                item["unconfirmed"] = True
                item["reason"] = "工具航材未完善"
                unconfirmed.append(item)
            else:
                still_matched.append(item)
        else:
            still_matched.append(item)
    matched[:] = still_matched
    new_cards = unconfirmed + new_cards

    now_str = datetime.now().strftime("%Y.%m.%d %H:%M")
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
        return render_template("generate/form.html", has_data=False)

    pkg_data = _get_store().get_work_package(package_id)
    if not pkg_data:
        flash("数据已过期，请重新上传工作清单", "error")
        return redirect("/upload")

    # 延迟匹配：首次访问时匹配数据库并生成预览
    pkg_data = _ensure_package_matched(pkg_data)

    if request.method == "POST":
        try:
            return _handle_generate_post(pkg_data, package_id)
        except Exception as e:
            logger.exception("生成需求单失败")
            flash("生成失败，请稍后重试", "error")
            return redirect("/generate?package_id=" + package_id)

    # GET: 预览
    return _handle_generate_preview(pkg_data, package_id)

def _dedup_matched(matched):
    """按 set_id 去重，每组只取第一条"""
    seen = set()
    for item in matched:
        sid = item.get("set_id")
        if sid:
            if sid in seen:
                continue
            seen.add(sid)
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
                "quantity": qties[i].strip() if i < len(qties) else "1",
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
        "date": request.form.get("date", datetime.now().strftime("%Y.%m.%d")),
        "conditions": conditions,
        "spare_items": spare_items,
    }

    # 组装匹配数据（按set_id去重，同组只输出一套工具/航材）
    matched_tools, matched_mats, spare_auto = [], [], []

    for item in _dedup_matched(pkg_data.get("matched", [])):
        task_name = item.get("task_name", "")
        cat = item.get("category", "")
        set_name = item.get("set_name", "")

        for t in item.get("tools", []):
            matched_tools.append({**t, "category": cat, "task_name": task_name, "set_name": set_name})

        for m in item.get("materials", []):
            entry = {**m, "category": cat, "task_name": task_name, "set_name": set_name}
            if m.get("usage_type") in ["", "必须使用"]:
                matched_mats.append(entry)
            else:
                spare_auto.append(entry)

    new_cards = pkg_data.get("new_cards", [])
    parsed_data = {
        "matched_tools": matched_tools,
        "matched_materials": matched_mats,
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

def _handle_generate_preview(pkg_data: dict, package_id: str):
    """组装预览数据并渲染页面"""
    aircraft_info = pkg_data.get("aircraft_info", {})
    matched = pkg_data.get("matched", [])
    new_cards = pkg_data.get("new_cards", [])
    cancelled = pkg_data.get("cancelled", [])
    routine_count = pkg_data.get("routine_count", 0)
    other_count = pkg_data.get("other_count", 0)

    # 按set_id分组构建matched_sets
    set_groups = {}
    for item in matched:
        sid = item.get("set_id")
        if sid:
            group = set_groups.setdefault(sid, {"set_name": item.get("set_name", ""), "cards": []})
            group["cards"].append(item)

    # 分类排序权重
    cat_order = {"发动机": 0, "机体": 1, "电子": 2}

    # 预览工具/航材/备用（按set_id去重，每组只取第一条代表输出）
    tool_preview, mat_preview, spare_preview = [], [], []

    for item in _dedup_matched(matched):
        cat = item.get("category", "")
        task_name = item.get("task_name", "")
        set_name = item.get("set_name", "")

        for t in item.get("tools", []):
            tool_preview.append({**t, "category": cat, "task_name": task_name, "set_name": set_name})

        for m in item.get("materials", []):
            entry = {**m, "category": cat, "task_name": task_name, "set_name": set_name}
            if m.get("usage_type") in ["", "必须使用"]:
                mat_preview.append(entry)
            else:
                spare_preview.append(entry)

    # 排序
    for lst in [tool_preview, mat_preview, spare_preview]:
        lst.sort(key=lambda x: cat_order.get(x.get("category", ""), 99))

    # 有数据的专业列表
    def _active_cats(lst):
        return [c for c in CATEGORIES
                if any(t.get("category") == c for t in lst)]

    return render_template("generate/form.html",
                           has_data=True,
                           package_id=package_id,
                           aircraft_info=aircraft_info,
                           tool_preview=tool_preview,
                           material_preview=mat_preview,
                           spare_auto=spare_preview,
                           new_cards=new_cards,
                           cancelled=cancelled,
                           matched_sets=set_groups,
                           conditions=CONDITIONS,
                           tool_cats=_active_cats(tool_preview),
                           mat_cats=_active_cats(mat_preview),
                           spare_cats=_active_cats(spare_preview),
                           routine_count=routine_count,
                           other_count=other_count,
                           now=datetime.now(),
                           categories=CATEGORIES)
