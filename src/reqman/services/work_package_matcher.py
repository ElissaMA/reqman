"""工作包工卡匹配服务 — 从 packages_bp 提取，供 generate_bp 复用"""

import logging

logger = logging.getLogger(__name__)


def match_work_package_items(all_items, store, service):
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

        card = store.find_by_code(item["task_code"])
        if card:
            # 检查是否已配置工具/航材
            tools = card.get("tools", [])
            materials = card.get("materials", [])
            tools_confirmed = card.get("tools_confirmed", False)
            materials_confirmed = card.get("materials_confirmed", False)
            is_unconfigured = len(tools) == 0 and len(materials) == 0 and not (tools_confirmed and materials_confirmed)

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

    service.propagate_set_data(matched, all_items, new_cards)
    service.dedup_by_set(matched, new_cards)
    return matched, new_cards, cancelled
