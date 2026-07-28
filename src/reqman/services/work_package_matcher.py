"""工作包工卡匹配服务 — 从 packages_bp 提取，供 generate_bp 复用"""

import logging

logger = logging.getLogger(__name__)


def match_work_package_items(all_items, store, svc):
    """对原始工作清单项执行数据库匹配，返回 (matched, new_cards, cancelled)

    匹配规则：
    - 数据库有工卡且工具/航材已确认 → matched
    - 数据库有工卡但工具/航材均未确认且无数据 → new_cards（需人工补全）
    - 数据库无工卡 → new_cards
    """
    matched = []
    new_cards = []
    cancelled = []

    for item in all_items:
        if "撤销" in item.get("remark", ""):
            item["status"] = "cancelled"
            cancelled.append(item)
            continue

        db_card = store.find_by_code(item["task_code"])
        if db_card:
            # 检查是否已配置工具/航材
            tools = db_card.get("tools", [])
            mats = db_card.get("materials", [])
            tc = db_card.get("tools_confirmed", False)
            mc = db_card.get("materials_confirmed", False)
            is_unconfigured = len(tools) == 0 and len(mats) == 0 and not (tc and mc)

            if is_unconfigured:
                item["status"] = "new"
                item["db_id"] = db_card["id"]
                item["task_name"] = db_card.get("task_name", "")
                item["category"] = db_card.get("category", "")
                item["unconfirmed"] = True
                new_cards.append(item)
            else:
                item["status"] = "matched"
                item["db_id"] = db_card["id"]
                item["set_id"] = db_card.get("set_id")
                item["tools"] = tools
                item["materials"] = mats
                matched.append(item)
        else:
            item["status"] = "new"
            new_cards.append(item)

    svc.propagate_set_data(matched, all_items, new_cards)
    svc.dedup_by_set(matched, new_cards)
    return matched, new_cards, cancelled
