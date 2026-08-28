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
        _c1 = card_service.add_card("CS-001", "组内工卡1", "发动机", "A", "")
        _c2 = card_service.add_card("CS-002", "组内工卡2", "发动机", "A", "")
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


class TestSetConfirmedSync:
    """sync_set_to_cards：工卡组 tools_confirmed/materials_confirmed 同步到子卡"""

    def _add_set_with_cards(self, svc, confirmed_t=False, confirmed_m=False,
                            tools=None, materials=None):
        """创建2张卡 + 1个含它们的工卡组，返回 (set_id, [card_ids])"""
        c1 = svc.add_card("SYNC-001", "同步卡1", "发动机", "A", "")
        c2 = svc.add_card("SYNC-002", "同步卡2", "发动机", "A", "")
        r = svc.add_card_set(name="同步组", description="", category="发动机",
                             card_codes=["SYNC-001", "SYNC-002"],
                             tools=tools, materials=materials,
                             tools_confirmed=confirmed_t,
                             materials_confirmed=confirmed_m)
        return r["id"], [c1["id"], c2["id"]]

    def test_new_set_syncs_confirmed_to_cards(self, card_service):
        """新建工卡组：tools/materials_confirmed=True 同步到组内所有子卡"""
        _set_id, card_ids = self._add_set_with_cards(
            card_service, confirmed_t=True, confirmed_m=True)
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["tools_confirmed"] is True
            assert card["materials_confirmed"] is True

    def test_new_set_default_confirmed_false(self, card_service):
        """新建工卡组：默认 confirmed=False，子卡同步为 False"""
        _set_id, card_ids = self._add_set_with_cards(card_service)
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["tools_confirmed"] is False
            assert card["materials_confirmed"] is False

    def test_new_set_syncs_tools_materials(self, card_service):
        """新建工卡组：tools/materials 列表同步到组内子卡"""
        tools = [{"device_name": "扳手", "part_number": "W-001"}]
        materials = [{"material_name": "密封胶", "part_number": "M-001"}]
        _set_id, card_ids = self._add_set_with_cards(
            card_service, tools=tools, materials=materials)
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["tools"] == tools
            assert card["materials"] == materials

    def test_update_set_syncs_confirmed_to_cards(self, card_service):
        """编辑工卡组：修改 tools/materials_confirmed 后子卡同步更新"""
        set_id, card_ids = self._add_set_with_cards(card_service)
        card_service.update_card_set(set_id, tools_confirmed=True,
                                     materials_confirmed=True)
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["tools_confirmed"] is True
            assert card["materials_confirmed"] is True

    def test_update_set_keep_confirmed_when_not_changed(self, card_service):
        """编辑工卡组：不传 confirmed（None）时子卡保持原值"""
        set_id, card_ids = self._add_set_with_cards(
            card_service, confirmed_t=True, confirmed_m=True)
        card_service.update_card_set(set_id, name="改名")  # 不动 confirmed
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["tools_confirmed"] is True
            assert card["materials_confirmed"] is True

    def test_sync_does_not_affect_cards_outside_set(self, card_service):
        """同步不影响组外卡（set_id 不匹配）"""
        outside = card_service.add_card("SYNC-OUT-001", "组外卡", "发动机", "A", "")
        card_service.add_card_set(name="空组", description="", category="发动机",
                                  card_codes=[], tools_confirmed=True,
                                  materials_confirmed=True)
        card = card_service.get_card(outside["id"])
        assert card["tools_confirmed"] is False
        assert card["materials_confirmed"] is False


