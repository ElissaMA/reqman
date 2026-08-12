"""e2e 有头浏览器测试（pytest-playwright，7用例）。

覆盖：页面渲染 / 弹窗编辑(保存成功toast) / 弹窗新增 / 校验toast(空专业·半空行·未勾选确认)
      / cardId编辑URL / 上传无文件 / 日志分页导航。

运行：
    venv\\Scripts\\python.exe -m pytest tests/e2e -m e2e -v
"""
import json
import re
import uuid

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------- 1. 页面渲染 ----------
def test_pages_render(page, server_base):
    """列表/表单/详情页 200 + 无JS错误。"""
    js_errors = []
    page.on("pageerror", lambda e: js_errors.append(str(e)))

    # 列表页
    resp = page.goto(server_base + "/card/list")
    assert resp.status == 200, "列表页非200"
    page.wait_for_selector("#cardTable tbody tr")

    # 表单页
    resp = page.goto(server_base + "/card/new")
    assert resp.status == 200, "表单页非200"
    page.wait_for_selector("input[name=task_code]")

    # 详情页(JSON API)：取真实工卡id
    r = page.request.get(server_base + "/card/list-json")
    assert r.status == 200, "list-json非200"
    cards = r.json()
    assert len(cards) > 0, "list-json为空"
    cid = cards[0].get("id")
    assert cid, "list-json缺少id字段"
    resp = page.goto(server_base + f"/card/{cid}")
    assert resp.status == 200, "详情页非200"
    data = resp.json()
    assert data.get("task_code"), "详情数据缺少task_code"

    assert not js_errors, f"页面存在JS错误: {js_errors}"


# ---------- 2. 弹窗编辑 ----------
def test_edit_card_popup(page, server_base):
    """弹窗编辑工卡 → 保存 → toast"保存成功" → 弹窗关闭。"""
    page.goto(server_base + "/card/list")
    page.wait_for_selector("#cardTable tbody tr")
    first = page.locator("#cardTable tbody tr").first
    code = first.locator("td").first.inner_text().strip()

    with page.expect_popup() as pi:
        first.locator("a[onclick*='openEditor']").first.click()
    popup = pi.value
    popup.wait_for_load_state("load")
    popup.wait_for_selector("input[name=task_code]")
    assert popup.locator("input[name=task_code]").input_value() == code, "弹窗预填工卡号不一致"

    if popup.locator("#toolTable tbody tr").count() == 0:
        popup.check("#confirmNoTools")
    if popup.locator("#matTable tbody tr").count() == 0:
        popup.check("#confirmNoMats")

    popup.fill("input[name=task_name]", "E2E-EDIT-" + uuid.uuid4().hex[:6])
    popup.click("button[type=submit]")
    popup.wait_for_selector("#toastContainer .toast", timeout=5000)
    txt = popup.locator("#toastContainer .toast").last.inner_text()
    assert "保存成功" in txt, f"未出现保存成功toast: {txt!r}"
    popup.wait_for_event("close", timeout=15000)


# ---------- 3. 弹窗新增 ----------
def test_new_card_popup(page, server_base):
    """弹窗新增工卡 → 保存成功 → 弹窗关闭 → 父页显示新卡。"""
    page.goto(server_base + "/card/list")
    page.wait_for_selector("#cardTable tbody tr")

    with page.expect_popup() as pi:
        page.click("a[onclick*='/card/new']")
    popup = pi.value
    popup.wait_for_load_state("load")
    popup.wait_for_selector("input[name=task_code]")
    assert popup.url.rstrip("/") == server_base + "/card/new"

    code = _uniq("E2E-NEW")
    popup.fill("input[name=task_code]", code)
    popup.fill("input[name=task_name]", "e2e新增工卡")
    popup.select_option("select[name=category]", label="发动机")
    popup.select_option("select[name=task_type]", "A")
    popup.check("#confirmNoTools")
    popup.check("#confirmNoMats")

    with popup.expect_event("close", timeout=15000):
        popup.click("button[type=submit]")

    page.wait_for_selector(f"text={code}", timeout=15000)


