# 确认字段统一与提醒单修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复提醒单飞机信息缺失（定检级别/FSN/MSN/APU）、未确认工卡未显示于新工卡区，并将确认字段命名与 UI 可见性统一（工具/航材/提醒三块对称确认，总确认 card_ok 置表头，备注置表底部）。

**Architecture:** 遵循现有"工厂+蓝图+服务层"。`no_reminder` 重命名为 `reminder_confirmed`（语义不变）；工具/航材/提醒三块对称判定（有数据自动确认，无数据须勾选确认框）；`match_work_package_items` 与 `_ensure_package_matched` 后处理统一为"任一确认缺失→new_cards"；提醒单 form_data 补齐 `level/fsn/msn/apu`（level 取工作清单 H2，fsn/msn/apu 按 reg 查数据库 aircraft）。UI 统一规则：总确认在表头、分项确认在各区块下、备注在底部。数据仅存 `data/reqman_db.json`，测试一律用隔离 DB 副本。

**Tech Stack:** Python 3.10+、Flask 3.1+、openpyxl、pytest。

**Spec:** 方案经多轮业务澄清定稿（字段命名/确认判定/布局统一均确认），未单独写 spec 文件。

## Global Constraints

- 执行分支：**feature**（`fbb8d31`，版本 3.4.0）；**禁止 commit/push**，完成后汇报 diff 摘要 + 测试结果
- `no_reminder` → `reminder_confirmed` 全库重命名（语义不变：勾选"确认无需提醒"→True，`reminder_type` 留空）；现有 data 无该字段，`_norm` 兜底默认 False，无需数据迁移
- 确认判定三块对称：`tools_confirmed = bool(tools) or (not tools and confirm_no_tools)`；`materials_confirmed` 同理；`reminder_confirmed = bool(reminder_type) or (not reminder_type and confirm_no_reminder)`；由后端保存时计算
- 提醒下拉框：`一般提醒`/`重点提醒`/默认空；选类型即确认，否则须勾"确认无需提醒"；前端 JS 校验同步
- 未确认判定统一：`not (tools_confirmed and materials_confirmed and reminder_confirmed)` → 进新工卡区
- 提醒单 form_data 补 `level`（=H2）/`fsn`/`msn`/`apu`（fsn/msn/apu 按 reg 查数据库 aircraft，无则空，reg 匹配试去/加 `B-` 前缀）
- UI 统一规则：总确认（card_ok）在表头横幅、分项确认在各区块下方、备注在表单/详情底部；列表行保持 blink 高亮
- 测试隔离 DB 副本，严禁触碰 `data/reqman_db.json`；命令 `python -m pytest -m "not slow" -o addopts=""`、`ruff check src/ tests/`
- 遵循 `agent.md`：大改走 feature 分支；提交前 `git branch` 确认；commit/merge/push 各自需用户确认

---

### Task 1: 字段重命名 `no_reminder` → `reminder_confirmed`

**Files:**
- Modify: `src/reqman/models/json_store.py`
- Modify: `src/reqman/services/card_service.py`
- Modify: `src/reqman/blueprints/cards_bp.py`
- Modify: `src/reqman/blueprints/generate_bp.py`
- Modify: `src/reqman/api_docs.py`
- Modify: `src/reqman/templates/cards/form.html`
- Modify: `src/reqman/templates/cards/set_form.html`
- Modify: `src/reqman/templates/cards/list.html`
- Modify: `src/reqman/templates/cards/sets.html`
- Modify: `src/reqman/templates/generate/form.html`
- Test: `tests/` 下全部引用点

**Interfaces:**
- Produces:
  - card/set 字段：`reminder_confirmed=False`（替代 `no_reminder=False`）
  - `_CARD_FIELDS`/`_SET_FIELDS`、`add()`/`add_set()` 默认值、`update()`/`update_set()` 白名单同步
  - `card_service.add_card/update_card/add_card_set/update_card_set` 参数与 updates 键
  - `cards_bp._parse_reminder()` 返回第二项 `reminder_confirmed`
  - `generate_bp.reminder_download` 过滤条件 `item.get("reminder_confirmed")`
  - 模板与 api_docs schema 字段名

- [ ] **Step 1: 更新 json_store.py**（`_FIELDS`/`_CARD_FIELDS`/`_SET_FIELDS`/`add`/`add_set`/`update`/`update_set` 白名单）
- [ ] **Step 2: 更新 card_service.py**（add/update 三方法参数与 updates 键）
- [ ] **Step 3: 更新 cards_bp.py**（`_parse_reminder` + 4 个提交入口传递）
- [ ] **Step 4: 更新 generate_bp.py、api_docs.py**
- [ ] **Step 5: 更新全部模板引用**（form/set_form/list/sets/generate-form）
- [ ] **Step 6: 更新测试全部 `no_reminder` 引用**
- [ ] **Step 7: 运行确认**：`python -m pytest tests/test_json_store.py tests/test_card_service.py tests/test_work_package_matcher.py -o addopts=""` 通过

### Task 2: 三块对称确认判定逻辑

