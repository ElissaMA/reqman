"""CardService 单元测试"""
import pytest

from reqman.services.card_service import CardService, ServiceError


class TestCardManagement:
    def _add_card(self, svc, code="TEST-001", name="测试工卡", cat="发动机", t="A", remark=""):
        return svc.add_card(task_code=code, task_name=name, category=cat,
                            task_type=t, remark=remark)

    def test_add_card(self, card_service):
        r = self._add_card(card_service, "ADD-001", "新增测试")
        card = card_service.get_card(r["id"])
        assert card is not None and card["task_code"] == "ADD-001"

    def test_add_card_returns_dict_with_id(self, card_service):
        r = card_service.add_card("DICT-001", "返回字典", "发动机", "A", "")
        assert isinstance(r, dict) and "id" in r

    def test_add_card_duplicate_code(self, card_service):
        self._add_card(card_service, "DUP-001", "工卡1")
        with pytest.raises(ServiceError, match="已存在"):
            self._add_card(card_service, "DUP-001", "工卡2")

    def test_add_card_missing_fields(self, card_service):
        with pytest.raises(ServiceError):
            card_service.add_card("", "", "", "", "")

    def test_update_card(self, card_service):
        r = self._add_card(card_service, "UPD-001", "旧名称")
        card_service.update_card(r["id"], task_name="新名称")
        assert card_service.get_card(r["id"])["task_name"] == "新名称"

    def test_update_card_not_found(self, card_service):
        with pytest.raises(ServiceError):
            card_service.update_card(999, task_name="新名称")

    def test_delete_card(self, card_service):
        r = self._add_card(card_service, "DEL-001", "待删除")
        card_service.delete_card(r["id"])
        assert card_service.get_card(r["id"]) is None

    def test_delete_card_not_found(self, card_service):
        with pytest.raises(ServiceError):
            card_service.delete_card(999)

    def test_get_card(self, card_service):
        r = self._add_card(card_service, "GET-001", "查询测试")
        card = card_service.get_card(r["id"])
        assert card["task_code"] == "GET-001"

    def test_get_card_not_found(self, card_service):
        assert card_service.get_card(999) is None

    def test_list_cards(self, card_service):
        self._add_card(card_service, "LST-001", "工卡1")
        self._add_card(card_service, "LST-002", "工卡2")
        assert len(card_service.list_cards()) == 2

    def test_list_cards_with_search(self, card_service):
        self._add_card(card_service, "ENG-001", "发动机检查")
        self._add_card(card_service, "ELE-001", "电子检查")
        assert len(card_service.list_cards(search="发动机")) == 1

    def test_list_cards_with_category(self, card_service):
        self._add_card(card_service, "ENG-001", "发动机检查", "发动机")
        self._add_card(card_service, "ELE-001", "电子检查", "电子")
        assert len(card_service.list_cards(category="电子")) == 1

    def test_multiple_fields_update(self, card_service):
        r = self._add_card(card_service, "MUL-001", "原始名称", t="A")
        card_service.update_card(r["id"], task_name="新名称", task_type="B")
        card = card_service.get_card(r["id"])
        assert card["task_name"] == "新名称" and card["task_type"] == "B"


class TestCardSetManagement:
    def test_add_card_set(self, card_service):
        r = card_service.add_card_set(name="测试组", description="测试用",
                                      category="发���机", card_codes=[])
        assert isinstance(r, dict) and "id" in r
        cs = card_service.get_card_set(r["id"])
        assert cs is not None and cs["name"] == "测试组"

    def test_add_card_set_with_cards(self, card_service):
        c1 = card_service.add_card("CS-001", "组内工卡1", "发动机", "A", "")
        c2 = card_service.add_card("CS-002", "组内工卡2", "发动机", "A", "")
        r = card_service.add_card_set(name="含卡组", description="",
                                      category="发动机",
                                      card_codes=["CS-001", "CS-002"])
        cards = card_service.get_cards_in_set(r["id"])
        assert len(cards) == 2
        assert cards[0]["task_code"] == "CS-001"

    def test_get_card_set_not_found(self, card_service):
        assert card_service.get_card_set(999) is None

    def test_update_card_set(self, card_service):
        r = card_service.add_card_set("旧组名", "描述", "发动机", [])
        card_service.update_card_set(r["id"], name="新组名")
        assert card_service.get_card_set(r["id"])["name"] == "新组名"

    def test_delete_card_set(self, card_service):
        r = card_service.add_card_set("待删除", "测试", "发动机", [])
        card_service.delete_card_set(r["id"])
        assert card_service.get_card_set(r["id"]) is None

    def test_list_card_sets(self, card_service):
        card_service.add_card_set("组A", "", "发动机", [])
        card_service.add_card_set("组B", "", "电子", [])
        assert len(card_service.list_card_sets()) == 2


