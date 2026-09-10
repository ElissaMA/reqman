"""工作包工卡匹配服务 — 从 packages_bp 提取，供 generate_bp 复用"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def is_cancelled_item(item: dict) -> bool:
    """统一判断工作清单项是否撤销（AMRO/Excel 两入口共用）。"""
    remark = unicodedata.normalize("NFKC", str(item.get("remark") or ""))
    remark = re.sub(r"\s+", "", remark)
    return "撤销" in remark


def match_work_package_items(all_items, store, service):
    """对原始工作清单项执行数据库匹配，返回 (matched, new_cards, cancelled)

    匹配规则：
    - 数据库有工卡且工具/航材/提醒三块均已确认 → matched
    - 数据库有工卡但任一确认缺失（工具/航材/提醒） → new_cards（需人工补全）
    - 数据库无工卡 → new_cards
    """
    matched = []
    new_cards = []
    cancelled = []

    # 单次读取批量查卡，避免逐卡 N+1 整库重读
    codes = [str(item.get("task_code", "")).strip() for item in all_items]
    cards_by_code = store.find_by_codes(codes)

    for item in all_items:
        item["cancelled"] = is_cancelled_item(item)
        if item["cancelled"]:
            item["status"] = "cancelled"
            cancelled.append(item)
            continue

        card = cards_by_code.get(str(item["task_code"]).strip())
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
        else:
            item["status"] = "new"
            new_cards.append(item)

    service.propagate_set_data(matched, all_items, new_cards, cards_by_code=cards_by_code)
    service.dedup_by_set(matched, new_cards, cards_by_code=cards_by_code)
    return matched, new_cards, cancelled