class TestSetCategorySync:
    """sync_set_to_cards：工卡组 category 同步到子卡"""

    def _add_set_with_cards(self, svc, category="发动机"):
        """创建2张卡 + 1个含它们的工卡组，返回 (set_id, [card_ids])"""
        c1 = svc.add_card("CAT-001", "分类卡1", "机体", "A", "")
        c2 = svc.add_card("CAT-002", "分类卡2", "机体", "A", "")
        r = svc.add_card_set(name="分类组", description="", category=category,
                             card_codes=["CAT-001", "CAT-002"])
        return r["id"], [c1["id"], c2["id"]]

    def test_new_set_syncs_category_to_cards(self, card_service):
        """新建工卡组：category 同步到组内所有子卡（覆盖子卡原分类）"""
        _set_id, card_ids = self._add_set_with_cards(card_service, category="电子")
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["category"] == "电子"

    def test_new_set_default_category_synced(self, card_service):
        """新建工卡组：add_card_set 默认 category='机体' 同步到子卡"""
        c1 = card_service.add_card("CAT-DEF-001", "默认卡1", "发动机", "A", "")
        c2 = card_service.add_card("CAT-DEF-002", "默认卡2", "发动机", "A", "")
        r = card_service.add_card_set(name="默认组", description="",
                                      card_codes=["CAT-DEF-001", "CAT-DEF-002"])
        assert r["category"] == "机体"
        for cid in [c1["id"], c2["id"]]:
            card = card_service.get_card(cid)
            assert card["category"] == "机体"  # 默认分类覆盖子卡原分类

    def test_update_set_syncs_category_to_cards(self, card_service):
        """编辑工卡组：修改 category 后子卡同步更新"""
        set_id, card_ids = self._add_set_with_cards(card_service, category="电子")
        card_service.update_card_set(set_id, category="发动机")
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["category"] == "发动机"

    def test_update_set_keep_category_when_not_changed(self, card_service):
        """编辑工卡组：不传 category（空串）时子卡保持原值"""
        set_id, card_ids = self._add_set_with_cards(card_service, category="电子")
        card_service.update_card_set(set_id, name="改名")  # 不动 category
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["category"] == "电子"

    def test_update_set_other_fields_keep_category(self, card_service):
        """编辑工卡组：只改工具/航材不动 category，子卡分类保持"""
        set_id, card_ids = self._add_set_with_cards(card_service, category="电子")
        tools = [{"device_name": "扳手", "part_number": "W-001"}]
        card_service.update_card_set(set_id, tools=tools)
        for cid in card_ids:
            card = card_service.get_card(cid)
            assert card["category"] == "电子"
            assert card["tools"] == tools

    def test_sync_category_does_not_affect_cards_outside_set(self, card_service):
        """category 同步不影响组外卡（set_id 不匹配）"""
        outside = card_service.add_card("CAT-OUT-001", "组外卡", "机体", "A", "")
        card_service.add_card_set(name="空组", description="", category="电子",
                                  card_codes=[])
        card = card_service.get_card(outside["id"])
        assert card["category"] == "机体"


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
        """重复注册号应拒绝（find_aircraft_by_reg 依赖机号唯一性，v3.4.5 起）"""
        card_service.add_aircraft("B-1234", "A320", "", "", "", "")
        with pytest.raises(ServiceError):
            card_service.add_aircraft("B-1234", "A320", "", "", "", "")

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
        tools, _mats = self._call(tool_names=["扳手", "扳手", "螺丝刀"])
        assert len(tools) == 3  # 不��重，保持原始数据

    def test_parse_fields(self):
        """验证各字段映射"""
        form = _make_form(
            tool_name=["扳手", "螺丝刀"],
            tool_pn=["PN-001", "PN-002"],
            tool_qty=["2", "3"],
            tool_remark=["备件", ""],
        )
        tools, _mats = CardService.parse_tools_mats(form)
        assert tools[0]["device_name"] == "扳手"
        assert tools[0]["part_number"] == "PN-001"
        assert tools[0]["quantity"] == "2"
        assert tools[0]["remark"] == "备件"
        assert tools[1]["device_name"] == "螺丝刀"
        assert tools[1]["part_number"] == "PN-002"
        assert tools[1]["quantity"] == "3"

    # ---------- 3.2.4：数量无默认（空存空，不再默认"1"） ----------

    def test_quantity_empty_when_missing(self):
        """未填数量 → 存空字符串（不默认"1"）"""
        tools, _mats = self._call(tool_names=["扳手"])
        assert tools[0]["quantity"] == ""

    def test_quantity_empty_when_blank(self):
        """数量为空白/不可见字符 → 存空字符串"""
        for blank in ("", "  ", "\u3000", "\u200b"):
            form = _make_form(tool_name=["扳手"], tool_qty=[blank])
            tools, _mats = CardService.parse_tools_mats(form)
            assert tools[0]["quantity"] == "", f"blank={blank!r} 应存空"

    def test_quantity_trimmed(self):
        """数量两侧空白被清理"""
        form = _make_form(tool_name=["扳手"], tool_qty=[" 5 "])
        tools, _mats = CardService.parse_tools_mats(form)
        assert tools[0]["quantity"] == "5"

    def test_quantity_empty_material(self):
        """航材数量同样空存空"""
        _tools, mats = self._call(mat_names=["垫片"])
        assert mats[0]["quantity"] == ""

    def test_empty_names_skipped(self):
        tools, _mats = self._call(tool_names=["扳手", "", "螺丝刀", "  "])
        assert len(tools) == 2  # 空字符串和纯空格被跳过

    # ---------- 任务 #019ff49b：不可见字符（零宽/全角空格）处理 ----------

    @pytest.mark.parametrize("invisible", ["\u200b", "\u200c", "\u200d", "\ufeff", "\u3000"])
    def test_usage_type_invisible_falls_back(self, invisible):
        """usage_type 为零宽/全角等不可见字符 → 兜底为"必须使用" """
        form = _make_form(tool_name=["扳手"], tool_type=[invisible])
        tools, _mats = CardService.parse_tools_mats(form)
        assert tools[0]["usage_type"] == "必须使用"

    def test_usage_type_blank_falls_back(self):
        """usage_type 纯空白 → 兜底为"必须使用"（与空值一致）"""
        form = _make_form(tool_name=["扳手"], tool_type=["   "])
        tools, _mats = CardService.parse_tools_mats(form)
        assert tools[0]["usage_type"] == "必须使用"

    def test_usage_type_normal_kept(self):
        form = _make_form(tool_name=["扳手"], tool_type=["工具房"])
        tools, _mats = CardService.parse_tools_mats(form)
        assert tools[0]["usage_type"] == "工具房"

    @pytest.mark.parametrize("invisible", ["\u200b", "\u3000", "\ufeff"])
    def test_half_empty_name_invisible_raises(self, invisible):
        """名称是不可见字符但件号/数量等有值 → 半空行必须拒绝"""
        form = _make_form(tool_name=[invisible], tool_pn=["PN-001"], tool_qty=["1"])
        with pytest.raises(ServiceError, match="缺少名称"):
            CardService.parse_tools_mats(form)

    @pytest.mark.parametrize("invisible", ["\u200b", "\u3000", "\ufeff"])
    def test_invisible_name_only_skipped(self, invisible):
        """名称是不可见字符且其他字段全空 → 视为空行跳过，不产生幽灵数据"""
        form = _make_form(tool_name=[invisible])
        tools, _mats = CardService.parse_tools_mats(form)
        assert tools == []


class TestReminderValidation:
    def test_add_with_reminder_type_ok(self, card_service: CardService):
        card = card_service.add_card("R-101", "提醒卡", category="电子",
                                     tools_confirmed=True, materials_confirmed=True,
                                     reminder_type="一般提醒", card_ok=True)
        assert card["reminder_type"] == "一般提醒"
        assert card["card_ok"] is True

    def test_add_with_reminder_confirmed_ok(self, card_service: CardService):
        card = card_service.add_card("R-102", "卡", category="电子",
                                     tools_confirmed=True, materials_confirmed=True,
                                     reminder_confirmed=True, card_ok=True)
        assert card["reminder_confirmed"] is True

    def test_reset_confirmation_keeps_content(self, card_service: CardService):
        card = card_service.add_card("R-103", "卡", category="电子",
                                     tools_confirmed=True, materials_confirmed=True,
                                     reminder_type="重点提醒", card_ok=True)
        updated = card_service.update_card(card["id"], card_ok=False)
        assert updated["card_ok"] is False
        assert updated["reminder_type"] == "重点提醒"   # 内容保留
        assert updated["tools"] == []                    # 工具内容保留


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
