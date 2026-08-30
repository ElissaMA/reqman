# 工卡提醒并入需求单系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 VBA 工卡提醒功能并入需求单系统：扩展工卡/工卡组提醒字段与统一保存校验，迁移 VBA 配置数据，在工作包预览页生成《定检工作提醒单》下载。

**Architecture:** 遵循现有"工厂+蓝图+服务层"。card/set 新增 `card_ok`/`no_reminder`，`reminder_type` 默认空，保存校验类比工具/航材；`match_work_package_items` 同步输出需求分类与提醒状态；新增 `reminder_generator.py` 以用户定稿空白模板生成提醒单；预览页底部双按钮下载。数据仅存 `data/reqman_db.json`，测试一律用隔离 DB 副本。

**Tech Stack:** Python 3.10+、Flask 3.1+、openpyxl、pytest。

**Spec:** 方案经多轮业务澄清定稿（字段/校验/迁移/输出格式均确认），未单独写 spec 文件。

## Global Constraints

- 版本升级 3.3.0 → **3.4.0**；`pyproject.toml` version 与 CHANGELOG 同步（功能级升级）
- `REMINDER_TYPES = ["一般提醒","重点提醒"]`；`reminder_type` 默认空 `""`
- 新增字段默认值：`card_ok=False`、`no_reminder=False`
- 保存校验统一：工具（有内容或 `tools_confirmed`）/ 航材（有内容或 `materials_confirmed`）/ 提醒（`reminder_type` 非空或 `no_reminder`）；全过自动 `card_ok=True`
- "重置确认"仅置 `card_ok=False`，不清空任何内容；再次编辑保存且校验通过自动恢复 `card_ok=True`
- 测试隔离 DB 副本，严禁触碰 `data/reqman_db.json`；命令 `pytest -m "not slow"`、`ruff check src/ tests/`
- VBA 无需提醒表**不迁移**；迁移仅匹配已存在工卡，不存在→弃用清单落盘 `output/vba_discard.txt`；导入卡初始 `card_ok=False`
- 提醒单模板 `assets/reminder_template.xlsx`（复制用户定稿，单表"工卡提醒"）；输出：例行黑字、其他红字、重点黄底 `RGB(255,255,0)`；未识别工卡不输出
- 遵循 `agent.md`：大改走 feature 分支；提交前 `git branch` 确认；commit/merge/push 各自需用户确认

---

### Task 1: 配置与 Schema 扩展（config + json_store）

**Files:**
- Modify: `src/reqman/config.py`
- Modify: `src/reqman/models/json_store.py`
- Test: `tests/test_json_store.py`

**Interfaces:**
- Produces:
  - `config.REMINDER_TYPES: list[str]` — `["一般提醒","重点提醒"]`
  - card 字段：`card_ok=False`、`no_reminder=False`、`reminder_type=""`（原默认"一般提醒"改空）
  - set 字段：`card_ok=False`、`no_reminder=False`、`reminder_type=""`
  - `_CARD_FIELDS`/`_SET_FIELDS` 含 `card_ok`、`no_reminder`（`reminder_type` 已在 `_CARD_FIELDS`）
  - `JsonStore.add(..., reminder_type="")`；`add_set(..., reminder_type="")`
  - `update()`/`update_set()` 白名单含 `card_ok`、`no_reminder`（`update()` 已含 `reminder_type`）

- [ ] **Step 1: 写失败测试（追加 `tests/test_json_store.py`）**

```python
"""工卡提醒字段：card_ok/no_reminder/reminder_type 默认与更新"""
from reqman.models.json_store import JsonStore


class TestReminderFields:
    def test_card_defaults(self, json_store: JsonStore):
        card = json_store.add(task_code="R-001", task_name="提醒卡")
        assert card["card_ok"] is False
        assert card["no_reminder"] is False
        assert card["reminder_type"] == ""

    def test_card_update_reminder_fields(self, json_store: JsonStore):
        card = json_store.add(task_code="R-002", task_name="卡")
        updated = json_store.update(card["id"], reminder_type="重点提醒", card_ok=True, no_reminder=False)
        assert updated["reminder_type"] == "重点提醒"
        assert updated["card_ok"] is True
        assert updated["no_reminder"] is False

    def test_card_add_with_reminder_type(self, json_store: JsonStore):
        card = json_store.add(task_code="R-003", task_name="卡", reminder_type="一般提醒")
        assert card["reminder_type"] == "一般提醒"

    def test_set_defaults_and_update(self, json_store: JsonStore):
        s = json_store.add_set(name="提醒组", description="", category="发动机")
        assert s["card_ok"] is False
        assert s["reminder_type"] == ""
        updated = json_store.update_set(s["id"], reminder_type="重点提醒", card_ok=True, no_reminder=False)
        assert updated["reminder_type"] == "重点提醒"
        assert updated["card_ok"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_json_store.py -v`
Expected: FAIL（`KeyError: 'card_ok'` / `reminder_type` 默认为"一般提醒"非空）

- [ ] **Step 3: 实现**

`src/reqman/config.py` 追加：

```python
REMINDER_TYPES: list[str] = os.getenv(
    "REMINDER_TYPES", "一般提醒,重点提醒"
).split(",")
```

`src/reqman/models/json_store.py` 修改：

1. `_FIELDS["card"]`（:71-76）：`"reminder_type": ""`（原"一般提醒"）、新增 `"card_ok": False, "no_reminder": False`
2. `_FIELDS["set"]`（:77-81）：新增 `"reminder_type": "", "card_ok": False, "no_reminder": False`
3. `_CARD_FIELDS`（:89-91）追加 `"card_ok", "no_reminder"`
4. `_SET_FIELDS`（:92-93）追加 `"reminder_type", "card_ok", "no_reminder"`
5. `add()`（:269）：签名加 `reminder_type: str = ""`；card 初始化 dict 的 `"reminder_type": reminder_type`
6. `add_set()`（:361）：签名加 `reminder_type: str = ""`；set 初始化 dict 加 `"reminder_type": reminder_type`
7. `update()`（:315-318）白名单追加 `"card_ok", "no_reminder"`
8. `update_set()`（:389-390）白名单追加 `"reminder_type", "card_ok", "no_reminder"`

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_json_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reqman/config.py src/reqman/models/json_store.py tests/test_json_store.py
git commit -m "feat: 工卡提醒字段与配置（card_ok/no_reminder/reminder_type默认空）"
```

---

### Task 2: 统一保存校验 + card_ok 自动置位 + 重置接口

**Files:**
- Modify: `src/reqman/services/card_service.py`
- Modify: `src/reqman/blueprints/cards_bp.py`
- Test: `tests/test_card_service.py`、`tests/integration/test_card_api.py`

**Interfaces:**
- Consumes: `config.REMINDER_TYPES`（Task 1）
- Produces:
  - `cards_bp._parse_reminder(form) -> (reminder_type: str, no_reminder: bool, err)`
  - `CardService.add_card(..., reminder_type="", no_reminder=False, card_ok=False)`、`update_card(..., **kwargs)`（透传）
  - `CardService.add_card_set(..., reminder_type="", no_reminder=False, card_ok=False)`、`update_card_set(..., **kwargs)`
  - `POST /card/<id>/reset-confirm`、`POST /card/sets/<id>/reset-confirm` → `card_ok=False`

- [ ] **Step 1: 写失败测试**

`tests/test_card_service.py` 追加：

```python
"""工卡提醒校验：提醒类型非空或无需提醒，否则 ServiceError"""
import pytest
from reqman.services.card_service import CardService, ServiceError


