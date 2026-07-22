"""工卡管理 API 集成测试"""

import json


class TestListCards:
    """工卡列表接口���试"""

    def test_list_empty(self, client, ajax_headers):
        """空数���库返回空列表"""
        resp = client.get("/card/api/list", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["items"] == []
        assert data["data"]["pagination"]["total"] == 0

    def test_list_with_data(self, prefilled_client, ajax_headers):
        """预填充后返回工卡列表"""
        resp = prefilled_client.get("/card/api/list", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["data"]["items"]) == 5
        assert data["data"]["pagination"]["total"] == 5

    def test_list_all_cards_json(self, prefilled_client, ajax_headers):
        """工卡选择器列��端点"""
        resp = prefilled_client.get("/card/list-json", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["data"]) == 5

    def test_list_search_by_code(self, prefilled_client, ajax_headers):
        """按工卡号搜索"""
        resp = prefilled_client.get("/card/api/list?search=ENG",
                                     headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["items"]) == 2
        for item in data["data"]["items"]:
            assert "ENG" in item["task_code"]

    def test_list_search_by_name(self, prefilled_client, ajax_headers):
        """按工卡���搜索"""
        resp = prefilled_client.get("/card/api/list?search=蒙皮",
                                     headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["task_code"] == "AIR-001"

    def test_list_filter_category(self, prefilled_client, ajax_headers):
        """按专业分类筛选"""
        resp = prefilled_client.get("/card/api/list?category=电子",
                                     headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["category"] == "电子"

    def test_list_filter_nonexistent_category(self, prefilled_client, ajax_headers):
        """不存在的���类返回空"""
        resp = prefilled_client.get("/card/api/list?category=不存在",
                                     headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["items"] == []

    def test_list_pagination(self, prefilled_client, ajax_headers):
        """分页参数正常工作"""
        resp = prefilled_client.get("/card/api/list?page=1&per_page=2",
                                     headers=ajax_headers)
        data = resp.get_json()
        assert len(data["data"]["items"]) == 2
        assert data["data"]["pagination"]["page"] == 1
        assert data["data"]["pagination"]["per_page"] == 2
        assert data["data"]["pagination"]["total"] == 5
        assert data["data"]["pagination"]["total_pages"] == 3

    def test_list_pagination_page_out_of_range(self, prefilled_client, ajax_headers):
        """超出范围的页号被钳位到最后一页"""
        resp = prefilled_client.get("/card/api/list?page=99",
                                     headers=ajax_headers)
        data = resp.get_json()
        # API 将 page 钳位到 total_pages，不会返回空
        assert data["data"]["pagination"]["page"] == 1
        assert data["data"]["pagination"]["total_pages"] == 1


class TestCardDetail:
    """工卡详情接口测试"""

    def test_detail_existing(self, prefilled_client, ajax_headers):
        """获取现有工卡详情"""
        resp = prefilled_client.get("/card/1", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        card = data["data"]
        assert card["task_code"] == "ENG-001"
        assert card["category"] == "发动机"
        assert card["task_name"] == "发动机检查"

    def test_detail_not_found(self, prefilled_client, ajax_headers):
        """不存在的工卡返回 404"""
        resp = prefilled_client.get("/card/9999", headers=ajax_headers)
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["success"] is False
        assert data["error_code"] == "NOT_FOUND"

    def test_detail_with_set_info(self, prefilled_app, prefilled_client, ajax_headers):
        """已加入工卡组的工卡，详情包含组信��"""
        svc = prefilled_app.extensions['card_service']
        # 将 ENG-001 加入第一个工��组
        sets = svc.list_card_sets()
        if sets:
            svc.update_card_set(sets[0]["id"], card_codes=["ENG-001"])
        resp = prefilled_client.get("/card/1", headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"].get("set_id") is not None


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
            "task_name": "��建工卡",
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
        assert resp.status_code == 400
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
        assert resp.status_code in (400, 409)
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
            "task_name": "带工具���工卡",
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
        """编辑不存在的���卡返回重定向"""
        resp = prefilled_client.post(self._edit_url(9999), data={
            "task_name": "不存在",
        }, headers=ajax_headers)
        # 不存在的工卡触发 flash + redirect，不返回 JSON
        assert resp.status_code == 302

    def test_edit_form_validation_error(self, prefilled_client, ajax_headers):
        """编辑时缺少必要字段返回验证错误"""
        resp = prefilled_client.post(self._edit_url(1), data={
            "task_name": "",
        }, headers=ajax_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False


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
        resp = prefilled_client.get("/card/1", headers=ajax_headers)
        assert resp.status_code == 404

    def test_delete_not_found(self, prefilled_client, ajax_headers):
        """删除不存在的工���返回 400"""
        resp = prefilled_client.post(self._delete_url(9999),
                                      headers=ajax_headers)
        # delete_card 抛出 ServiceError��handler 返回 api_error (400)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False


class TestCardSetAPI:
    """工卡组管理接口测试"""

    SET_LIST_URL = "/card/sets"

    def test_list_sets(self, prefilled_client, ajax_headers):
        """工卡组列表返回 HTML 页面"""
        resp = prefilled_client.get(self.SET_LIST_URL, headers=ajax_headers)
        # /card/sets 返回 HTML 渲染页面，不是 JSON
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_list_sets_empty(self, client, ajax_headers):
        """空数据库返回空工卡���页面"""
        resp = client.get(self.SET_LIST_URL, headers=ajax_headers)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_new_set_ajax(self, prefilled_client, ajax_headers):
        """AJAX 创建工卡组成功"""
        resp = prefilled_client.post("/card/sets/new", data={
            "name": "集成测试组",
            "description": "由集成测试创建",
            "category": "发动机",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
        }, headers=ajax_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


class TestAircraftAPI:
    """飞机信息管理接口测试"""

    AIRCRAFT_URL = "/card/aircraft"

    def test_list_aircraft(self, prefilled_client, ajax_headers):
        """飞机信息列表返回 HTML 页面"""
        resp = prefilled_client.get(self.AIRCRAFT_URL, headers=ajax_headers)
        # /card/aircraft 返回 HTML 渲染页面
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_new_aircraft_ajax(self, prefilled_client, ajax_headers):
        """新增���机（即使 AJAX 也返回重定向）"""
        resp = prefilled_client.post("/card/aircraft/new", data={
            "reg": "B-9999",
            "model": "A330",
            "engine": "TRENT700",
        }, headers=ajax_headers)
        # 飞���新增总是返回 302 重定向，不支持 AJAX 响应
        assert resp.status_code == 302

    def test_delete_aircraft_ajax(self, prefilled_client, ajax_headers):
        """删除飞机（即使 AJAX 也返回重定向）"""
        resp = prefilled_client.post("/card/aircraft/1/delete",
                                      headers=ajax_headers)
        # 飞机删除总是返回 302 重定向
        assert resp.status_code == 302
