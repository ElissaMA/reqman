"""工作包匹配输出提醒状态"""
from reqman.services.work_package_matcher import match_work_package_items


def _items():
    return [
        {"task_code": "M-001", "task_name": "匹配卡", "category": "电子",
         "task_type": "", "remark": "", "source": "例行"},
        {"task_code": "M-002", "task_name": "待确认卡", "category": "机体",
         "task_type": "", "remark": "", "source": "其他"},
        {"task_code": "M-003", "task_name": "撤销卡", "category": "发动机",
         "task_type": "", "remark": "撤销", "source": "例行"},
        {"task_code": "NO-DB", "task_name": "库无此卡", "category": "",
         "task_type": "", "remark": "", "source": "例行"},
    ]


class TestMatcherReminderStatus:
    def test_matched_item_carries_reminder(self, json_store, card_service):
        store = json_store
        json_store.add(task_code="M-001", task_name="匹配卡", category="电子")
        json_store.update(1, tools=[{"device_name": "万用表"}],
                          tools_confirmed=True, materials_confirmed=True,
                          reminder_type="重点提醒", reminder_confirmed=True, card_ok=True)
        json_store.add(task_code="M-002", task_name="待确认卡", category="机体")
        json_store.update(2, reminder_type="一般提醒", card_ok=False)
        matched, new_cards, cancelled = match_work_package_items(_items(), store, card_service)
        assert any(i["task_code"] == "M-001" and i["reminder_type"] == "重点提醒"
                   and i["card_ok"] is True for i in matched)
        assert any(i["task_code"] == "M-002" and i["card_ok"] is False for i in new_cards)
        assert any(i["task_code"] == "M-003" for i in cancelled)
        assert any(i["task_code"] == "NO-DB" for i in new_cards)


class TestMatcherConfirmBlocks:
    """三块（工具/航材/提醒）任一未确认 → new_cards"""

    def _one_item(self, code):
        return [{"task_code": code, "task_name": "卡", "category": "电子",
                 "task_type": "", "remark": "", "source": "例行"}]

    def test_all_three_confirmed_matches(self, json_store, card_service):
        json_store.add(task_code="B-001", task_name="卡", category="电子")
        json_store.update(1, tools_confirmed=True, materials_confirmed=True,
                          reminder_confirmed=True, card_ok=True)
        matched, new_cards, _ = match_work_package_items(
            self._one_item("B-001"), json_store, card_service)
        assert any(i["task_code"] == "B-001" for i in matched)
        assert not any(i["task_code"] == "B-001" for i in new_cards)

    def test_tools_unconfirmed_goes_new(self, json_store, card_service):
        json_store.add(task_code="B-002", task_name="卡", category="电子")
        json_store.update(1, materials_confirmed=True, reminder_confirmed=True,
                          card_ok=True)
        matched, new_cards, _ = match_work_package_items(
            self._one_item("B-002"), json_store, card_service)
        assert any(i["task_code"] == "B-002" and i.get("unconfirmed") for i in new_cards)
        assert not any(i["task_code"] == "B-002" for i in matched)

    def test_reminder_unconfirmed_goes_new(self, json_store, card_service):
        json_store.add(task_code="B-003", task_name="卡", category="电子")
        json_store.update(1, tools_confirmed=True, materials_confirmed=True,
                          card_ok=True)
        matched, new_cards, _ = match_work_package_items(
            self._one_item("B-003"), json_store, card_service)
        assert any(i["task_code"] == "B-003" and i.get("unconfirmed") for i in new_cards)
        assert not any(i["task_code"] == "B-003" for i in matched)