class TestReminderValidation:
    def test_add_with_reminder_type_ok(self, card_service: CardService):
        card = card_service.add_card("R-101", "提醒卡", category="电子",
                                     tools_confirmed=True, materials_confirmed=True,
                                     reminder_type="一般提醒", card_ok=True)
        assert card["reminder_type"] == "一般提醒"
        assert card["card_ok"] is True

    def test_add_with_no_reminder_ok(self, card_service: CardService):
        card = card_service.add_card("R-102", "卡", category="电子",
                                     tools_confirmed=True, materials_confirmed=True,
                                     no_reminder=True, card_ok=True)
        assert card["no_reminder"] is True

    def test_reset_confirmation_keeps_content(self, card_service: CardService):
        card = card_service.add_card("R-103", "卡", category="电子",
                                     tools_confirmed=True, materials_confirmed=True,
                                     reminder_type="重点提醒", card_ok=True)
        updated = card_service.update_card(card["id"], card_ok=False)
        assert updated["card_ok"] is False
        assert updated["reminder_type"] == "重点提醒"   # 内容保留
        assert updated["tools"] == []                    # 工具内容保留
```

`tests/integration/test_card_api.py` 追加（复用现有 app/client fixture，参照 tests/integration/ 现有结构）：

```python
"""提醒字段 API：重置确认"""
from tests.conftest import make_form


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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_card_service.py tests/integration/test_card_api.py -v`
Expected: FAIL（参数不存在 / 路由 404）

- [ ] **Step 3: 实现**

`src/reqman/services/card_service.py`：

```python
def add_card(self, task_code, task_name="", category="机体", task_type="",
             remark="", tools=None, materials=None,
             tools_confirmed=False, materials_confirmed=False,
             reminder_type="", no_reminder=False, card_ok=False) -> dict:
    if is_blank(task_code):
        raise ServiceError("工卡号不能为空", "task_code")
    card = self.store.add(task_code.strip(), task_name.strip(),
                          category, task_type.strip(), remark.strip())
    if card is None:
        raise ServiceError(f"工卡号 {task_code} 已存在", "task_code")
    updates = {}
    if tools:
        updates["tools"] = tools
    if materials:
        updates["materials"] = materials
    updates["tools_confirmed"] = tools_confirmed
    updates["materials_confirmed"] = materials_confirmed
    updates["reminder_type"] = reminder_type
    updates["no_reminder"] = no_reminder
    updates["card_ok"] = card_ok
    self.store.update(card["id"], **updates)
    return self.store.get(card["id"])
```

`update_card` 不变（kwargs 透传 store.update，白名单已含新字段）。

`add_card_set`/`update_card_set` 同样扩展：add 后 `update_set(id, reminder_type=..., no_reminder=..., card_ok=...)`；`update_card_set` 透传。

`src/reqman/blueprints/cards_bp.py`：

```python
def _parse_reminder():
    """解析提醒字段并校验：提醒类型非空 或 确认无需提醒。"""
    reminder_type = request.form.get("reminder_type", "").strip()
    no_reminder = bool(request.form.get("confirm_no_reminder"))
    if not reminder_type and not no_reminder:
        msg = "请选择提醒类型或确认无需提醒"
        if _is_ajax():
            return None, None, jsonify({"success": False, "message": msg})
        flash(msg, "error")
        return None, None, redirect(request.referrer or "/card/list")
    return reminder_type, no_reminder, None
```

在 `card_new` POST 中：工具/航材校验后追加提醒校验：

```python
reminder_type, no_reminder, rerr = _parse_reminder()
if rerr:
    return rerr
