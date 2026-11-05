"""工作包工卡匹配服务 — 从 packages_bp 提取，供 generate_bp 复用"""

import logging
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def is_cancelled_item(item: dict) -> bool:
    """统一判断工作清单项是否撤销（AMRO/Excel 两入口共用）。

    Excel 依备注识别；AMRO 详情使用 CONDITION 状态域（D/CX=撤销）。
    不读取 item 的 cancelled 布尔值，避免把主库作废语义混入清单撤销判定。
    """
    remark = unicodedata.normalize("NFKC", str(item.get("remark") or ""))
    remark = re.sub(r"\s+", "", remark)
    if "撤销" in remark:
        return True
    condition = str(item.get("condition") or item.get("CONDITION") or "").strip().upper()
    return condition in {"D", "CX"}


def needs_amro_reimport(package: dict) -> bool:
    """旧 AMRO 导入未保存 CONDITION；只重匹配本地清单无法恢复撤销状态。"""
    items = package.get("all_items") or []
    return (package.get("source") == "AMRO" and bool(items)
            and any("condition" not in item and "CONDITION" not in item for item in items))


def match_work_package_items(all_items, store, service):
    """对原始工作清单项执行数据库匹配，返回 (matched, new_cards, cancelled)

    匹配规则：
    - 数据库有工卡且工具/航材/提醒三块均已确认 → matched
    - 数据库有工卡但任一确认缺失（工具/航材/提醒） → new_cards（需人工补全）
    - 数据库无工卡 → new_cards
    - 工卡号命中数据库中已作废的卡 → cancelled（库级作废，区别于清单撤销标记）；
      不落入 new_cards——否则提示"去新增"又因工卡号被作废卡占用而新增失败，自相矛盾
    """
    matched = []
    new_cards = []
    cancelled = []

    # 单次读取批量查卡，避免逐卡 N+1 整库重读
    codes = [str(item.get("task_code", "")).strip() for item in all_items]
    cards_by_code = store.find_by_codes(codes)
    # 未命中的号若对应数据库已作废卡 → 归入 cancelled（仅在存在未命中时才多读一次）
    missing_codes = {c for c in dict.fromkeys(codes) if c and c not in cards_by_code}
    cancelled_by_code = (
        {c.get("task_code", ""): c for c in store.get_all(include_cancelled=True)
         if c.get("cancelled")} if missing_codes else {})

    for item in all_items:
        item["cancelled"] = is_cancelled_item(item)
        if item["cancelled"]:
            item["status"] = "cancelled"
            cancelled.append(item)
            continue

        code = str(item.get("task_code", "")).strip()
        card = cards_by_code.get(code)
        if card:
            item["reminder_type"] = card.get("reminder_type", "")
            item["card_ok"] = card.get("card_ok", False)
            item["reminder_confirmed"] = card.get("reminder_confirmed", False)
            # 三块（工具/航材/提醒）任一未确认 → 需人工补全
            tools = card.get("tools", [])
            materials = card.get("materials", [])
            tools_confirmed = card.get("tools_confirmed", False)
            materials_confirmed = card.get("materials_confirmed", False)
            reminder_confirmed = item["reminder_confirmed"]
            is_unconfigured = not (tools_confirmed and materials_confirmed and reminder_confirmed)

            if is_unconfigured:
                item["status"] = "new"
                item["db_id"] = card["id"]
                item["task_name"] = card.get("task_name", "")
                item["category"] = card.get("category", "")
                item["task_type"] = card.get("task_type", "")
                item["unconfirmed"] = True
                new_cards.append(item)
            else:
                item["status"] = "matched"
                item["db_id"] = card["id"]
                item["set_id"] = card.get("set_id")
                item["category"] = card.get("category", item.get("category"))
                item["task_type"] = card.get("task_type", item.get("task_type"))
                item["tools"] = tools
                item["materials"] = materials
                matched.append(item)
        elif code and code in cancelled_by_code:
            # 数据库级作废：不参与匹配与输出，也不提示新增（作废页可恢复）
            item["status"] = "cancelled"
            item["cancelled"] = True
            item["db_cancelled"] = True
            cancelled.append(item)
        else:
            item["status"] = "new"
            new_cards.append(item)

    service.propagate_set_data(matched, all_items, new_cards,
                               cards_by_code=cards_by_code, cancelled=cancelled)
    service.dedup_by_set(matched, new_cards,
                         cards_by_code=cards_by_code, cancelled=cancelled)
    return matched, new_cards, cancelled


def apply_match(pkg_data: dict, store, service) -> dict:
    """执行匹配并写回派生字段 —— 全系统唯一匹配入口（仅「重新匹配」调用）。

    导入只存原始清单行；此处集中完成匹配、未确认工卡归入新工卡区，
    以及 cancelled_count / routine_count / other_count / is_matched / generated_at 统计。
    """
    all_items = pkg_data.get("all_items", [])
    matched, new_cards, cancelled = match_work_package_items(all_items, store, service)

    # 三块（工具/航材/提醒）任一未确认的工卡从已匹配移入新工卡区域。
    # 一次性批量查卡，避免循环内逐条 find_by_code 的 N+1 整库重读。
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

    pkg_data["matched"] = matched
    pkg_data["new_cards"] = unconfirmed + new_cards
    pkg_data["cancelled"] = cancelled
    pkg_data["cancelled_count"] = sum(1 for item in cancelled if is_cancelled_item(item))
    pkg_data["routine_count"] = sum(1 for i in all_items if i.get("source") == "例行")
    pkg_data["other_count"] = sum(1 for i in all_items if i.get("source") == "其他")
    pkg_data["is_matched"] = True
    pkg_data["generated_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    return pkg_data
