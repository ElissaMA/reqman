"""工作包蓝图 — 上传工作清单 + 工卡匹配"""

import os
import logging
import tempfile
from datetime import datetime
from flask import (Blueprint, current_app, render_template, request, redirect,
                   flash)

from ..services.worklist_parser import parse_worklist, merge_aircraft_info, WorklistError
from ..config import CATEGORIES
from ..services.work_package_matcher import match_work_package_items

logger = logging.getLogger(__name__)

packages_bp = Blueprint("packages", __name__)


# ---------- 匹配辅助函数 ----------

@packages_bp.route("/upload", methods=["GET", "POST"])
def upload():
    """上传工作清单并匹配"""
    store = current_app.extensions['store']
    if request.method == "POST":
        routine_file = request.files.get("routine_file")
        other_file = request.files.get("other_file")

        if not routine_file and not other_file:
            flash("请至少上传一个文件", "error")
            return redirect("/upload")

        all_items = []
        info_list = []
        errors = []

        # 上传文件存入系统临时目录，解析完随上下文退出自动清理，不污染项目目录
        with tempfile.TemporaryDirectory() as tmp_dir:
            for f, label in [(routine_file, "例行"), (other_file, "其他")]:
                if not f or not f.filename:
                    continue

                # 校验文件类型
                if not f.filename.lower().endswith(".xlsx"):
                    errors.append(f"{label}清单不是 .xlsx 格式")
                    continue

                tmp_path = os.path.join(tmp_dir, f"{label}.xlsx")
                try:
                    f.save(tmp_path)
                    result = parse_worklist(tmp_path, label)
                    all_items.extend(result["items"])
                    info_list.append(result["aircraft_info"])
                except WorklistError as e:
                    errors.append(f"{label}清单: {e.message}")
                    logger.warning(f"解析{label}清单失败: {e}")
                except Exception as e:
                    errors.append(f"{label}清单解析失败")
                    logger.exception(f"解析{label}清单异常")

        if errors:
            for err in errors:
                flash(err, "error")
            if not all_items:
                return redirect("/upload")

        # 合并飞机信息
        aircraft_info = merge_aircraft_info(info_list)

        # 按专业排序
        cat_order = {c: i for i, c in enumerate(CATEGORIES)}
        all_items.sort(key=lambda x: cat_order.get(x.get("category", ""), 99))

        # 统计（仅统计，不匹配）
        routine_count = sum(1 for i in all_items if i.get("source") == "例行")
        other_count = sum(1 for i in all_items if i.get("source") == "其他")

        # 保存原始工作包（不匹配），点击时延迟匹配
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
        flash("工作包上传成功，点击工作包即可匹配生成", "success")
        return redirect("/upload")

    # GET: 显示上传页面和工作包列表
    store = current_app.extensions['store']
    work_packages = store.get_work_packages()
    return render_template("packages/upload.html", work_packages=work_packages)


@packages_bp.route("/packages/<package_id>/rematch", methods=["POST"])
def package_rematch(package_id):
    """重新匹配工作包中的工卡（数据库更新后刷新匹配状态）"""
    store = current_app.extensions['store']
    pkg_data = store.get_work_package(package_id)
    if not pkg_data:
        flash("工作包不存在", "error")
        return redirect("/upload")

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

    flash("重新匹配完成", "success")
    return redirect("/upload")




