"""借用清单路由集成测试（/generate/tool-list、/generate/chemical-list）"""
import io

import openpyxl


def _make_package(store):
    """一个已匹配包：发动机/电子卡各一张，含工具与开封航化航材"""
    store.add(task_code="CSCA320-256652-01-1-X", task_name="检查救生衣",
              category="发动机", task_type="RST")
    store.update(store.find_by_code("CSCA320-256652-01-1-X")["id"],
                 tools=[{"device_name": "内六角扳手", "part_number": "PN-T1",
                         "quantity": "2", "remark": "", "usage_type": "必须使用"}],
                 materials=[{"material_name": "密封胶 MQ-1", "part_number": "PN-M1",
                             "quantity": "2", "remark": "优先使用开封航化",
                             "usage_type": "必须使用"}],
                 tools_confirmed=True, materials_confirmed=True,
                 reminder_type="一般提醒", reminder_confirmed=True, card_ok=True)
    return store.save_work_package({
        "reg": "B-1234", "description": "46A", "date": "2026.09.06",
        "aircraft_info": {"reg": "B-1234", "type": "A320", "description": "46A",
                          "date": "2026.09.06"},
        "matched": [{"task_code": "CSCA320-256652-01-1-X", "task_name": "检查救生衣",
                     "category": "发动机", "set_id": None, "set_name": "",
                     "task_type": "RST", "card_ok": True,
                     "reminder_type": "一般提醒", "reminder_confirmed": True,
                     "tools": [{"device_name": "内六角扳手", "part_number": "PN-T1",
                                "quantity": "2", "remark": "", "usage_type": "必须使用"}],
                     "materials": [{"material_name": "密封胶 MQ-1", "part_number": "PN-M1",
                                    "quantity": "2", "remark": "优先使用开封航化",
                                    "usage_type": "必须使用"}]}],
        "new_cards": [], "cancelled": [], "all_items": [],
        "routine_count": 1, "other_count": 0,
        "is_matched": True, "generated_at": "2026.09.06 10:00",
    })["package_id"]


class TestChecklistApi:
    def test_tool_list_download(self, client, store):
        pkg_id = _make_package(store)
        resp = client.post("/generate/tool-list", data={"package_id": pkg_id})
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.mimetype
        from urllib.parse import unquote
        assert "定检中队零散工具借用清单" in unquote(resp.headers["Content-Disposition"])
        wb = openpyxl.load_workbook(io.BytesIO(resp.data))
        ws = wb["定检工具"]
        assert ws["B19"].value == "内六角扳手"     # 发动机区首行
        assert ws["D19"].value == "2"

    def test_chemical_list_download(self, client, store):
        pkg_id = _make_package(store)
        resp = client.post("/generate/chemical-list", data={"package_id": pkg_id})
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.mimetype
        from urllib.parse import unquote
        assert "定检中队开封航化借用清单" in unquote(resp.headers["Content-Disposition"])
        wb = openpyxl.load_workbook(io.BytesIO(resp.data))
        ws = wb["定检航化"]
        assert ws["B18"].value == "密封胶 MQ-1"    # 非例行区首行

    def test_missing_package_id_400(self, client):
        resp = client.post("/generate/tool-list", data={})
        assert resp.status_code == 400

    def test_unknown_package_404(self, client, ajax_headers):
        resp = client.post("/generate/chemical-list", data={"package_id": "nope"},
                           headers=ajax_headers)
        assert resp.status_code == 404
