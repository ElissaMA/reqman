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
            "reminder_type": "一般提醒",
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
            "reminder_type": "一般提醒",
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
            "reminder_type": "一般提醒",
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
            "reminder_type": "一般提醒",
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
            "reminder_type": "重点提醒",
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

    def test_edit_ajax_duplicate_code(self, prefilled_client, ajax_headers, store):
        """编辑工卡号撞其他卡已有编号时被拒绝，且双方数据不变"""
        resp = prefilled_client.post(self._edit_url(2), data={
            "task_code": "ENG-001",  # 卡1 已占用
            "task_name": "发动机拆装",
            "category": "发动机",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
            "reminder_type": "一般提醒",
        }, headers=ajax_headers)
        data = resp.get_json()
        assert data["success"] is False
        assert "已存在" in data["message"]
        # 双方工卡号原样保留
        assert store.get(1)["task_code"] == "ENG-001"
        assert store.get(2)["task_code"] == "ENG-002"

    def test_edit_form_no_tools_no_mats(self, prefilled_client, ajax_headers):
        """编辑时确认无工具航材"""
        resp = prefilled_client.post(self._edit_url(1), data={
            "task_name": "无工具航材",
            "category": "发动机",
            "confirm_no_tools": "1",
            "confirm_no_mats": "1",
            "reminder_type": "一般提醒",
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
            "reminder_type": "一般提醒",
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


class TestReminderResetApi:
    def test_reset_card_confirmation(self, client, store):
        # 先新增一张已确认卡（工具/航材/提醒三满足）
        resp = client.post("/card/new", data={
            "task_code": "R-200", "task_name": "卡", "category": "电子",
            "reminder_type": "一般提醒",
            "confirm_no_tools": "1", "confirm_no_mats": "1",
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.get_json()["success"] is True
        card = store.find_by_code("R-200")
        assert card["card_ok"] is True
        resp2 = client.post(f"/card/{card['id']}/reset-confirm",
                            headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp2.get_json()["success"] is True
        assert store.find_by_code("R-200")["card_ok"] is False
        # 内容保留：提醒类型/工具确认未被清空
        assert store.find_by_code("R-200")["reminder_type"] == "一般提醒"


class TestConfirmSymmetry:
    """三块对称确认判定：有数据自动确认/无数据须勾选/提醒选类型即确认"""

    def _post(self, client, task_code="SYM-001", data=None):
        payload = {
            "task_code": task_code,
            "task_name": "对称确认卡",
            "category": "电子",
            "task_type": "A",
        }
        if data:
            payload.update(data)
        return client.post("/card/new", data=payload,
                           headers={"X-Requested-With": "XMLHttpRequest"})

    def test_all_missing_blocks_fail(self, client):
        """工具/航材/提醒均空且未勾选确认 → 校验失败"""
        resp = self._post(client)
        assert resp.get_json()["success"] is False

    def test_data_auto_confirms_three_blocks(self, client, store):
        """有工具/航材数据 + 选提醒类型 → 三块自动确认"""
        resp = self._post(client, task_code="SYM-002", data={
            "tool_name[]": ["扳手"], "tool_pn[]": ["WR-1"], "tool_qty[]": ["1"],
            "mat_name[]": ["润滑油"], "mat_pn[]": ["GRE-1"], "mat_qty[]": ["1瓶"],
            "reminder_type": "一般提醒",
        })
        assert resp.get_json()["success"] is True
        card = store.find_by_code("SYM-002")
        assert card["tools_confirmed"] is True
        assert card["materials_confirmed"] is True
        assert card["reminder_confirmed"] is True

    def test_reminder_type_alone_confirms(self, client, store):
        """选提醒类型即确认提醒（无需勾选确认无需提醒）"""
        resp = self._post(client, task_code="SYM-003", data={
            "confirm_no_tools": "1", "confirm_no_mats": "1",
            "reminder_type": "重点提醒",
        })
        assert resp.get_json()["success"] is True
        card = store.find_by_code("SYM-003")
        assert card["reminder_type"] == "重点提醒"
        assert card["reminder_confirmed"] is True

    def test_confirm_no_reminder_alone(self, client, store):
        """无提醒类型但勾选确认无需提醒 → 提醒确认"""
        resp = self._post(client, task_code="SYM-004", data={
            "confirm_no_tools": "1", "confirm_no_mats": "1",
            "confirm_no_reminder": "1",
        })
        assert resp.get_json()["success"] is True
        card = store.find_by_code("SYM-004")
        assert card["reminder_type"] == ""
        assert card["reminder_confirmed"] is True

    def test_reminder_missing_fails(self, client):
        """无提醒类型且未勾选确认无需提醒 → 校验失败"""
        resp = self._post(client, task_code="SYM-005", data={
            "confirm_no_tools": "1", "confirm_no_mats": "1",
        })
        assert resp.get_json()["success"] is False


class TestWriteDateApi:
    """编写日期（工卡版本日期）：新建/编辑全链路 + 清单列 + 操作日志标签"""

    def _post_new(self, client, task_code="WD-001", extra=None):
        payload = {
            "task_code": task_code, "task_name": "编写日期卡", "category": "电子",
            "confirm_no_tools": "1", "confirm_no_mats": "1",
            "reminder_type": "一般提醒",
        }
        if extra:
            payload.update(extra)
        return client.post("/card/new", data=payload,
                           headers={"X-Requested-With": "XMLHttpRequest"})

    def test_new_card_with_write_date(self, client, store):
        """新建工卡带编写日期 → 入库（YYYY-MM-DD）且清单页显示该列"""
        resp = self._post_new(client, extra={"write_date": "2026-08-05"})
        assert resp.get_json()["success"] is True
        card = store.find_by_code("WD-001")
        assert card["write_date"] == "2026-08-05"
        html = client.get("/card/list").get_data(as_text=True)
        assert "编写日期" in html and "2026-08-05" in html

    def test_new_card_write_date_blank(self, client, store):
        """留空 → 存空串（待 AMRO 同步）"""
        resp = self._post_new(client, task_code="WD-002")
        assert resp.get_json()["success"] is True
        assert store.find_by_code("WD-002")["write_date"] == ""

    def test_edit_card_write_date(self, client, store):
        """编辑工卡可改编写日期，清空则存空"""
        self._post_new(client, task_code="WD-003", extra={"write_date": "2026-08-01"})
        card = store.find_by_code("WD-003")
        resp = client.post(f"/card/{card['id']}/edit", data={
            "task_code": "WD-003", "task_name": "编写日期卡", "category": "电子",
            "confirm_no_tools": "1", "confirm_no_mats": "1",
            "reminder_type": "一般提醒", "write_date": "2026-08-10",
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.get_json()["success"] is True
        assert store.find_by_code("WD-003")["write_date"] == "2026-08-10"
        # 清空 → 空串
        client.post(f"/card/{card['id']}/edit", data={
            "task_code": "WD-003", "task_name": "编写日期卡", "category": "电子",
            "confirm_no_tools": "1", "confirm_no_mats": "1",
            "reminder_type": "一般提醒", "write_date": "",
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        assert store.find_by_code("WD-003")["write_date"] == ""

    def test_invalid_write_date_rejected(self, client):
        """编写日期格式非法 → 校验失败"""
        resp = self._post_new(client, task_code="WD-004", extra={"write_date": "abc"})
        assert resp.get_json()["success"] is False

    def test_operation_log_label(self):
        """操作日志页 write_date 字段显示中文标签"""
        from reqman.blueprints.logs_bp import FIELD_LABELS
        assert FIELD_LABELS["write_date"] == "编写日期"


import reqman.services.amro_sync as amro_sync_mod


class TestCardListLastQuery:
    def test_no_duplicate_download_anchor(self, client, tmp_path, monkeypatch):
        """工卡列表页仅保留规范块下载，不再有冗余的 amroVerDownloadBtn 锚点。"""
        out_dir = tmp_path / "amro_out"
        out_dir.mkdir()
        monkeypatch.setattr(amro_sync_mod, "OUTPUT_DIR", out_dir)
        # 隔离其他用例残留的内存查询状态，确保渲染走持久摘要分支
        monkeypatch.setitem(amro_sync_mod.QUERY_STATUS, "full_version", {})
        (out_dir / "last_query_full_version.json").write_text(
            '{"label":"查询工卡版本","finished_at":"2026-01-01 00:00:00",'
            '"summary":"全量查询工卡版本完成","download_url":"/card/amro-version-report"}',
            encoding="utf-8",
        )
        resp = client.get("/card/list")
        html = resp.get_data(as_text=True)
        assert 'id="amroVerDownloadBtn"' not in html
        assert "amro-version-report" in html
        assert "⬇下载改版清单" in html


class TestCancelledCardsPage:
    """作废工卡子页（数据管理）：列表展示 + 彻底删除"""

    def test_page_renders(self, client):
        resp = client.get("/card/cancelled")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "作废工卡" in html
        assert "/card/cancelled" in html   # 侧边导航子页链接

    def test_lists_cancelled_and_delete(self, app, client):
        """作废记录整卡展示（含原工卡组），删除后从列表消失；不展示作废来源列。"""
        cstore = app.extensions["cancelled_cards"]
        cstore.add({"id": 1, "task_code": "EOJC-X-1", "task_name": "旧卡", "category": "机体",
                    "task_type": "EO", "remark": "", "tools": [], "materials": [],
                    "reminder_type": "重点提醒", "write_date": "2026-01-01"},
                   source="full_version", set_name="组A")
        try:
            html = client.get("/card/cancelled").get_data(as_text=True)
            assert "EOJC-X-1" in html
            assert "组A" in html
            assert "作废来源" not in html   # 清单不再展示作废来源列
            rec = cstore.find_by_code("EOJC-X-1")
            resp = client.post(f"/card/cancelled/{rec['id']}/delete",
                               headers={"X-Requested-With": "XMLHttpRequest"})
            assert resp.get_json()["success"] is True
            assert cstore.find_by_code("EOJC-X-1") is None
            assert "EOJC-X-1" not in client.get("/card/cancelled").get_data(as_text=True)
        finally:
            if cstore.find_by_code("EOJC-X-1"):
                cstore.remove(cstore.find_by_code("EOJC-X-1")["id"])

    def test_delete_nonexistent(self, client):
        resp = client.post("/card/cancelled/999/delete",
                           headers={"X-Requested-With": "XMLHttpRequest"})
        data = resp.get_json()
        assert data["success"] is False
