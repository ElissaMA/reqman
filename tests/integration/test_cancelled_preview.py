"""工作清单撤销项在预览中可见、在匹配和导出中不可见。"""

import io

import openpyxl

from reqman.services.amro_sync.packages import package_items
from reqman.services.work_package_matcher import is_cancelled_item

AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _rematch(client, package_id):
    """匹配只在「重新匹配」时发生：预览/下载前必须先匹配。"""
    resp = client.post(f"/packages/{package_id}/rematch", headers=AJAX)
    assert resp.status_code == 200 and resp.get_json()["success"]
    return resp


def _package(items, description):
    return {
        "reg": "B-8162", "description": description, "date": "2026-11-05",
        "aircraft_info": {"reg": "B-8162", "description": description,
                          "type": "A320-214", "date": "2026-11-05"},
        "all_items": items,
    }


def _amro_row(code, name, remark="", condition="N"):
    return {"JCNO": code, "JCTITLE": name, "TASK": "RST", "ZY": "机身",
            "PPCBZSM": remark, "CONDITION": condition}


def test_amro_revoked_preview_and_export_exclusion(client, store):
    """模拟 AMRO 例行/其他导入：撤销项仅在预览可见，三个匹配桶互斥。"""
    code = "CSCA320-CANCEL-001"
    normal = _amro_row("CSCA320-ACTIVE-002", "正常卡")
    revoked = _amro_row(code, "撤销卡", "已撤销|计划调整")
    parsed = package_items([_amro_row(code, "旧版正常卡"), normal], [revoked])
    pkg = store.save_work_package(_package(parsed["all_items"], "撤销预览测试包"))
    package_id = pkg["package_id"]
    _rematch(client, package_id)

    response = client.get(f"/generate?package_id={package_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<h2>新工卡</h2>" in html
    assert "<h2>撤销工卡</h2>" in html
    assert html.index("<h2>新工卡</h2>") < html.index("<h2>撤销工卡</h2>")
    assert "撤销卡" in html
    assert "旧版正常卡" not in html  # 同号撤销项应覆盖先到的正常项
    assert "正常卡" in html
    # 撤销区不再展示类别与撤销依据/备注列
    cancelled_section = html[html.index("<h2>撤销工卡</h2>"):]
    assert "撤销依据/备注" not in cancelled_section[:2000]
    assert "<th>类别</th>" not in cancelled_section[:2000]

    saved = store.get_work_package(package_id)
    assert [item["task_code"] for item in saved["cancelled"] if is_cancelled_item(item)] == [code]
    assert code not in {item["task_code"] for item in saved["matched"] + saved["new_cards"]}
    preview = client.get(f"/generate?package_id={package_id}",
                         headers={"X-Requested-With": "XMLHttpRequest"}).get_json()["data"]
    assert preview["cancelled_count"] == 1

    exported = client.post("/generate", data={"package_id": package_id, "reg": "B-8162",
                                              "date": "2026-11-05"})
    assert exported.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(exported.data), read_only=True, data_only=True)
    try:
        cells = (str(cell) for sheet in wb for row in sheet.iter_rows(values_only=True)
                 for cell in row if cell is not None)
        assert not any(code in text or "撤销卡" in text for text in cells)
    finally:
        wb.close()


def test_condition_revoked_preview_and_export_exclusion(client, store):
    """AMRO CONDITION=D、备注为空时仍能识别撤销，不进入需求单。"""
    code = "CSCA320-STATUS-CANCEL-004"
    parsed = package_items([_amro_row(code, "状态撤销卡", condition="D"),
                            _amro_row("CSCA320-STATUS-NORMAL-005", "新增卡", condition="N")], [])
    pkg = store.save_work_package(_package(parsed["all_items"], "状态撤销预览测试包"))
    package_id = pkg["package_id"]
    _rematch(client, package_id)
    response = client.get(f"/generate?package_id={package_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "状态撤销卡" in html
    saved = store.get_work_package(package_id)
    assert saved["cancelled_count"] == 1
    assert code not in {item["task_code"] for item in saved["matched"] + saved["new_cards"]}
    exported = client.post("/generate", data={"package_id": package_id, "reg": "B-8162",
                                              "date": "2026-11-05"})
    assert exported.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(exported.data), read_only=True, data_only=True)
    try:
        assert not any(code in str(cell) or "状态撤销卡" in str(cell)
                       for sheet in wb for row in sheet.iter_rows(values_only=True)
                       for cell in row if cell is not None)
    finally:
        wb.close()


