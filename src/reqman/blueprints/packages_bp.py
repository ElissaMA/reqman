"""工作包蓝图 — 上传工作清单 + 工卡匹配"""

import os
import logging
import tempfile
from datetime import datetime, date
from flask import (Blueprint, current_app, render_template, request, redirect,
                   flash)

from ..services.worklist_parser import parse_worklist, merge_aircraft_info, WorklistError
from ..services.work_package_matcher import match_work_package_items
from ..utils.response import api_success, api_error
from ..utils.error_handlers import NotFoundError, ValidationError
from ..utils.validators import validate_file_extension
from ..config import CATEGORIES

logger = logging.getLogger(__name__)

packages_bp = Blueprint("packages", __name__)


# ======================== 辅助函数 ========================


def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_wp_date(date_str):
    """解析 'YYYY.MM.DD' 格式日期，失败返回 None"""
    try:
        return datetime.strptime(date_str, "%Y.%m.%d").date()
    except (ValueError, TypeError):
        return None


def _classify_package(wp):
    """判断工作包状态：expired(过期>2天删除) / warning(过期≤2天灰色) / danger(未来4天内红色) / normal"""
    wp_date = _parse_wp_date(wp.get("date", ""))
    if not wp_date:
        return "normal"
    today = date.today()
    diff = (wp_date - today).days
    if diff < -2:
        return "expired"
    elif diff < 0:
        return "warning"
    elif diff <= 4:
        return "danger"
    else:
        return "normal"


def _parse_and_save_file(f, label):
    """解析上传的 Excel 文件，返回 (items, aircraft_info)
    如失败抛出 ValidationError
    """
    if not f or not f.filename:
        return [], {}
    validate_file_extension(f.filename, {"xlsx"}, label=f"{label}清单")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = os.path.join(tmp_dir, f"{label}.xlsx")
        f.save(tmp_path)
        result = parse_worklist(tmp_path, label)
    return result["items"], result["aircraft_info"]


# ======================== 路由 ========================


@packages_bp.route("/upload", methods=["GET", "POST"])
def upload():
    """上传工作清单并匹配"""
    if request.method == "POST":
        return _handle_upload_post()
    store = current_app.extensions['store']
    work_packages = store.get_work_packages()

    # 自动删除过期>2天的工作包，并标记状态
    today = date.today()
    filtered = []
    for wp in work_packages:
        wp_date = _parse_wp_date(wp.get("date", ""))
        if wp_date and (today - wp_date).days > 2:
            store.delete_work_package(wp["package_id"])
            continue
        wp["status"] = _classify_package(wp)
        filtered.append(wp)

    return render_template("packages/upload.html", work_packages=filtered)


def _handle_upload_post():
    """处理���传 POST 请求逻辑"""
    store = current_app.extensions['store']
    routine_file = request.files.get("routine_file")
    other_file = request.files.get("other_file")

    if not routine_file and not other_file:
        raise ValidationError("请至少上传��个文件", "NO_FILE")

    all_items = []
    info_list = []
    errors = []

    for f, label in [(routine_file, "例行"), (other_file, "其他")]:
        if not f or not f.filename:
            continue
        try:
            items, info = _parse_and_save_file(f, label)
            all_items.extend(items)
            if info:
                info_list.append(info)
        except (ValidationError, WorklistError) as e:
            msg = e.message if hasattr(e, "message") else str(e)
            errors.append(f"{label}清单: {msg}")
        except Exception:
            errors.append(f"{label}清单解析失败")
            logger.exception(f"解析{label}清单异常")

    if errors:
        for err in errors:
            logger.warning("上传错误: %s", err)
        if not all_items:
            raise ValidationError("；".join(errors), "PARSE_FAILED")
        # 部���成功：仅警告不阻断

    aircraft_info = merge_aircraft_info(info_list) if info_list else {}

    cat_order = {c: i for i, c in enumerate(CATEGORIES)}
    all_items.sort(key=lambda x: cat_order.get(x.get("category", ""), 99))

    routine_count = sum(1 for i in all_items if i.get("source") == "例行")
    other_count = sum(1 for i in all_items if i.get("source") == "其他")

    package_data = {
        "reg": aircraft_info.get("reg", ""),
        "description": aircraft_info.get("description", ""),
        "date": aircraft_info.get("date", datetime.now().strftime("%Y.%m.%d")),
        "aircraft_info": aircraft_info,
        "matched": [],
        "new_cards": [],
        "cancelled": [],
        "all_items": all_items,
        "routine_count": routine_count,
        "other_count": other_count,
        "is_matched": False,
        "generated_at": None,
    }
    store.save_work_package(package_data)

    if _is_ajax():
        return api_success(data={"package_id": package_data.get("id")},
                           message="工作包上传成功")
    flash("工作包上传成功，点击工作包即可匹配生成", "success")
    return redirect("/upload")


@packages_bp.route("/packages/<package_id>/rematch", methods=["POST"])
def package_rematch(package_id):
    """重新匹配工作包中的工卡（数据库更新后刷新匹配状态）"""
    store = current_app.extensions['store']
    pkg_data = store.get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("工作包不存在")

    all_items = pkg_data.get("all_items", [])
    svc = current_app.extensions['card_service']
    matched, new_cards, cancelled = match_work_package_items(all_items, store, svc)

    now_str = datetime.now().strftime("%Y.%m.%d %H:%M")
    pkg_data["matched"] = matched
    pkg_data["new_cards"] = new_cards
    pkg_data["cancelled"] = cancelled
    pkg_data["routine_count"] = sum(1 for i in all_items if i.get("source") == "例行")
    pkg_data["other_count"] = sum(1 for i in all_items if i.get("source") == "其他")
    pkg_data["is_matched"] = True
    pkg_data["generated_at"] = now_str
    store.save_work_package(pkg_data)

    if _is_ajax():
        return api_success(message="重新匹配完成")
    flash("重新匹配���成", "success")
    return redirect("/upload")