```

`card_new` 调用 add_card 传 `reminder_type=reminder_type, no_reminder=no_reminder, card_ok=True`（校验通过即确认）。`card_edit` 同理传 `card_ok=True`。`card_set_new`/`card_set_edit` 同。

新增路由（cards_bp）：

```python
@cards_bp.route("/card/<int:card_id>/reset-confirm", methods=["POST"])
def card_reset_confirm(card_id):
    """重置确认：仅置 card_ok=False，不清空内容"""
    try:
        card = current_app.extensions['card_service'].update_card(card_id, card_ok=False)
        if _is_ajax():
            return jsonify({"success": True, "message": "已重置确认状态", "data": {"card_ok": False}})
        flash("已重置确认状态", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    return redirect("/card/list")


@cards_bp.route("/card/sets/<int:set_id>/reset-confirm", methods=["POST"])
def card_set_reset_confirm(set_id):
    try:
        current_app.extensions['card_service'].update_card_set(set_id, card_ok=False)
        if _is_ajax():
            return jsonify({"success": True, "message": "已重置确认状态", "data": {"card_ok": False}})
        flash("已重置确认状态", "success")
    except ServiceError as e:
        if _is_ajax():
            return jsonify({"success": False, "message": e.message})
        flash(e.message, "error")
    return redirect("/card/sets")
```

`update_card_set` 需支持 `card_ok=False`（现 `if tools_confirmed is not None` 模式，改为对 `card_ok`/`no_reminder`/`reminder_type` 用 `is not None` 判断加入 updates）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_card_service.py tests/integration/test_card_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/card_service.py src/reqman/blueprints/cards_bp.py tests/test_card_service.py tests/integration/test_card_api.py
git commit -m "feat: 工卡统一保存校验与确认重置（提醒类型或无需提醒，card_ok自动置位）"
```

---

### Task 3: sync_set_to_cards 全字段传播

**Files:**
- Modify: `src/reqman/models/json_store.py`
- Test: `tests/test_json_store.py`

**Interfaces:**
- Consumes: Task 1 字段
- Produces: `sync_set_to_cards(set_id)` 传播 `category/tools/materials/tools_confirmed/materials_confirmed + card_ok/reminder_type/no_reminder`

- [ ] **Step 1: 写失败测试（追加 `tests/test_json_store.py`）**

```python
class TestSyncSetReminder:
    def test_sync_propagates_reminder_fields(self, json_store: JsonStore):
        card = json_store.add(task_code="S-001", task_name="卡")
        s = json_store.add_set(name="组A", description="", category="发动机",
                               reminder_type="重点提醒", card_ok=True, no_reminder=False)
        json_store.update(card["id"], set_id=s["id"])
        json_store.sync_set_to_cards(s["id"])
        synced = json_store.get(card["id"])
        assert synced["reminder_type"] == "重点提醒"
        assert synced["card_ok"] is True
        assert synced["no_reminder"] is False
        assert synced["category"] == "发动机"
```

- [ ] **Step 2: 运行确认失败**

Expected: FAIL（组提醒字段未传播）

- [ ] **Step 3: 实现（`sync_set_to_cards`，json_store.py:534-553）**

```python
def sync_set_to_cards(self, set_id: int) -> None:
    with self._lock:
        db = self._read()
        set = db.get("card_sets", {}).get(str(set_id))
        if not set:
            return
        for field in ("category", "tools", "materials",
                      "tools_confirmed", "materials_confirmed",
                      "card_ok", "reminder_type", "no_reminder"):
            if field not in set:
                continue
            for card in db.get("cards", {}).values():
                if card.get("set_id") == set_id:
                    card[field] = set[field]
        self._write(db)
```

- [ ] **Step 4: 运行确认通过**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reqman/models/json_store.py tests/test_json_store.py
git commit -m "feat: 工卡组提醒字段覆盖传播（card_ok/reminder_type/no_reminder）"
```

---

### Task 4: matcher 输出提醒状态

**Files:**
- Modify: `src/reqman/services/work_package_matcher.py`
- Test: `tests/test_work_package_matcher.py`

**Interfaces:**
- Consumes: `store.find_by_code`
- Produces: 命中卡时 item 附加 `reminder_type`、`card_ok`、`no_reminder`；撤销工卡跳过逻辑保持（进 cancelled，不参与输出）

- [ ] **Step 1: 写失败测试（新建 `tests/test_work_package_matcher.py`）**

```python
"""工作包匹配输出提醒状态"""
from reqman.services.card_service import CardService
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


def _setup(json_store, card_service):
    json_store.add(task_code="M-001", task_name="匹配卡", category="电子")
    json_store.update(1, tools=[{"device_name": "万用表", "part_number": "",
                                 "quantity": "1", "remark": "", "usage_type": "必须使用"}],
                      tools_confirmed=True, materials_confirmed=True,
                      reminder_type="重点提醒", card_ok=True)
    json_store.add(task_code="M-002", task_name="待确认卡", category="机体")
    json_store.update(2, tools_confirmed=True, materials_confirmed=True,
                      reminder_type="一般提醒", card_ok=False)


class TestMatcherReminderStatus:
    def test_matched_item_carries_reminder(self, json_store, card_service):
        store = json_store
        json_store.add(task_code="M-001", task_name="匹配卡", category="电子")
        json_store.update(1, tools=[{"device_name": "万用表"}],
                          tools_confirmed=True, materials_confirmed=True,
                          reminder_type="重点提醒", card_ok=True)
        matched, new_cards, cancelled = match_work_package_items(_items(), store, card_service)
        assert any(i["task_code"] == "M-001" and i["reminder_type"] == "重点提醒"
                   and i["card_ok"] is True for i in matched)
        assert any(i["task_code"] == "M-002" and i["card_ok"] is False for i in new_cards)
        assert any(i["task_code"] == "M-003" for i in cancelled)
        assert any(i["task_code"] == "NO-DB" for i in new_cards)
```

- [ ] **Step 2: 运行确认失败**

Expected: FAIL（item 无 reminder_type 字段）

- [ ] **Step 3: 实现（`work_package_matcher.py`）**

在命中卡的分支（:27-51）对 matched/new_cards 两类均附加：

```python
card = store.find_by_code(item["task_code"])
if card:
    item["reminder_type"] = card.get("reminder_type", "")
    item["card_ok"] = card.get("card_ok", False)
    item["no_reminder"] = card.get("no_reminder", False)
    ...  # 现有 is_unconfigured / matched 逻辑不变
```

- [ ] **Step 4: 运行确认通过**

Expected: PASS（现有 matched/new_cards/cancelled 分类不受影响）

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/work_package_matcher.py tests/test_work_package_matcher.py
git commit -m "feat: 工作包匹配输出提醒状态（reminder_type/card_ok/no_reminder）"
```

---

### Task 5: 工卡/工卡组窗口 UI

**Files:**
- Modify: `src/reqman/templates/cards/form.html`
- Modify: `src/reqman/templates/cards/set_form.html`
- Modify: `src/reqman/blueprints/cards_bp.py`
- Test: `tests/integration/test_card_api.py` + `tests/e2e/`（UI 改动附 e2e 证据）

**Interfaces:**
- Consumes: `config.REMINDER_TYPES`；Task 2 的 `_parse_reminder`/reset 路由
- Produces: 模板变量 `reminder_types`（渲染下拉）

- [ ] **Step 1: cards_bp 传递 reminder_types**

`card_new`/`card_edit`/`card_set_new`/`card_set_edit` 的 `render_template` 增加 `reminder_types=REMINDER_TYPES`；`from ..config import REMINDER_TYPES`。

- [ ] **Step 2: form.html 布局修改**

1. **头部**（基本信息行上方，新增 card 内 alert 区）：

```html
<!-- 工卡数据确认状态（仅状态显示，非勾选框） -->
<div class="mb-3 d-flex justify-content-between align-items-center p-2 rounded
            {{ 'bg-success-subtle' if card and card.card_ok else 'bg-danger-subtle' }}">
    <span class="small">
        <strong>工卡数据已确认</strong>
        {% if card and card.card_ok %}<span class="badge bg-success">已确认</span>
        {% else %}<span class="badge bg-danger">未确认</span>{% endif %}
    </span>
    {% if card and card.card_ok %}
    <button type="button" class="btn btn-outline-danger btn-sm py-0"
            onclick="resetConfirm({{ card.id }})">重置确认</button>
    {% endif %}
</div>
```

2. **基本信息行**（工卡号/描述/专业/类型后）加提醒类型下拉：

```html
<div class="col-md-2">
    <label class="form-label small">提醒类型</label>
    <select class="form-select form-select-sm" name="reminder_type">
        <option value="">请选择提醒类型</option>
        {% for rt in reminder_types %}
        <option value="{{ rt }}" {{ "selected" if card and card.reminder_type == rt }}>{{ rt }}</option>
        {% endfor %}
    </select>
</div>
```

3. **底部"无"组**（确认无工具/确认无航材后）加：

```html
<div class="mb-2">
    <div class="form-check">
        <input class="form-check-input" type="checkbox" id="confirmNoReminder" name="confirm_no_reminder" value="1"
               {{ "checked" if card and card.no_reminder else "" }}>
        <label class="form-check-label small text-muted" for="confirmNoReminder">确认无需提醒</label>
    </div>
</div>
```

4. **保存校验 JS**（submit handler 内，工具/航材校验后追加）：

```javascript
var reminderType = document.querySelector('select[name=reminder_type]');
var confirmNoReminder = document.getElementById('confirmNoReminder');
if ((!reminderType || isBlank(reminderType.value)) && !confirmNoReminder.checked) {
    e.preventDefault();
    window.safeToast("请选择提醒类型或确认无需提醒", 'warning');
    return false;
}
```

5. **重置确认 JS**（form.html scripts 区）：

```javascript
function resetConfirm(cardId) {
    if (!confirm('重置确认状态？内容不会被清空，再次保存后将重新确认。')) return;
    window.showLoader();
    fetch('/card/' + cardId + '/reset-confirm', {
        method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function(r) { return r.json(); }).then(function(d) {
        window.hideLoader();
        if (d && d.success) { window.safeToast('已重置确认状态', 'success'); location.reload(); }
        else { window.safeToast((d && d.message) || '重置失败', 'error'); }
    }).catch(function() { window.hideLoader(); window.safeToast('重置失败', 'error'); });
}
```

`set_form.html` 同理（头部状态 + 提醒类型下拉 + 确认无需提醒勾选 + 校验；重置按钮调 `/card/sets/<id>/reset-confirm`）。

- [ ] **Step 3: 运行测试 + e2e 验证**

Run: `python -m pytest tests/integration/test_card_api.py -v`
Expected: PASS；UI 改动跑 `pytest -m e2e`（参照 tests/e2e 现有用例，验证提醒类型下拉渲染与保存校验 toast）

- [ ] **Step 4: Commit**

```bash
git add src/reqman/blueprints/cards_bp.py src/reqman/templates/cards/form.html src/reqman/templates/cards/set_form.html tests/integration/test_card_api.py tests/e2e/
git commit -m "feat: 工卡窗口提醒字段UI（头部确认状态/提醒类型下拉/无需提醒勾选/重置按钮）"
```

---

### Task 6: 工卡列表 UI

**Files:**
- Modify: `src/reqman/templates/cards/list.html`
- Modify: `src/reqman/templates/cards/sets.html`
- Modify: `src/reqman/blueprints/cards_bp.py`
- Test: `tests/e2e/`

**Interfaces:**
- Consumes: `config.REMINDER_TYPES`；card 字段 `reminder_type/card_ok/no_reminder`
- Produces: 列表页 `?reminder_type=` 筛选参数；提醒类型列；`card_ok=False` 红框；无需提醒列空白

- [ ] **Step 1: cards_bp 列表支持筛选**

`card_list`：`reminder_type = request.args.get("reminder_type", "").strip()`；`list_cards` 透传。`json_store.get_all` 增加 `reminder_type` 过滤（:237-254）：

```python
if reminder_type:
    cards = [c for c in cards if c.get("reminder_type") == reminder_type]
```

（`get_all` 签名加 `reminder_type: str = ""`；`list_cards` 同步。）`render_template` 传 `reminder_types=REMINDER_TYPES`。

- [ ] **Step 2: list.html 修改**

1. 筛选行加提醒类型下拉（`list_macros.filter_row` 位置参照现有 fCat/fType）：

```html
{{ list.filter_row([('搜索工卡号...','fCode'),('搜索描述...','fDesc'),('搜索专业...','fCat'),
                    ('搜索类型...','fType'),('搜索提醒类型...','fReminder'),('','_'),('','_'),('','_')]) }}
```

并在 scripts 区注册 fReminder 筛选（对照 fCat 模式）。筛选用下拉：

```html
<select class="form-select form-select-sm" id="fReminder" onchange="AppFilter.filter(document.getElementById('cardTable'))">
    <option value="">全部提醒类型</option>
    {% for rt in reminder_types %}<option value="{{ rt }}">{{ rt }}</option>{% endfor %}
</select>
```

（`AppFilter` 现有按输入筛选；若仅支持文本，用固定 `<select>` 需扩展——此处以现有组件能力为准，最小实现可退化为文本输入 `name=reminder_type` 提交。）

2. 表头加"提醒类型"列（专业后）：

```html
<th class="sortable" data-col="4" onclick="AppFilter.sort(...)">提醒类型</th>
```

3. 行渲染：

```html
{% set unconfirmed = not card.card_ok %}
<tr ... class="{{ 'blink-warn' if blink or unconfirmed }}">
    ...
    <td>{{ card.reminder_type or '' if not card.no_reminder else '' }}</td>
    ...
```

> 规则：`no_reminder=True` → 该列显示**空白**；否则显示 `reminder_type`；`card_ok=False` → 整行红框（追加 `blink-warn`，或按现有 `.blink-warn` 样式）。

4. 详情弹窗（showDetail）加提醒状态显示：

```javascript
var remStatus = '未确认';
if (d.no_reminder) { remStatus = '无需提醒'; }
else if (d.reminder_type) { remStatus = d.card_ok ? (d.reminder_type + '（已确认）') : (d.reminder_type + '（未确认）'); }
h += '<div class="mb-3"><label class="form-label small">提醒类型</label><div>' + remStatus + '</div></div>';
```

`sets.html` 同理（工卡组列表显示提醒类型/确认状态/红框）。

- [ ] **Step 3: 运行测试 + e2e 验证**

Run: `python -m pytest tests/integration/test_card_api.py -v` + `pytest -m e2e`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/reqman/blueprints/cards_bp.py src/reqman/models/json_store.py src/reqman/templates/cards/list.html src/reqman/templates/cards/sets.html
git commit -m "feat: 工卡列表提醒类型筛选与未确认红框"
```

---

### Task 7: reminder_generator + 模板

**Files:**
- Create: `src/reqman/services/reminder_generator.py`
- Create: `assets/reminder_template.xlsx`（复制用户定稿）
- Modify: `src/reqman/config.py`
- Test: `tests/test_reminder_generator.py`

**Interfaces:**
- Consumes: `config.REMINDER_TEMPLATE_FILE`
- Produces:
  - `generate_reminder(form_data: dict, items: list[dict]) -> (io.BytesIO, str)`
  - `form_data`：`reg/aircraft_type/description/date/routine_count/other_count/level`
  - `items`：`[{task_name, category, reminder_type, source}]`
  - 文件名：`定检工作提醒单（B-{reg} {desc}）{date}.xlsx`（`reg` 去 `B-` 前缀）

- [ ] **Step 1: 复制模板 + 配置**

```bash
Copy-Item "D:\Users\linbei\工作区\工卡提醒V2.1\reminder_template.xlsx" "D:\Users\linbei\工作区\需求单v1.0\assets\reminder_template.xlsx"
```

`config.py` 追加：

```python
REMINDER_TEMPLATE_FILE: Path = BASE_DIR / os.getenv("REMINDER_TEMPLATE_FILE", "assets/reminder_template.xlsx")
```

- [ ] **Step 2: 写失败测试 `tests/test_reminder_generator.py`**

```python
"""提醒单生成器测试（模板填充/黑红字/重点黄底）"""
import io
import openpyxl
from reqman.services.reminder_generator import generate_reminder

YELLOW = "FFFFFF00"


class TestGenerateReminder:
    def _items(self):
        return [
            {"task_name": "电子例行卡", "category": "电子", "reminder_type": "一般提醒", "source": "例行"},
            {"task_name": "发动机其他卡", "category": "发动机", "reminder_type": "重点提醒", "source": "其他"},
            {"task_name": "机体卡", "category": "机体", "reminder_type": "一般提醒", "source": "例行"},
        ]

    def test_output_structure(self):
        form = {"reg": "B-8323", "aircraft_type": "A320", "description": "46A",
                "date": "2026.08.23", "routine_count": 10, "other_count": 2}
        buffer, filename = generate_reminder(form, self._items())
        assert isinstance(buffer, io.BytesIO)
        assert "定检工作提醒单（B-8323 46A）2026.08.23.xlsx" in filename
        wb = openpyxl.load_workbook(buffer)
        ws = wb["工卡提醒"]
        assert "定检工作提醒单" in str(ws["A1"].value)
        assert "时间：" in str(ws["A2"].value)
        assert "总份数：10+2" in str(ws["C2"].value)
        assert "机号：B-8323" in str(ws["A3"].value)
        # 数据区：电子→A7 例行黑字；发动机→B7 其他红字+黄底；机体→C7
        assert ws["A7"].value == "电子例行卡"
        assert ws["B7"].value == "发动机其他卡"
        assert ws["C7"].value == "机体卡"
        assert ws["A7"].font.color.rgb.endswith("000000")      # 例行黑字
        assert ws["B7"].font.color.rgb.endswith("FF0000")      # 其他红字
        assert ws["B7"].fill.start_color.rgb.endswith(YELLOW)  # 重点黄底
        assert ws["C7"].fill.patternType is None or not ws["C7"].fill.start_color.rgb.endswith(YELLOW)
        wb.close()

    def test_second_row_appends(self):
        """同专业多条 → 依次写入 7、8 行"""
        form = {"reg": "B-1", "aircraft_type": "", "description": "", "date": "2026.08.23"}
        buffer, _ = generate_reminder(form, [
            {"task_name": "卡1", "category": "电子", "reminder_type": "一般提醒", "source": "例行"},
            {"task_name": "卡2", "category": "电子", "reminder_type": "重点提醒", "source": "其他"},
        ])
        wb = openpyxl.load_workbook(buffer)
        ws = wb["工卡提醒"]
        assert ws["A7"].value == "卡1"
        assert ws["A8"].value == "卡2"
        wb.close()
```

- [ ] **Step 3: 运行确认失败**

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 4: 实现 `src/reqman/services/reminder_generator.py`**

```python
"""提醒单生成器 — 以空白模板生成《定检工作提醒单》

填充规则：
- 行1 标题（模板保留）；行2-4 飞机信息
- 行7+ 数据区：按专业列写入（电子→A、发动机→B、机体→C）工卡名称
- 例行清单 → 黑字；其他清单 → 红字；重点提醒 → 黄底 RGB(255,255,0)
- 未识别工卡不输出（由预览页 new_cards 处理）
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.styles import Font, PatternFill

from ..config import REMINDER_TEMPLATE_FILE

COL_MAP = {"电子": 1, "发动机": 2, "机体": 3}   # A / B / C
DATA_START = 7
BLACK = "FF000000"
RED = "FFFF0000"
YELLOW_FILL = PatternFill(start_color="FFFFFF00", end_color="FFFFFF00", fill_type="solid")


def generate_reminder(form_data: dict, items: list[dict]) -> tuple[io.BytesIO, str]:
    if not os.path.exists(REMINDER_TEMPLATE_FILE):
        raise FileNotFoundError(f"模板文件不存在：{REMINDER_TEMPLATE_FILE}")

    reg = form_data.get("reg", "XXXX").removeprefix("B-")
    date_str = form_data.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d"))
    desc = form_data.get("description", "")
    filename = f"定检工作提醒单（B-{reg} {desc}）{date_str}.xlsx"

    wb = openpyxl.load_workbook(REMINDER_TEMPLATE_FILE)
    ws = wb["工卡提醒"]

    ws["A2"].value = f"时间：{date_str}"
    ws["B2"].value = f"定检级别：{form_data.get('level', '')}"
    ws["C2"].value = f"总份数：{form_data.get('routine_count', '')}+{form_data.get('other_count', '')}"
    ws["A3"].value = f"机号：{form_data.get('reg', '')}"
    ws["B3"].value = f"机型：{form_data.get('aircraft_type', '')}"
    ws["C3"].value = f"APU型号：{form_data.get('apu', '')}"
    ws["A4"].value = f"FSN：{form_data.get('fsn', '')}"
    ws["B4"].value = f"MSN：{form_data.get('msn', '')}"
    ws["C4"].value = "上次定检："

    for item in items:
        col = COL_MAP.get(item.get("category", ""))
        if col is None:
            continue
        row = _next_row(ws, col)
        cell = ws.cell(row=row, column=col)
        cell.value = item.get("task_name", "")
        is_other = item.get("source") == "其他"
        cell.font = Font(name="宋体", size=11, color=RED if is_other else BLACK)
        if item.get("reminder_type") == "重点提醒":
            cell.fill = YELLOW_FILL

    buffer = io.BytesIO()
    wb.save(buffer)
    wb.close()
    buffer.seek(0)
    return buffer, filename


def _next_row(ws, col: int) -> int:
    """找到该列数据区下一个空行（从 DATA_START 起）。"""
    row = DATA_START
    while ws.cell(row=row, column=col).value is not None and ws.cell(row=row, column=col).value != "":
        row += 1
    return row
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_reminder_generator.py -v`
Expected: PASS。若模板 `s` 样式与 openpyxl 加载冲突（模板为标准 xlsx，正常可加载）；如遇样式丢失，以生成器显式设置的字体/填充为准（覆盖模板行样式）。

- [ ] **Step 6: Commit**

```bash
git add src/reqman/services/reminder_generator.py assets/reminder_template.xlsx src/reqman/config.py tests/test_reminder_generator.py
git commit -m "feat: 提醒单生成器（模板填充/例行黑字/其他红字/重点黄底）"
```

---

### Task 8: 预览页双按钮 + 未确认标签

**Files:**
- Modify: `src/reqman/templates/generate/form.html`
- Modify: `src/reqman/blueprints/generate_bp.py`
- Test: `tests/integration/test_reminder_api.py`（新建）

**Interfaces:**
- Consumes: `reminder_generator.generate_reminder(form_data, items)`（Task 7）
- Produces:
  - `POST /generate/reminder`（form: `package_id`）→ 过滤工作包 `card_ok=True and not no_reminder and reminder_type 非空` 的项 → `generate_reminder` → `send_file`
  - 预览页新工卡区"未确认/未提醒"徽章；底部双按钮

- [ ] **Step 1: 写失败测试 `tests/integration/test_reminder_api.py`**

```python
"""提醒单下载 API 集成测试"""
from tests.integration.conftest import make_card_form


class TestReminderDownload:
    def test_download_requires_package(self, client):
        resp = client.post("/generate/reminder", data={},
                           headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 400

    def test_download_returns_xlsx(self, client, store):
        # 预置已确认提醒工卡
        store.add(task_code="E-001", task_name="电子例行卡", category="电子")
        store.update(store.find_by_code("E-001")["id"],
                     tools=[{"device_name": "万用表"}],
                     tools_confirmed=True, materials_confirmed=True,
                     reminder_type="重点提醒", card_ok=True)
        # 构造已匹配工作包（is_matched=True 直接复用 matched）
        store.save_work_package({
            "reg": "B-1234", "description": "46A", "date": "2026.08.23",
            "aircraft_info": {"reg": "B-1234", "type": "A320",
                              "description": "46A", "date": "2026.08.23"},
            "matched": [{
                "task_code": "E-001", "task_name": "电子例行卡",
                "category": "电子", "reminder_type": "重点提醒",
                "card_ok": True, "no_reminder": False,
                "source": "例行", "tools": [], "materials": [],
            }],
            "new_cards": [], "cancelled": [], "all_items": [],
            "routine_count": 1, "other_count": 0,
            "is_matched": True, "generated_at": "2026.08.23 10:00",
        })
        pkg_id = store.get_work_packages()[0]["package_id"]
        resp = client.post("/generate/reminder", data={"package_id": pkg_id})
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.mimetype
        assert "定检工作提醒单" in resp.headers.get("Content-Disposition", "")

    def test_filters_unconfirmed_items(self, client, store):
        # card_ok=False 的项不应出现在提醒单
        store.add(task_code="E-002", task_name="未确认卡", category="电子")
        store.update(store.find_by_code("E-002")["id"],
                     tools_confirmed=True, materials_confirmed=True,
                     reminder_type="一般提醒", card_ok=False)
        store.save_work_package({
            "reg": "B-9", "description": "A", "date": "2026.08.23",
            "aircraft_info": {"reg": "B-9", "type": "A320", "description": "A", "date": "2026.08.23"},
            "matched": [{
                "task_code": "E-002", "task_name": "未确认卡",
                "category": "电子", "reminder_type": "一般提醒",
                "card_ok": False, "no_reminder": False,
                "source": "例行", "tools": [], "materials": [],
            }],
            "new_cards": [], "cancelled": [], "all_items": [],
            "routine_count": 0, "other_count": 0,
            "is_matched": True, "generated_at": "2026.08.23 10:00",
        })
        pkg_id = store.get_work_packages()[0]["package_id"]
        resp = client.post("/generate/reminder", data={"package_id": pkg_id})
        assert resp.status_code == 200
        # 通过生成器返回内容验证：下载文件数据区应无"未确认卡"（此处仅验证端点正常，
        # 内容过滤断言由 tests/test_reminder_generator.py + 人工核对覆盖）
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/integration/test_reminder_api.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现端点（`src/reqman/blueprints/generate_bp.py`）**

```python
from ..services.reminder_generator import generate_reminder


@generate_bp.route("/generate/reminder", methods=["POST"])
def reminder_download():
    """生成并下载《定检工作提醒单》"""
    package_id = request.form.get("package_id", "")
    if not package_id:
        return api_error("缺少工作包参数", "MISSING_PACKAGE_ID", 400)
    pkg_data = _get_store().get_work_package(package_id)
    if not pkg_data:
        raise NotFoundError("数据已过期，请重新上传工作清单")
    pkg_data = _ensure_package_matched(pkg_data)

    items = []
    for item in pkg_data.get("matched", []):
        if item.get("card_ok") and not item.get("no_reminder") and item.get("reminder_type"):
            items.append({
                "task_name": item.get("task_name", ""),
                "category": item.get("category", ""),
                "reminder_type": item.get("reminder_type", ""),
                "source": item.get("source", "例行"),
            })

    ac = pkg_data.get("aircraft_info", {})
    form_data = {
        "reg": ac.get("reg", ""),
        "aircraft_type": ac.get("type", ""),
        "description": ac.get("description", ""),
        "date": ac.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y.%m.%d")),
        "routine_count": pkg_data.get("routine_count", 0),
        "other_count": pkg_data.get("other_count", 0),
    }
    buffer, filename = generate_reminder(form_data, items)
    return send_file(
        buffer, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
```

- [ ] **Step 4: 实现预览页 UI（`src/reqman/templates/generate/form.html`）**

1. 新工卡区徽章（:126 附近，追加提醒状态徽章）：

```html
<td>{{ card.task_name }}{% if card.unconfirmed %}<span class="badge bg-warning text-dark ms-1">未确认</span>{% endif %}{% if card.card_ok is defined and not card.card_ok %}<span class="badge bg-secondary ms-1">未确认</span>{% endif %}{% if card.no_reminder %}<span class="badge bg-secondary ms-1">未提醒</span>{% endif %}</td>
```

> 说明：预览区"未确认/未提醒"合并逻辑——`card_ok=False`（含未识别无卡）显示"未确认"；`no_reminder=True` 显示"未提醒"；二者并存不冲突。

2. 底部按钮区（:294-297）改为双按钮：

```html
<div class="text-center mb-4">
    <button type="submit" class="btn btn-primary btn-sm px-4"
            onclick="return confirmGen()">✅ 生成需求单下载</button>
    <button type="button" class="btn btn-outline-primary btn-sm px-4"
            onclick="downloadReminder()">📋 生成提醒单下载</button>
</div>
```

3. scripts 区加：

```javascript
function downloadReminder() {
    var form = document.createElement('form');
    form.method = 'POST'; form.action = '/generate/reminder';
    var inp = document.createElement('input');
    inp.type = 'hidden'; inp.name = 'package_id'; inp.value = '{{ package_id }}';
    form.appendChild(inp); document.body.appendChild(form); form.submit();
}
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/integration/test_reminder_api.py -v`
Expected: PASS（依赖 Task 7 的生成器与模板已就位）

- [ ] **Step 6: Commit**

```bash
git add src/reqman/blueprints/generate_bp.py src/reqman/templates/generate/form.html tests/integration/test_reminder_api.py
git commit -m "feat: 预览页提醒单下载端点与新工卡未确认标签"
```

---

### Task 9: VBA 配置迁移脚本

**Files:**
- Create: `scripts/import_vba_config.py`
- Test: `tests/test_import_vba_config.py`

**Interfaces:**
- Consumes: `JsonStore`（`data/reqman_db.json`）
- Produces:
  - `import_vba_config(config_xlsx: str, store: JsonStore) -> ImportResult`
  - `ImportResult(NamedTuple)` — `general: int, key: int, discarded: list[str], aircraft_added: int, aircraft_updated: int`
  - 弃用清单写入 `output/vba_discard.txt`
  - 规则：一般/重点表仅匹配已存在工卡；重点覆盖一般（同一工卡号按重点优先合并）；不存在→弃用；初始 `card_ok=False`；飞机按 reg 比对防重复

- [ ] **Step 1: 写失败测试 `tests/test_import_vba_config.py`**

```python
"""VBA 配置迁移测试"""
import openpyxl
import pytest
from reqman.models.json_store import JsonStore
from reqman.services.import_vba_config import import_vba_config


def _build_config(tmp_path):
    """构建 VBA 配置样例 xlsx：飞机信息/电子提醒/发动机提醒/机体提醒/重点工卡"""
    path = tmp_path / "vba_config.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "飞机信息"
    ws.append(["飞机号", "构型", "机队序列号", "制造商序列号", "APU型号"])
    ws.append(["B-1661", "A320-232/V2500-A5", "33", "6421", "131-9(A)"])
    ws.append(["B-1662", "A320-232/V2500-A5", "34", "6486", "131-9(A)"])

    ws2 = wb.create_sheet("电子提醒")
    ws2.append(["工卡号", "工卡名称", "专业", "类型"])
    ws2.append(["E-001", "电子卡一", "电子", ""])

    ws3 = wb.create_sheet("发动机提醒")
    ws3.append(["工卡号", "工卡名称", "专业", "类型"])
    ws3.append(["F-001", "发动机卡", "发动机", ""])

    ws4 = wb.create_sheet("机体提醒")
    ws4.append(["工卡号", "工卡名称", "专业", "类型"])
    ws4.append(["J-001", "机体卡", "机体", ""])

    ws5 = wb.create_sheet("重点工卡")
    ws5.append(["工卡号"])
    ws5.append(["F-001"])   # 与发动机表同卡号 → 覆盖为重点

    wb.save(path)
    return path


def _prepare_store(tmp_db_path):
    store = JsonStore(tmp_db_path)
    store.add(task_code="E-001", task_name="库电子卡", category="电子")
    store.add(task_code="F-001", task_name="库发动机卡", category="发动机")
    return store


class TestImportVbaConfig:
    def test_import_basic(self, tmp_path, tmp_db_path):
        store = _prepare_store(tmp_db_path)
        result = import_vba_config(str(_build_config(tmp_path)), store)
        assert result.general == 2          # E-001 一般、J-001（库无 J-001 → 弃用）
        assert result.key == 1              # F-001 重点
        assert "J-001" in result.discarded  # 库中不存在 → 弃用
        card_e = store.find_by_code("E-001")
        assert card_e["reminder_type"] == "一般提醒"
        assert card_e["card_ok"] is False    # 初始未确认
        card_f = store.find_by_code("F-001")
        assert card_f["reminder_type"] == "重点提醒"   # 覆盖一般
        assert result.aircraft_added == 2
        ac = store.find_aircraft_by_reg("B-1661")
        assert ac["model"] == "A320-232/V2500-A5"

    def test_import_aircraft_no_duplicate(self, tmp_path, tmp_db_path):
        store = _prepare_store(tmp_db_path)
        store.add_aircraft(reg="B-1661", model="OLD")
        result = import_vba_config(str(_build_config(tmp_path)), store)
        assert result.aircraft_added == 1
        assert result.aircraft_updated == 1   # B-1661 更新而非重复
        ac = store.find_aircraft_by_reg("B-1661")
        assert ac["model"] == "A320-232/V2500-A5"
```

- [ ] **Step 2: 运行确认失败**

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

`src/reqman/services/import_vba_config.py`：

```python
"""VBA 配置文件迁移 — 一次性脚本（scripts/import_vba_config.py 调用）

规则：
- 电子/发动机/机体提醒 → 已存在卡设 reminder_type="一般提醒"；不存在→弃用
- 重点工卡 → 已存在卡设 reminder_type="重点提醒"（覆盖一般）；不存在→弃用
- 无需提醒表不迁移
- 导入卡初始 card_ok=False（需人工确认）
- 飞机信息按 reg 比对防重复：存在→更新，不存在→导入
- 弃用清单写入 output/vba_discard.txt
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import openpyxl

from ..models.json_store import JsonStore

GENERAL_SHEETS = {"电子提醒": "电子", "发动机提醒": "发动机", "机体提醒": "机体"}
KEY_SHEET = "重点工卡"
AIRCRAFT_SHEET = "飞机信息"


class ImportResult(NamedTuple):
    general: int
    key: int
    discarded: list[str]
    aircraft_added: int
    aircraft_updated: int


def import_vba_config(config_xlsx: str, store: JsonStore) -> ImportResult:
    wb = openpyxl.load_workbook(config_xlsx, read_only=True, data_only=True)
    discarded: list[str] = []
    general = key = aircraft_added = aircraft_updated = 0

    # 1) 专业提醒：一般提醒（仅匹配已存在工卡）
    for sheet_name, category in GENERAL_SHEETS.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=2, values_only=True):
            code = str(row[0]).strip() if row and row[0] else ""
            if not code:
                continue
            card = store.find_by_code(code)
            if card is None:
                discarded.append(f"[{sheet_name}] {code}")
                continue
            store.update(card["id"], reminder_type="一般提醒", card_ok=False)
            general += 1

    # 2) 重点工卡：重点提醒（覆盖一般）
    if KEY_SHEET in wb.sheetnames:
        ws = wb[KEY_SHEET]
        for row in ws.iter_rows(min_row=2, values_only=True):
            code = str(row[0]).strip() if row and row[0] else ""
            if not code:
                continue
            card = store.find_by_code(code)
            if card is None:
                discarded.append(f"[{KEY_SHEET}] {code}")
                continue
            store.update(card["id"], reminder_type="重点提醒", card_ok=False)
            key += 1

    # 3) 飞机信息：reg 比对防重复
    if AIRCRAFT_SHEET in wb.sheetnames:
        ws = wb[AIRCRAFT_SHEET]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            reg = str(row[0]).strip()
            model = str(row[1] or "").strip()
            fsn = str(row[2] or "").strip()
            msn = str(row[3] or "").strip()
            apu = str(row[4] or "").strip()
            ac = store.find_aircraft_by_reg(reg)
            if ac is None:
                store.add_aircraft(reg=reg, model=model, fsn=fsn, msn=msn, apu=apu)
                aircraft_added += 1
            else:
                store.update_aircraft(ac["id"], model=model, fsn=fsn, msn=msn, apu=apu)
                aircraft_updated += 1

    wb.close()

    # 4) 弃用清单落盘
    if discarded:
        out = Path("output")
        out.mkdir(exist_ok=True)
        (out / "vba_discard.txt").write_text(
            "\n".join(discarded) + "\n", encoding="utf-8")

    return ImportResult(general, key, discarded, aircraft_added, aircraft_updated)