# ---------- 4. 校验toast ----------
def test_validation_toasts(page, server_base):
    """空专业/半空行/未勾选确认 → 对应toast提示。"""
    # 场景1：空专业 → toast "专业不能为空"
    page.goto(server_base + "/card/list")
    page.wait_for_selector("#cardTable tbody tr")
    with page.expect_popup() as pi:
        page.locator("#cardTable tbody tr").first.locator("a[onclick*='openEditor']").first.click()
    popup1 = pi.value
    popup1.wait_for_load_state("load")
    popup1.wait_for_selector("select[name=category]")
    popup1.select_option("select[name=category]", "")
    popup1.click("button[type=submit]")
    popup1.wait_for_selector("#toastContainer .toast", timeout=5000)
    t1 = popup1.locator("#toastContainer .toast").last.inner_text()
    assert "专业不能为空" in t1, f"空专业toast不符: {t1!r}"
    popup1.close()

    # 场景2：半空行（仅填工具名称）→ toast 行不完整
    with page.expect_popup() as pi2:
        page.click("a[onclick*='/card/new']")
    popup2 = pi2.value
    popup2.wait_for_load_state("load")
    popup2.wait_for_selector("input[name=task_code]")
    popup2.fill("input[name=task_code]", _uniq("E2E-HALF"))
    popup2.fill("input[name=task_name]", "半空行用例")
    popup2.select_option("select[name=category]", label="发动机")
    popup2.select_option("select[name=task_type]", "A")
    popup2.click("button[onclick*=\"addRow('tool')\"]")
    popup2.locator("#toolTable tbody input[name='tool_name[]']").last.fill("仅名称工具")
    popup2.click("button[type=submit]")
    popup2.wait_for_selector("#toastContainer .toast", timeout=5000)
    t2 = popup2.locator("#toastContainer .toast").last.inner_text()
    assert ("不完整" in t2) or ("半空" in t2), f"半空行toast不符: {t2!r}"
    popup2.close()

    # 场景3：未勾选确认无工具 → toast "请添加工具或确认无工具"
    with page.expect_popup() as pi3:
        page.click("a[onclick*='/card/new']")
    popup3 = pi3.value
    popup3.wait_for_load_state("load")
    popup3.wait_for_selector("input[name=task_code]")
    popup3.fill("input[name=task_code]", _uniq("E2E-NOCONF"))
    popup3.fill("input[name=task_name]", "未勾选用例")
    popup3.select_option("select[name=category]", label="发动机")
    popup3.select_option("select[name=task_type]", "A")
    popup3.click("button[type=submit]")
    popup3.wait_for_selector("#toastContainer .toast", timeout=5000)
    t3 = popup3.locator("#toastContainer .toast").last.inner_text()
    assert "请添加工具或确认无工具" in t3, f"未勾选确认toast不符: {t3!r}"
    popup3.close()


# ---------- 5. cardId 编辑URL ----------
def test_card_id_correct(page, server_base):
    """编辑页 cardId 正确：URL=/card/<id>/edit 与内嵌 cards 数组id一致。"""
    page.goto(server_base + "/card/list")
    page.wait_for_selector("#cardTable tbody tr")

    html = page.content()
    m = re.search(r"var cards\s*=\s*(\[.*?\])\s*;", html, re.DOTALL)
    assert m, "未找到 var cards 数组"
    cards = json.loads(m.group(1))
    assert len(cards) > 0, "cards数组为空"
    ids = [str(c["id"]) for c in cards]

    rows = page.locator("#cardTable tbody tr")
    for i in range(min(3, len(ids))):
        onclick = rows.nth(i).locator("a[onclick*='openEditor']").first.get_attribute("onclick")
        mm = re.search(r"openEditor\('/card/(\d+)/edit'\)", onclick)
        assert mm is not None, f"第{i}行编辑URL格式异常: {onclick!r}"
        assert mm.group(1) == ids[i], f"第{i}行编辑URL id={mm.group(1)} 与cards数组 id={ids[i]} 不一致"


# ---------- 6. 上传无文件 ----------
def test_upload_no_file(page, server_base):
    """上传页无文件 → toast"请至少上传一个文件"。"""
    page.goto(server_base + "/upload")
    page.wait_for_selector("#uploadForm")
    assert page.locator("#uploadForm input[type=file]").count() >= 1, "上传表单缺少文件输入"

    page.click("#uploadForm button[type=submit]")
    page.wait_for_selector("#toastContainer .toast", timeout=5000)
    txt = page.locator("#toastContainer .toast").last.inner_text()
    assert "请至少上传一个文件" in txt, f"上传toast不符: {txt!r}"


# ---------- 7. 日志分页导航 ----------
def test_logs_pagination_ui(page, server_base):
    """日志分页导航正常：第1页有分页信息→点下一页→URL page=2→首行变化。"""
    page.goto(server_base + "/card/logs")
    page.wait_for_selector(".log-table tbody tr")

    info = page.locator("div.text-muted.small").first.inner_text()
    m = re.search(r"第\s*(\d+)/(\d+)\s*页", info)
    assert m, f"未找到分页信息: {info!r}"
    cur, total_pages = int(m.group(1)), int(m.group(2))
    assert cur == 1 and total_pages > 1, f"期望多页日志(total_pages>1)，实际 {info!r}"

    first_id = page.locator(".log-table tbody tr").first.locator("td").first.inner_text()
    page.locator("ul.pagination a.page-link", has_text="下一页").click()
    page.wait_for_url("**/card/logs?*page=2*", timeout=5000)
    page.wait_for_load_state("load")
    new_id = page.locator(".log-table tbody tr").first.locator("td").first.inner_text()
    assert new_id != first_id, "翻页后首行日志未变化"