**Files:**
- Modify: `src/reqman/blueprints/cards_bp.py`
- Modify: `src/reqman/templates/cards/form.html`
- Modify: `src/reqman/templates/cards/set_form.html`
- Test: `tests/test_card_api.py`、`tests/test_card_service.py`

**Interfaces:**
- Produces:
  - `_parse_and_validate_tools_mats` 判定改为：`tools_confirmed = bool(tools) or (not tools and bool(confirm_no_tools))`；materials 同理
  - `_parse_reminder` 改为：`reminder_confirmed = bool(reminder_type) or (not reminder_type and bool(confirm_no_reminder))`
  - 前端 JS 校验：选提醒类型或勾"确认无需提醒"二选一，否则拦截并提示

- [ ] **Step 1: 重写 `_parse_and_validate_tools_mats` 判定**
- [ ] **Step 2: 重写 `_parse_reminder` 判定**
- [ ] **Step 3: 同步 JS 校验逻辑（form.html/set_form.html）**
- [ ] **Step 4: 补测试用例**（有数据自动确认 / 无数据须勾选 / 提醒选类型即确认）
- [ ] **Step 5: 运行确认**：对应测试通过

### Task 3: 未确认工卡进新工卡区

**Files:**
- Modify: `src/reqman/services/work_package_matcher.py`
- Modify: `src/reqman/blueprints/generate_bp.py`
- Test: `tests/test_work_package_matcher.py`

**Interfaces:**
- Produces:
  - matcher `is_unconfigured = not (tools_confirmed and materials_confirmed and reminder_confirmed)`
  - `_ensure_package_matched` 后处理条件同步（任一未确认→new_cards，标记 unconfirmed/reason）

- [ ] **Step 1: 更新 matcher 判定**
- [ ] **Step 2: 更新 generate_bp 后处理**
- [ ] **Step 3: 补"任一未确认→new_cards"用例**
- [ ] **Step 4: 运行确认**

### Task 4: 提醒单飞机信息（定检级别/FSN/MSN/APU）

**Files:**
- Modify: `src/reqman/services/worklist_parser.py`
- Modify: `src/reqman/blueprints/generate_bp.py`
- Test: `tests/test_reminder_generator.py`、`tests/integration/test_reminder_api.py`

**Interfaces:**
- Produces:
  - `_parse_aircraft_info`/`merge_aircraft_info` 新增 `level`（=H2 值，与 description 同源）
  - `reminder_download`：按 reg `find_aircraft_by_reg` 查飞机（失败试去/加 `B-` 前缀），form_data 增加 `level/fsn/msn/apu`
  - 提醒单 B2=定检级别、C3=APU型号、A4=FSN、B4=MSN 正常输出

- [ ] **Step 1: worklist_parser 新增 level**
- [ ] **Step 2: reminder_download 补飞机信息查询与 form_data**
- [ ] **Step 3: 更新提醒单测试断言**
- [ ] **Step 4: 运行确认**

### Task 5: UI 布局统一

**Files:**
- Modify: `src/reqman/templates/cards/form.html`
- Modify: `src/reqman/templates/cards/set_form.html`
- Modify: `src/reqman/templates/cards/list.html`
- Modify: `src/reqman/templates/cards/sets.html`

**Interfaces:**
- Produces:
  - 统一规则：总确认（card_ok）在表头横幅（含重置确认）；分项确认在各区块（提醒/工具/航材）下方；备注在表单/详情底部
  - form/set_form：基本信息区移除 reminder_type 下拉框 → 独立"提醒类型"区块（标题+下拉框），区块下"确认状态 + ☑确认无需提醒"；工具/航材区块下"确认状态 + ☑确认无工具/无航材"；底部备注输入框（保留既有值，修复 card_edit 清空 bug）
  - list/sets 详情弹窗：顶部总确认横幅、各区块下确认状态、底部备注；列表行保持 blink 高亮

- [ ] **Step 1: 重构 form.html**
- [ ] **Step 2: 重构 set_form.html**
- [ ] **Step 3: 重构 list.html 详情弹窗**
- [ ] **Step 4: 重构 sets.html 详情弹窗**
- [ ] **Step 5: 前端 smoke 检查**（页面渲染无 JS 错误）

### Task 6: 测试更新 + 全量验证

**Files:**
- Test: `tests/test_json_store.py`、`tests/test_card_service.py`、`tests/test_work_package_matcher.py`、`tests/test_reminder_generator.py`、`tests/integration/test_reminder_api.py`、`tests/integration/test_card_api.py`、`tests/test_import_vba_config.py`

**Interfaces:**
- Produces:
  - 字段改名断言、确认逻辑断言、提醒单 level/fsn/msn/apu 断言、matcher 任一未确认用例

- [ ] **Step 1: 更新相关测试**
- [ ] **Step 2: 全量测试**：`python -m pytest -m "not slow" -o addopts=""`（预期 326 通过）
- [ ] **Step 3: ruff**：`ruff check src/ tests/`（0 错误）
- [ ] **Step 4: smoke**：生成提醒单验证 B2/C3/A4/B4 字段输出
- [ ] **Step 5: 汇报** diff 摘要 + 测试结果，等待用户确认 commit/merge