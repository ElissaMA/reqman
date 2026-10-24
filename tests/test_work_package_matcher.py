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


class TestMatcherDbCancelled:
    """库级作废卡：命中数据库已作废记录 → cancelled 分组，不落入 new_cards"""

    def _item(self, code):
        return [{"task_code": code, "task_name": "卡", "category": "电子",
                 "task_type": "", "remark": "", "source": "例行"}]

    def test_db_cancelled_goes_cancelled_not_new(self, json_store, card_service):
        card = json_store.add(task_code="DB-C-1", task_name="已作废卡", category="电子")
        json_store.mark_cancelled(card["id"], source="full_version", set_name="")
        matched, new_cards, cancelled = match_work_package_items(
            self._item("DB-C-1"), json_store, card_service)
        assert not matched
        assert not any(i["task_code"] == "DB-C-1" for i in new_cards)  # 不提示新增
        entry = next(i for i in cancelled if i["task_code"] == "DB-C-1")
        assert entry["db_cancelled"] is True and entry["status"] == "cancelled"

    def test_active_card_still_matches(self, json_store, card_service):
        """回归：在用卡匹配行为不受作废分支影响"""
        json_store.add(task_code="DB-A-1", task_name="在用卡", category="电子")
        json_store.update(1, tools_confirmed=True, materials_confirmed=True,
                          reminder_confirmed=True, card_ok=True)
        matched, _, _ = match_work_package_items(
            self._item("DB-A-1"), json_store, card_service)
        assert any(i["task_code"] == "DB-A-1" for i in matched)


class TestDefensiveCancelledBucket:
    """propagate/dedup 防御分支：漏网撤销项须移入 cancelled 桶而非静默丢弃。

    匹配器正常路径已路由全部撤销项，此分支当前不可达——测试直接调服务方法
    模拟"未来调用顺序变化"的兜底行为。
    """

    def _leaked_item(self):
        return [{"task_code": "LEAK-1", "task_name": "漏网撤销", "category": "电子",
                 "task_type": "", "remark": "此卡撤销", "source": "例行"}]

    def test_dedup_by_set_routes_leak_to_cancelled(self, card_service):
        leak = self._leaked_item()
        cancelled = []
        card_service.dedup_by_set(matched=[], new_cards=leak, cancelled=cancelled)
        assert leak == []                       # 移出 new_cards
        assert cancelled and cancelled[0]["task_code"] == "LEAK-1"
        assert cancelled[0]["status"] == "cancelled"

    def test_propagate_routes_leak_to_cancelled(self, json_store, card_service):
        """传播扫描（需至少一个带组 matched 项触发）发现的漏网撤销项 → cancelled 桶"""
        s = json_store.add_set(name="防御组", description="", category="电子")
        carrier = {"task_code": "CARRY-1", "task_name": "带组项", "category": "电子",
                   "task_type": "", "remark": "", "source": "例行", "set_id": s["id"]}
        leak = self._leaked_item()[0]
        cancelled = []
        card_service.propagate_set_data(matched=[carrier],
                                        all_items=[carrier, leak],
                                        new_cards=[leak], cancelled=cancelled)
        assert leak not in [carrier] and leak["status"] == "cancelled"
        assert cancelled and cancelled[0]["task_code"] == "LEAK-1"

    def test_propagate_no_double_append(self, card_service):
        """已在桶内的撤销项不重复追加（身份判断）"""
        item = self._leaked_item()[0]
        cancelled = [item]
        card_service.propagate_set_data(matched=[], all_items=[item],
                                        new_cards=[], cancelled=cancelled)
        assert len(cancelled) == 1


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