def test_unmatched_package_preview_is_blocked(client, store):
    """未匹配工作包访问预览不触发匹配，返回 409 提示先重新匹配。"""
    item = package_items([_amro_row("CACHE-CANCEL-1", "缓存撤销", condition="D")], [])["all_items"][0]
    pkg = store.save_work_package(_package([item], "未匹配预览测试包"))

    resp = client.get(f"/generate?package_id={pkg['package_id']}", headers=AJAX)
    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "PACKAGE_NOT_MATCHED"

    html = client.get(f"/generate?package_id={pkg['package_id']}").get_data(as_text=True)
    assert "工作包尚未匹配" in html

    saved = store.get_work_package(pkg["package_id"])
    assert not saved.get("matched")           # 预览不得落库匹配结果
    assert not saved.get("is_matched")


def test_legacy_amro_rematch_matches_without_amro_refresh(client, store, monkeypatch):
    """旧包重新匹配不再提示旧版、不再访问 AMRO；直接按当前数据库匹配并保留原包 ID。"""
    from reqman.services import amro_sync

    code = "CSCA320-275449-06-1-X"
    description = "旧 AMRO 详情状态测试包"
    old_item = {"task_code": code, "task_name": "襟翼作动筒排放并重新用半流体注油",
                "remark": "该工作涉及双重维修|", "category": "机体", "task_type": "RST",
                "source": "例行", "cancelled": False}
    old_pkg = _package([old_item], description)
    old_pkg["aircraft_info"]["package"] = "10673997"
    pkg = store.save_work_package({**old_pkg, "source": "AMRO", "is_matched": True,
                                   "matched": [old_item], "new_cards": [], "cancelled": []})
    package_id = pkg["package_id"]
    headers = {"X-Requested-With": "XMLHttpRequest"}

    def _no_amro(*args, **kwargs):
        raise AssertionError("重新匹配不应访问 AMRO")

    monkeypatch.setattr(amro_sync, "require_amro_session", _no_amro)
    monkeypatch.setattr(amro_sync, "list_amro_packages", _no_amro)
    monkeypatch.setattr(amro_sync, "fetch_amro_package_items", _no_amro)

    rematch = client.post(f"/packages/{package_id}/rematch", headers=headers)
    assert rematch.status_code == 200 and rematch.get_json()["success"]
    assert rematch.get_json()["message"] == "重新匹配完成"
    saved = store.get_work_package(package_id)
    assert saved["package_id"] == package_id
    assert saved["is_matched"] is True
    assert code in {item["task_code"] for item in saved["matched"] + saved["new_cards"]}


def test_preview_card_tables_share_three_leading_columns(client, store):
    """新工卡区与撤销区前三列宽一致（colgroup 固定像素）。"""
    import re

    cancelled = package_items([_amro_row("CXL-1", "撤销卡", condition="D")], [])["all_items"]
    pkg = store.save_work_package(_package(cancelled, "列宽一致性测试包"))
    _rematch(client, pkg["package_id"])
    html = client.get(f"/generate?package_id={pkg['package_id']}").get_data(as_text=True)

    tables = re.findall(
        r'<table class="table table-bordered table-sm mb-0 preview-card-table"><colgroup>(.*?)</colgroup>',
        html)
    assert len(tables) == 2
    for colgroup in tables:
        assert "col-card-code" in colgroup
        assert "col-card-name" in colgroup
        assert "col-card-category" in colgroup
    assert tables[1].count("<col") == 3  # 撤销区三列
    assert tables[0].count("<col") == 5  # 新工卡区五列


def test_db_cancelled_not_shown_as_list_revocation(client, store):
    """本地数据库已作废不等于工作清单撤销，不在预览撤销区出现。"""
    card = store.add("CSCA320-DB-003", "数据库作废卡", "机体", "RST", "")
    store.mark_cancelled(card["id"], source="full_version", set_name="")
    parsed = package_items([_amro_row(card["task_code"], "数据库作废卡")], [])
    pkg = store.save_work_package(_package(parsed["all_items"], "本地作废预览测试包"))
    _rematch(client, pkg["package_id"])
    response = client.get(f"/generate?package_id={pkg['package_id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "工作清单中无撤销工卡" in html
    assert "数据库作废卡" not in html
    saved = store.get_work_package(pkg["package_id"])
    assert not saved["matched"] and not saved["new_cards"]
