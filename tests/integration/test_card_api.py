"""工卡管理 API 集成测试"""



class TestListCards:
    """工卡列表接口测试"""

    def test_list_empty(self, client):
        """空数据库返回空列表页面"""
        resp = client.get("/card/list")
        assert resp.status_code == 200

    def test_list_with_data(self, prefilled_client):
        """预填充后返回工卡列表页面"""
        resp = prefilled_client.get("/card/list")
        assert resp.status_code == 200

    def test_list_all_cards_json(self, prefilled_client):
        """工卡选择器列表端点"""
        resp = prefilled_client.get("/card/list-json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 5

    def test_list_search_by_code(self, prefilled_client):
        """按工卡号搜索"""
        resp = prefilled_client.get("/card/list?search=ENG")
        assert resp.status_code == 200

    def test_list_search_by_name(self, prefilled_client):
        """按工卡名搜索"""
        resp = prefilled_client.get("/card/list?search=蒙皮")
        assert resp.status_code == 200

    def test_list_filter_category(self, prefilled_client):
        """按专业分类筛选"""
        resp = prefilled_client.get("/card/list?category=电子")
        assert resp.status_code == 200

    def test_list_filter_nonexistent_category(self, prefilled_client):
        """不存在的分类返回空"""
        resp = prefilled_client.get("/card/list?category=不存在")
        assert resp.status_code == 200


class TestCardDetail:
    """工卡详情接口测试"""

    def test_detail_existing(self, prefilled_client):
        """获取现有工卡详情"""
        resp = prefilled_client.get("/card/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["task_code"] == "ENG-001"
        assert data["category"] == "发动机"
        assert data["task_name"] == "发动机检查"

    def test_detail_not_found(self, prefilled_client):
        """不存在的工卡返回 404"""
        resp = prefilled_client.get("/card/9999")
        assert resp.status_code == 404

    def test_detail_with_set_info(self, prefilled_app, prefilled_client):
        """已加入工卡组的工卡，详情包含组信息"""
        svc = prefilled_app.extensions['card_service']
        sets = svc.list_card_sets()
        if sets:
            svc.update_card_set(sets[0]["id"], card_codes=["ENG-001"])
        resp = prefilled_client.get("/card/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("set_id") is not None


class TestCreateCard:
    """工卡新增接口测试"""

    CREATE_URL = "/card/new"

    def test_new_form_page(self, client):
        """新增工卡表单页面"""
        resp = client.get(self.CREATE_URL)
        assert resp.status_code == 200

    def test_create_ajax_success(self, prefilled_client, ajax_headers):
        """AJAX 创建工卡成功"""
        resp = prefilled_client.post(self.CREATE_URL, data={
            "task_code": "NEW-001",
            "task_name": "新建工卡",
            "category": "机体",
            "task_type": "A",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_create_ajax_missing_code(self, prefilled_client, ajax_headers):
        """缺少工卡号时返回验证错误"""
        resp = prefilled_client.post(self.CREATE_URL, data={
            "task_name": "无编号工卡",
            "category": "机体",
            "task_type": "A",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False

    def test_create_ajax_duplicate_code(self, prefilled_client, ajax_headers):
        """重复工卡号返回验证错误"""
        resp = prefilled_client.post(self.CREATE_URL, data={
            "task_code": "ENG-001",
            "task_name": "重复工卡",
            "category": "发动机",
            "task_type": "A",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        data = resp.get_json()
        assert data["success"] is False

    def test_create_ajax_with_tools_mats(self, prefilled_client, ajax_headers):
        """创建工卡时同时添加工具和航材"""
        resp = prefilled_client.post(self.CREATE_URL, data={
            "task_code": "TM-001",
            "task_name": "工具航材工卡",
            "category": "电子",
            "task_type": "A",
            "tool_name[]": ["扳手", "螺丝刀"],
            "tool_pn[]": ["WR-001", "SD-001"],
            "tool_qty[]": ["1", "2"],
            "mat_name[]": ["润滑油", "密封胶"],
            "mat_pn[]": ["GRE-001", "SEAL-001"],
            "mat_qty[]": ["1瓶", "2支"],
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_create_form_redirect(self, prefilled_client):
        """表单提交（非 AJAX）重定向到列表页面"""
        resp = prefilled_client.post(self.CREATE_URL, data={
            "task_code": "FORM-001",
            "task_name": "表单提交工卡",
            "category": "机体",
            "task_type": "A",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        })
        assert resp.status_code in (302, 200)


class TestEditCard:
    """工卡编辑接口测试"""

    def _edit_url(self, card_id):
        return f"/card/{card_id}/edit"

    def test_edit_form_page(self, prefilled_client):
        """编辑表单页面"""
        resp = prefilled_client.get(self._edit_url(1))
        assert resp.status_code == 200

    def test_edit_ajax_success(self, prefilled_client, ajax_headers):
        """AJAX 编辑工卡成功"""
        resp = prefilled_client.post(self._edit_url(1), data={
            "task_name": "发动机检查(更新)",
            "category": "发动机",
            "task_type": "B",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_edit_ajax_update_tools(self, prefilled_client, ajax_headers):
        """AJAX 编辑时更新工具航材"""
        resp = prefilled_client.post(self._edit_url(1), data={
            "task_name": "带工具的工卡",
            "category": "发动机",
            "tool_name[]": ["新工具"],
            "tool_pn[]": ["NT-001"],
            "tool_qty[]": ["1"],
            "mat_name[]": ["新航材"],
            "mat_pn[]": ["NM-001"],
            "mat_qty[]": ["1个"],
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_edit_not_found(self, prefilled_client, ajax_headers):
        """编辑不存在的工卡返回重定向"""
        resp = prefilled_client.post(self._edit_url(9999), data={
            "task_name": "不存在",
        }, headers=ajax_headers)
        assert resp.status_code == 302

    def test_edit_form_no_tools_no_mats(self, prefilled_client, ajax_headers):
        """编辑时确认无工具航材"""
        resp = prefilled_client.post(self._edit_url(1), data={
            "task_name": "无工具航材",
            "category": "发动机",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


class TestDeleteCard:
    """工卡删除接口测试"""

    def _delete_url(self, card_id):
        return f"/card/{card_id}/delete"

    def test_delete_ajax_success(self, prefilled_client, ajax_headers):
        """AJAX 删除工卡成功"""
        resp = prefilled_client.post(self._delete_url(1),
                                      headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_delete_really_removed(self, prefilled_client, ajax_headers):
        """删除后工卡不再出现在列表中"""
        prefilled_client.post(self._delete_url(1), headers=ajax_headers)
        resp = prefilled_client.get("/card/1")
        assert resp.status_code == 404

    def test_delete_not_found(self, prefilled_client, ajax_headers):
        """删除不存在的工卡返回错误（AJAX 返回 200+success:false，非AJAX 返回 302）"""
        resp = prefilled_client.post(self._delete_url(9999),
                                      headers=ajax_headers)
        data = resp.get_json()
        assert data["success"] is False


class TestCardSetAPI:
    """工卡组管理接口测试"""

    SET_LIST_URL = "/card/sets"

    def test_list_sets(self, prefilled_client):
        """工卡组列表返回 HTML 页面"""
        resp = prefilled_client.get(self.SET_LIST_URL)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_list_sets_empty(self, client):
        """空数据库返回空工卡组页面"""
        resp = client.get(self.SET_LIST_URL)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_new_set_ajax(self, prefilled_client, ajax_headers):
        """AJAX 创建工卡组成功"""
        resp = prefilled_client.post("/card/sets/new", data={
            "name": "集成测试组",
            "description": "由集成测试创建",
            "category": "发动机",
            "card_codes[]": ["A320-TEST-001", "A320-TEST-002"],
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


class TestAircraftAPI:
    """飞机信息管理接口测试"""

    AIRCRAFT_URL = "/card/aircraft"

    def test_list_aircraft(self, prefilled_client):
        """飞机信息列表返回 HTML 页面"""
        resp = prefilled_client.get(self.AIRCRAFT_URL)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_new_aircraft(self, prefilled_client):
        """新增飞机"""
        resp = prefilled_client.post("/card/aircraft/new", data={
            "reg": "B-9999",
            "model": "A330",
            "engine": "TRENT700",
        })
        assert resp.status_code == 302

    def test_delete_aircraft(self, prefilled_client):
        """删除飞机"""
        resp = prefilled_client.post("/card/aircraft/1/delete")
        assert resp.status_code == 302
