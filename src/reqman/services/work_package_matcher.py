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