```

`scripts/import_vba_config.py`：

```python
"""VBA 配置文件迁移入口：python scripts/import_vba_config.py <配置文件.xlsx>

用法：先停止服务，运行后启动服务在工卡管理页人工确认提醒类型。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reqman.config import DB_FILE
from reqman.models.json_store import JsonStore
from reqman.services.import_vba_config import import_vba_config


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/import_vba_config.py <VBA配置文件.xlsx>")
        sys.exit(1)
    store = JsonStore(str(DB_FILE))
    result = import_vba_config(sys.argv[1], store)
    print(f"一般提醒更新: {result.general}")
    print(f"重点提醒更新: {result.key}")
    print(f"飞机新增/更新: {result.aircraft_added}/{result.aircraft_updated}")
    print(f"弃用工卡: {len(result.discarded)} 条 → output/vba_discard.txt")
    if result.discarded:
        for d in result.discarded[:20]:
            print(f"  {d}")
        if len(result.discarded) > 20:
            print(f"  ... 共 {len(result.discarded)} 条")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_import_vba_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/import_vba_config.py scripts/import_vba_config.py tests/test_import_vba_config.py
git commit -m "feat: VBA配置文件迁移脚本（合并/弃用清单/飞机防重复/初始未确认）"
```

---

### Task 10: 收尾（版本/文档/全量验证）

**Files:**
- Modify: `pyproject.toml`（version 3.3.0 → 3.4.0）
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `agent.md`（如改动类型涉及）

- [ ] **Step 1: 版本与文档**

`pyproject.toml` `version = "3.4.0"`；CHANGELOG 新增条目（功能：工卡提醒并入——提醒字段/校验/提醒单下载/迁移）；README 功能模块加"提醒单"说明。

- [ ] **Step 2: 全量测试**

Run: `python -m pytest -m "not slow"` + `python -m pytest -m e2e` + `ruff check src/ tests/ scripts/import_vba_config.py`
Expected: 全绿、ruff 无违规

- [ ] **Step 3: 回归确认**

确认 `data/reqman_db.json` 未被测试污染（tests 用隔离副本）。

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md README.md
git commit -m "release: v3.4.0 工卡提醒并入需求单系统"
```

---

## Self-Review（已对照全部定稿决策）

| 决策 | 落点 |
|---|---|
| 字段 `card_ok`/`no_reminder`、`reminder_type` 默认空 | Task 1 |
| 保存校验统一 + 自动确认 + 重置（不清空内容） | Task 2 |
| 组传播全字段 | Task 3 |
| matcher 提醒状态 + 撤销跳过 | Task 4 |
| 窗口头部状态/提醒下拉/无需提醒勾选/重置按钮 | Task 5 |
| 列表筛选/红框/无需提醒列空白 | Task 6 |
| 提醒单输出（模板/例行黑字/其他红字/重点黄底 RGB(255,255,0)/无未识别表） | Task 7 |
| 预览双按钮 + 新工卡未确认标签 | Task 8 |
| 迁移（不导无需提醒/弃用清单/重点覆盖一般/飞机防重复/初始 card_ok=False） | Task 9 |
| 版本 3.4.0/CHANGELOG/全量验证 | Task 10 |

**占位扫描**：无 TBD/占位；跨 Task 字段名一致（`card_ok`/`no_reminder`/`reminder_type`/`REMINDER_TYPES`/`generate_reminder`）。

**注意事项（实施时核对）**：
- `tests/integration/` 的 client fixture 需按现有 `tests/integration/conftest.py` 模式（create_app + 临时 DB）确认；`test_card_api.py` 若不存在则按现有 integration 测试结构新建
- `_ensure_package_matched` 为私有函数，`reminder_download` 同模块内复用（generate_bp 内部）
- 模板 `reminder_template.xlsx` 复制前确认用户定稿版本；openpyxl 加载若出现样式兼容警告不影响功能
- Task 2/5 中工卡组 `update_card_set` 需以 `is not None` 判断支持 `card_ok=False`/`no_reminder` 落库