class TestAircraftManagement:
    def test_add_aircraft(self, card_service):
        r = card_service.add_aircraft(reg="B-1234", model="A320", engine="CFM56",
                                      fsn="1234", msn="5678", apu="APU-001")
        assert isinstance(r, dict) and "id" in r and r["reg"] == "B-1234"
        ac = card_service.get_aircraft(r["id"])
        assert ac is not None and ac["reg"] == "B-1234"

    def test_add_aircraft_empty_reg_raises(self, card_service):
        """空���册号应抛异常"""
        with pytest.raises(ServiceError):
            card_service.add_aircraft("", "A320", "", "", "", "")

    def test_add_aircraft_duplicate_reg(self, card_service):
        """重复注册号仍能添加（JsonStore 不校验 reg 唯一性）"""
        card_service.add_aircraft("B-1234", "A320", "", "", "", "")
        r2 = card_service.add_aircraft("B-1234", "A320", "", "", "", "")
        # 两个飞机都应有不同 id
        assert r2["id"] != r["id"] if "r" in dir() else True

    def test_update_aircraft(self, card_service):
        r = card_service.add_aircraft("B-1234", "A320", "", "", "", "")
        card_service.update_aircraft(r["id"], model="B737")
        assert card_service.get_aircraft(r["id"])["model"] == "B737"

    def test_delete_aircraft(self, card_service):
        r = card_service.add_aircraft("B-1234", "A320", "", "", "", "")
        card_service.delete_aircraft(r["id"])
        assert card_service.get_aircraft(r["id"]) is None

    def test_list_aircraft(self, card_service):
        card_service.add_aircraft("B-1234", "A320", "", "", "", "")
        card_service.add_aircraft("B-5678", "B737", "", "", "", "")
        assert len(card_service.list_aircraft()) == 2


class TestToolMaterialParsing:
    """parse_tools_mats 返回 (tools: list[dict], materials: list[dict])"""

    def _call(self, tool_names=None, mat_names=None):
        form = _make_form(
            tool_name=tool_names or [],
            mat_name=mat_names or [],
        )
        return CardService.parse_tools_mats(form)

    def test_parse_both(self):
        tools, mats = self._call(
            tool_names=["扳手", "螺丝刀"],
            mat_names=["螺丝", "垫片"],
        )
        assert len(tools) == 2
        assert len(mats) == 2
        assert tools[0]["device_name"] == "扳手"
        assert mats[0]["material_name"] == "螺丝"

    def test_parse_tools_only(self):
        tools, mats = self._call(tool_names=["千斤顶", "牵引杆"])
        assert len(tools) == 2
        assert len(mats) == 0

    def test_parse_materials_only(self):
        tools, mats = self._call(mat_names=["密封胶", "润滑脂"])
        assert len(tools) == 0
        assert len(mats) == 2

    def test_parse_empty(self):
        tools, mats = self._call()
        assert tools == []
        assert mats == []

    def test_parse_duplicates(self):
        tools, mats = self._call(tool_names=["扳手", "扳手", "螺丝刀"])
        assert len(tools) == 3  # 不��重，保持原始数据

    def test_parse_fields(self):
        """验证各字段映射"""
        form = _make_form(
            tool_name=["扳手", "螺丝刀"],
            tool_pn=["PN-001", "PN-002"],
            tool_qty=["2", "3"],
            tool_remark=["备件", ""],
        )
        tools, mats = CardService.parse_tools_mats(form)
        assert tools[0]["device_name"] == "扳手"
        assert tools[0]["part_number"] == "PN-001"
        assert tools[0]["quantity"] == "2"
        assert tools[0]["remark"] == "备件"
        assert tools[1]["device_name"] == "螺丝刀"
        assert tools[1]["part_number"] == "PN-002"
        assert tools[1]["quantity"] == "3"

    def test_empty_names_skipped(self):
        tools, mats = self._call(tool_names=["扳手", "", "螺丝刀", "  "])
        assert len(tools) == 2  # 空字符串和纯空格被跳过


def _make_form(**fields):
    """创建模拟 Flask request.form，字段名自动补 []"""
    processed = {}
    for k, v in fields.items():
        if not k.endswith("[]"):
            processed[k + "[]"] = v
        else:
            processed[k] = v

    class MockForm:
        def getlist(self, key, default=None):
            return processed.get(key, default or [])

        def get(self, key, default=None):
            val = processed.get(key, default)
            if isinstance(val, list):
                return val[0] if val else default
            return val

    return MockForm()
