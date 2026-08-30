# AMRO 三域数据同步实施计划（v3.5.0）v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **v3.6.0 变更记录**：T7（提醒单异步版本检查）实施后于 v3.6.0 废弃——提醒单回退纯同步，删除 _TASKS/线程/`/generate/task` 路由与 apply_reminder_version_section；版本检查改为工作包行级同步按钮 + 预览页改版清单下载，报告分专业节、日期旧→新、无蓝底；本计划 T7 任务仅存档。

**Goal:** 接入 7 个已验证 AMRO 只读端点：飞机信息页内嵌同步（AMRO 覆盖+在册外清理）、工作包页直读导入+版本变动日志区块、工卡数据页全库版本检查（改版清单 Excel）+ 提醒单实时版本检查（异步化，改版/作废/新工卡蓝底）；AMRO 登录三件套常驻表头。

**Architecture:** `connectors/amro.py` 增加通用 `query_plugin`（白名单/限速/审计/会话异常），三域逻辑收敛在新增 `services/amro_sync.py`；路由分散进现有蓝图（cards_bp/packages_bp/generate_bp）；数据层只加 card.`write_date` 一字段与 runtime `amro_sync_meta` 一键；长任务 daemon 线程+状态轮询；**全程零快照**（两处版本检查均实时拉）。

**Tech Stack:** Python 3.10 / Flask 3.1 / httpx+openpyxl（已有）/ pytest（19 单测+7 集成+e2e）

**Spec:** `docs/superpowers/specs/2026-08-30-amro-data-sync-design.md` v2（九轮评审定稿，执行前必读）

## Global Constraints

- **只读红线**：仅调用 `READONLY_PLUGINS` 白名单 7 端点；BM_RWJS_JS/BM_PRINT_*/BM_GET_ADD_JC 等其余端点一律禁用；请求间隔 ≥`AMRO_RATE_SECONDS`(默认2s)；每次调用追加 `data/amro_audit.jsonl`
- **agent.md 纪律**：提交/合并/推送逐项经用户确认；每次提交更新 CHANGELOG；**UI 改动必须附 e2e 验证证据**；大改走 feature 分支；真实 data/*.json 严禁 checkout/reset，测试一律隔离副本
- 版本 3.5.0；提交风格 `feat: v3.5.0 ...`；每任务独立 commit；三阶段顺序交付（T3 飞机 → T5 工作包 → T6/T7 工卡版本），每阶段末可独立验收
- ponytail：零新依赖；不加抽象基类/任务队列/新蓝图文件；版本变动日志不建新存储（card_logs 筛选视图）
- **工作包清单功能保留为硬性验收项**：📝工作包表格（wpTable）及搜索过滤/点击跳生成/重新匹配全功能不动，重排仅新增区块
- 测试全 mock AMRO（`_FakeClient` 模式），CI 零外呼；会话失效统一 `AmroSessionExpired`→401+P8 文案

## 基线（2026-08-30 amro-research 实测，参数以此为准）

| 端点 | form 参数 | 实测结果 |
|---|---|---|
| `DA_ACREG_LIST` | page=1&rows=300 | total=280 单页全量；含 ACNO/CONF_ACTYPE/ENG_TYPE/FSN/MSN/APU_TYPE/MP_ACTYPE/VALID_STATUS |
| `TD_JC_SMJC_LIST` | status=ISSUED&jcStatus=Y&page=N&rows=500 | total=1319（3 页）；WRITE_DATE 全有 |
| `TD_JC_ALL_EOJC_LIST` | 同上，**不得带 writer**；可选 fleet=a320（小写） | total=5579（12 页）；深分页 38~105s/页（timeout=150）；WRITE_DATE 全有 |
| `BM_TSK_LIST` | gjzStr=&initBase=&baseCode1=&baseCode=KM01&chktp=&planstdstr=D1&planstdEnd=D2&revst=WJS%7CZB%7CYZB%7CKG&xfdw=&actype=&acno=&gjz=&iftj=&ifgzrz=&page=1&rows=50 | **total 恒 0 以 data 为准**；REVNR/ACNO/ACTYPE/ENGTYPE/REVTITLE/CHKTP/PLANSTD/PLANEND |
| `BM_TSK_002_LIST` | revnr=<REVNR>&page=1&rows=50 | 66A 包 123 条全量返回；JCNO/TASK/ZY/JCTITLE/PPCBZSM |
| `BM_TSK_002_LIST_QT` | 同上 | 66A 包 43 条（EO/NRC/LS）；用户 2026-08-30 确认只读 |
| `DA_MPACTYPE_HELP` | FunctionCode=DA_MPACTYPE_HELP&page=1&rows=50 | 15 行机型对照（备用） |

---

### Task 1: query_plugin 通用只读调用器

**Files:** Modify `src/reqman/services/connectors/amro.py`；Test `tests/test_amro_connector.py`

**Interfaces (Produces):**
- `READONLY_PLUGINS: frozenset[str]`；`class AmroSessionExpired(RuntimeError)`
- `async def query_plugin(client, cookies, plugin, form, *, timeout=30) -> dict`（白名单→节流→POST→审计→code 校验）
- `async def fetch_all_pages(client, cookies, plugin, base_form, *, timeout=30, max_pages=30) -> list[dict]`（page 自增 rows=500；total 恒 0 时按行终止）

- [ ] **Step 1: 写失败测试**

```python
class TestQueryPlugin:
    async def test_whitelist_rejects_write_plugin(self, fake_client, monkeypatch):
        import pytest
        from reqman.services.connectors import amro
        with pytest.raises(ValueError):
            await amro.query_plugin(fake_client, {}, "BM_RWJS_JS", {})
        assert fake_client.posts == []

    async def test_session_expired_raises(self, fake_client_code100, monkeypatch):
        from reqman.services.connectors import amro
        monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
        with pytest.raises(amro.AmroSessionExpired):
            await amro.query_plugin(fake_client_code100, {}, "DA_ACREG_LIST", {})

    async def test_audit_line_written(self, fake_client, tmp_path, monkeypatch):
        from reqman.services.connectors import amro
        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(amro, "_audit_path", lambda: audit)
        monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
        await amro.query_plugin(fake_client, {}, "DA_ACREG_LIST", {"page": "1"})
        line = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert line["plugin"] == "DA_ACREG_LIST" and line["code"] == 200

    async def test_fetch_all_pages_zero_total_with_rows(self, fake_client_paged, monkeypatch):
        """BM_TSK_LIST 语义：total 恒 0 但有行 → 按行终止不空转"""
        from reqman.services.connectors import amro
        monkeypatch.setattr(amro.time, "monotonic", lambda: 1e9)
        rows = await amro.fetch_all_pages(None, {}, "BM_TSK_LIST", {"baseCode": "KM01"})
        assert len(rows) == 11
```

- [ ] **Step 2: 跑红** `pytest tests/test_amro_connector.py -k QueryPlugin -v`
- [ ] **Step 3: 最小实现**（READONLY_PLUGINS 常量；模块级 `_last_ts` 节流；`_audit()` JSONL；分页器）
- [ ] **Step 4: 跑绿** + `pytest -m "not slow"` + `ruff check src/ tests/`
- [ ] **Step 5: Commit** `feat: v3.5.0 query_plugin通用只读调用器(白名单/限速/审计)`

### Task 2: 表头登录三件套 + /inventory 简化

**Files:** Modify `templates/base.html`、`blueprints/inventory_bp.py`（ZIP+协议注册文件）、`templates/inventory/index.html`（移除登录区块）、`scripts/` 模板；Test `tests/integration/test_amro_sync_api.py` + e2e

**Interfaces (Produces):**
- 表头：状态徽章（10 分钟轮询+点击即查，调现有 `/inventory/session`）+提示区（P4/P5/P6/P7）+一键登录（`ReqManLogin://` 降级链）+新建配置
- ZIP 配置包新增 `register_protocol.bat`（检测桌面真实路径含 OneDrive 重定向 → reg add HKCU\Software\Classes\ReqManLogin）

- [ ] **Step 1: 失败测试（集成）**

```python
class TestHeaderLogin:
    def test_setup_package_contains_protocol_bat(self, client):
        resp = client.get("/inventory/setup-package")
        assert b"register_protocol.bat" in resp.data or "register_protocol.bat" in zip_names(resp)

    def test_session_endpoint_unchanged(self, client):
        assert client.get("/inventory/session").status_code == 200

    def test_inventory_page_has_no_login_card(self, client):
        """登录区块迁表头后，库存查询页不再含 P4 文案与配置按钮"""
        html = client.get("/inventory").get_data(as_text=True)
        assert "新建配置" not in html
```

e2e（agent.md 硬性）：表头徽章显示、点击立即检查、未注册点击一键登录走降级提示、/inventory 无登录区块（截图）。
- [ ] **Step 2: 跑红**　- [ ] **Step 3: 实现**（base.html 表头块+JS：`setInterval(check,600000)`+`onclick=check()`；提示区渲染 P4/P5/P6/P7；ZIP 模板加注册脚本；inventory/index.html 删登录卡片）
- [ ] **Step 4: 跑绿 + 全量 + e2e**　- [ ] **Step 5: Commit** `feat: v3.5.0 表头AMRO登录三件套(轮询/一键协议/新建配置)+库存页瘦身`

### Task 3: json_store 扩展（write_date + meta + 版本日志筛选）

**Files:** Modify `src/reqman/models/json_store.py`；Test `tests/test_json_store.py`

**Interfaces (Produces):**
- `_FIELDS["card"]`/`_CARD_FIELDS` +`write_date: ""`；`_RUNTIME_KEYS` +`amro_sync_meta`
- `JsonStore.get_amro_sync_meta()/set_amro_sync_meta(domain, payload)`
- `JsonStore.get_version_logs(limit=100) -> list`（card_logs 倒序筛选 changes 含 `write_date` 的条目）

- [ ] **Step 1: 失败测试**

```python
class TestAmroRuntime:
    def test_card_write_date_backcompat(self, json_store):
        r = json_store.add("NEW-100", "卡", "机体", "", "")
        assert r["write_date"] == ""          # _norm 补默认

    def test_sync_meta_roundtrip(self, json_store):
        json_store.set_amro_sync_meta("aircraft", {"added": 3})
        assert json_store.get_amro_sync_meta()["aircraft"]["added"] == 3

    def test_version_logs_filters_card_logs(self, json_store):
        """版本日志=card_logs 中 changes 含 write_date 的条目（无新存储）"""
        r = json_store.add("C-1", "卡", "机体", "", "")
        json_store.update(r["id"], task_name="改名")          # 非版本日志
        json_store.update(r["id"], write_date="2026-08-01 09:00:00")  # 版本日志
        logs = json_store.get_version_logs()
        assert len(logs) == 1 and logs[0]["target_identifier"] == "C-1"
```

- [ ] **Step 2: 跑红**　- [ ] **Step 3: 实现**（字段/键/两方法+一筛选；照抄现有模式）
- [ ] **Step 4: 跑绿 + 全量**　- [ ] **Step 5: Commit** `feat: v3.5.0 card版本字段+同步状态键+版本日志筛选查询`

### Task 4: 飞机信息同步（阶段一）

**Files:** New `src/reqman/services/amro_sync.py`；Modify `blueprints/cards_bp.py`、`templates/cards/aircraft.html`；Test `tests/test_amro_sync.py`、`tests/integration/test_amro_sync_api.py`

**Interfaces (Produces):**
- `async def sync_aircraft(store, client, cookies) -> dict`（报告 `{added, updated, removed:[reg...], total_amro}`）
- 路由：`POST /card/aircraft/amro-sync`（前置检查→确认弹窗已在前端→daemon 线程）、`GET /card/aircraft/amro-status`
- 前置检查装饰器/助手：会话失效 → 401 + P8

- [ ] **Step 1: 失败测试**

```python
class TestSyncAircraft:
    async def test_upsert_and_remove(self, json_store, fake_amro_acreg, monkeypatch):
        from reqman.services import amro_sync
        json_store.add_aircraft("B-1662", "旧机型", "", "", "", "")   # 在册 → 覆盖
        json_store.add_aircraft("B-9999", "A320-232", "", "", "", "") # 不在在册190 → 清理
        monkeypatch.setattr(amro_sync.time, "monotonic", lambda: 1e9)
        rep = await amro_sync.sync_aircraft(json_store, None, {}, fetch=fake_amro_acreg)
        ac = [a for a in json_store.get_aircraft_all() if a["reg"] == "B-1662"][0]
        assert ac["model"] == "A320-232" and ac["apu"] == "131-9(A)"
        assert "B-9999" in rep["removed"]
        assert all(a["reg"] != "B-9999" for a in json_store.get_aircraft_all())
        # 清理/更新均留 card_logs
        assert any(l["operation"] == "delete" for l in json_store._read()["card_logs"])

    async def test_bprefix_match_no_dup(self, json_store, fake_amro_acreg, monkeypatch):
        from reqman.services import amro_sync
        json_store.add_aircraft("1662", "A320-232", "", "", "", "")
        rep = await amro_sync.sync_aircraft(json_store, None, {}, fetch=fake_amro_acreg)
        assert rep["added"] == rep["total_amro"] - 1
```

集成：`POST /card/aircraft/amro-sync` 无会话 → 401+P8；mock 会话+mock fetch → started=true → status 轮询出现报告。
- [ ] **Step 2: 跑红**　- [ ] **Step 3: 实现**（过滤 `MP_ACTYPE==AMRO_AC_FLEET 且 VALID_STATUS=='1'`；三段匹配；清理走 `delete_aircraft`；meta 写 `amro_sync_meta["aircraft"]`；aircraft.html 加按钮+确认弹窗+报告卡+前置检查提示）
- [ ] **Step 4: 跑绿 + 全量 + e2e（本页区块截图）**　- [ ] **Step 5: Commit** `feat: v3.5.0 飞机信息AMRO同步(覆盖更新/在册外清理/日志留档)` —— **阶段一交付点，独立验收**

### Task 5: 工作包直读 + 页面重排 + 版本变动日志区块（阶段二）

**Files:** Modify `services/amro_sync.py`、`blueprints/packages_bp.py`（抽 `_persist_package` 共用）、`templates/packages/upload.html`（**四卡片重排**，spec §8.4）；Test 同步/集成

**Interfaces (Produces):**
- `async def list_amro_packages(client, cookies, base=None, days=7) -> list[dict]`
- `def package_items(rows_routine, rows_other) -> dict`（与 xlsx 解析 item 同构；机身→机体；PPCBZSM 含"撤销"→cancelled；source=例行/其他；aircraft_info 含 REVNR/ACNO/ACTYPE/ENGTYPE/REVTITLE/CHKTP/PLANSTD）
- `async def import_amro_package(store, client, cookies, revnr) -> dict`（拉两清单→package_items→复用 save_work_package+matcher→返回 package_id+计数）
- 路由：`GET/POST /packages/amro-list`、`POST /packages/amro-fetch`、`GET /packages/amro-version-logs`

**页面重排（硬性验收：现有功能全保留）**：Card0 新增「从 AMRO 拉取工作包」（页首，包列表+导入）｜Card1 上传工作清单**保留不动**｜Card2 📝工作包清单（wpTable 搜索过滤/点击跳生成/重新匹配）**保留不动**｜Card3 新增「工卡版本变动日志」（页尾空白处，`get_version_logs` 倒序 50 条简单清单，无筛选/删除）

- [ ] **Step 1: 失败测试**

```python
class TestPackageItems:
    def test_mapping_and_prefix(self, routine_row):
        from reqman.services.amro_sync import package_items
        routine_row["ZY"] = "机身"
        out = package_items([routine_row], [])
        it = out["all_items"][0]
        assert (it["task_code"], it["task_type"], it["category"], it["source"]) == (
            routine_row["JCNO"], routine_row["TASK"], "机体", "例行")
        assert out["aircraft_info"]["package"] == routine_row["REVNR"]

    def test_cancelled_by_remark(self, routine_row):
        from reqman.services.amro_sync import package_items
        routine_row["PPCBZSM"] = "该卡已撤销|"
        assert package_items([routine_row], [])["all_items"][0]["cancelled"] is True

class TestAmroVersionLogsView:
    def test_packages_page_shows_version_logs(self, client, prefilled_app):
        """工作包页面渲染版本变动日志区块（card_logs 筛选视图）"""
        html = client.get("/upload").get_data(as_text=True)  # 工作包页路由按实际调整
        assert "工卡版本变动日志" in html
```

集成：`POST /packages/amro-fetch`（mock 两清单）→ `package_id` 返回 + `get_work_packages()` 新增一条 items 正确；`GET /packages/amro-version-logs` 返回倒序筛选清单。
- [ ] **Step 2: 跑红**　- [ ] **Step 3: 实现**（抽 `_persist_package` 供 upload/直读共用；工作包页三区块重排：AMRO 拉取/上传兜底/版本日志清单）
- [ ] **Step 4: 跑绿 + 全量 + e2e（页面重排+拉包流程截图）**　- [ ] **Step 5: Commit** `feat: v3.5.0 工作包AMRO直读(页面重排/版本变动日志区块)` —— **阶段二交付点，独立验收**

### Task 6: 全库版本检查 + 改版清单 Excel（阶段三·上）

**Files:** Modify `services/amro_sync.py`、`blueprints/cards_bp.py`、`templates/cards/list.html`；Test 同步/集成

**Interfaces (Produces):**
- `async def full_version_check(store, client, cookies) -> dict`
  （拉两清单→过滤库内卡→逐卡比对 write_date：变化→更新+card_logs；作废=库内码不在已发布有效集合→不入卡字段、仅入报告；产出 `{revised:[{task_code,old_wd,new_wd}], cancelled:[...]}`）
- `def build_version_report_excel(report) -> bytes`（openpyxl：改版 sheet + 作废 sheet）
- 路由：`POST /card/amro-version-check`（daemon 线程）、`GET /card/amro-version-status`、`GET /card/amro-version-report/<ts>`（xlsx 下载）

- [ ] **Step 1: 失败测试**

```python
class TestFullVersionCheck:
    async def test_revised_updates_card_and_logs(self, json_store, fake_amro_cards, monkeypatch):
        from reqman.services import amro_sync
        r = json_store.add("CSCA320-256652-01-1-X", "检查救生衣", "电子", "RST", "")
        monkeypatch.setattr(amro_sync.time, "monotonic", lambda: 1e9)
        rep = await amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards)
        card = json_store.get(r["id"])
        assert card["write_date"] == "2026-08-01 09:00:00"
        assert rep["revised"][0]["old_wd"] == ""
        assert any(c["field"] == "write_date" for l in json_store._read()["card_logs"]
                   for c in l["changes"])

    async def test_cancelled_detected_not_deleted(self, json_store, fake_amro_cards, monkeypatch):
        from reqman.services import amro_sync
        r = json_store.add("EOJC-A320-57-2025-002-B", "卡", "机体", "", "")
        monkeypatch.setattr(amro_sync.time, "monotonic", lambda: 1e9)
        rep = await amro_sync.full_version_check(json_store, None, {}, fetch=fake_amro_cards)
        assert "EOJC-A320-57-2025-002-B" in [c["task_code"] for c in rep["cancelled"]]
        assert json_store.get(r["id"]) is not None   # 不删

    def test_report_excel_has_two_sheets(self):
        from reqman.services.amro_sync import build_version_report_excel
        buf = build_version_report_excel({"revised": [{"task_code": "C-1", "old_wd": "", "new_wd": "2026-08-01"}],
                                          "cancelled": [{"task_code": "C-2"}]})
        import io, openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        assert wb.sheetnames == ["改版工卡", "作废工卡"]
```

- [ ] **Step 2: 跑红**　- [ ] **Step 3: 实现**（比对只针对库内卡；作废只入报告；Excel 两 sheet；list.html 加按钮+前置检查+进度+下载提示）
- [ ] **Step 4: 跑绿 + 全量 + e2e**　- [ ] **Step 5: Commit** `feat: v3.5.0 全库工卡版本检查(实时比对/作废检测/改版清单Excel)`

### Task 7: 提醒单集成（异步实时版本检查 + 改版/新工卡蓝底）（阶段三·下）

**Files:** Modify `blueprints/generate_bp.py`、`services/amro_sync.py`（+`check_cards_against_amro`）、`templates/generate/*.html`；Test 同步/集成/e2e

**Interfaces (Produces):**
- 提醒单生成异步化：`POST /generate/reminder` → `{task_id}`；`GET /generate/task/<id>` 状态；`GET /generate/task/<id>/download`
- `async def check_cards_against_amro(store, client, cookies, task_codes) -> dict`（实时拉两清单，客户端过滤到 task_codes；比对后更新卡 write_date；返回 revised/cancelled/new_by_category）
- 提醒单 Excel 附加：「改版工卡」区块（工卡号/旧/新编写日期）与**新工卡按专业分组区块，两种行均为蓝色底色（0000FF）**；作废工卡浅红底（FFC7CE）+行首"已作废"（openpyxl PatternFill）

- [ ] **Step 1: 失败测试**

```python
class TestReminderVersionCheck:
    def test_revised_and_new_cards_blue_fill(self):
        from reqman.services.amro_sync import apply_reminder_version_section
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active
        report = {"revised": [{"task_code": "CSCA320-256652-01-1-X", "old_wd": "", "new_wd": "2026-08-01 09:00:00"}],
                  "cancelled": [{"task_code": "EOJC-A320-57-2025-002-B"}],
                  "new_by_category": {"电子": [{"task_code": "EOJC-A320-31-2026-007-A", "task_name": "实时数据改装"}]}}
        apply_reminder_version_section(ws, report)
        def blue_cells():
            return [c for row in ws.iter_rows() for c in row
                    if c.fill and c.fill.fgColor and c.fill.fgColor.rgb in ("FF0000FF", "0000FF")]
        codes_in_blue = {ws.cell(row=c.row, column=1).value for c in blue_cells()}
        assert "CSCA320-256652-01-1-X" in codes_in_blue   # 改版工卡蓝底
        assert "EOJC-A320-31-2026-007-A" in codes_in_blue  # 新工卡蓝底（按专业分组）
        assert "EOJC-A320-57-2025-002-B" not in codes_in_blue  # 作废=浅红底非蓝

    async def test_reminder_async_flow(self, client, monkeypatch):
        monkeypatch.setattr("reqman.services.amro_sync.check_cards_against_amro",
                            lambda *a, **k: _ok_coro({"revised": [], "cancelled": []}))
        resp = client.post("/generate/reminder", headers=ajax_headers, data={...})
        task_id = resp.get_json()["data"]["task_id"]
        assert client.get(f"/generate/task/{task_id}").get_json()["data"]["status"] in ("pending", "running", "done")
```

- [ ] **Step 2: 跑红**　- [ ] **Step 3: 实现**（task 状态机最小化 pending/running/done/error；旧同步路径保留开关一个版本；generate 页加"工卡版本检查"勾选+进度+完成下载）
- [ ] **Step 4: 跑绿 + 全量 + e2e（异步流程+提醒单区块截图）**　- [ ] **Step 5: Commit** `feat: v3.5.0 提醒单实时版本检查(异步生成/改版作废区块/新工卡蓝底)`

### Task 8: 收尾验证

- [ ] `pytest -m "not slow"` 全量 + `pytest -m e2e` + `ruff check src/ tests/` 通过
- [ ] 三阶段冒烟（需真实会话，人工配合）：①飞机同步（134 架存量 diff 合理、清理清单确认）②拉一个真实 66A 包对照人工 xlsx ③全库检查（抽查 3 张改版卡）+ 提醒单（含版本检查）生成下载
- [ ] `data/amro_audit.jsonl` 调用留痕完整；白名单外调用被拒有记录
- [ ] CHANGELOG 3.5.0（Added/Changed/遗留：撤销判定待实测/协议注册一次性成本）+ SERVER_README + 版本串统一

## 明确不做（各留一行升级路径）

- 工卡改版主动推送：提醒单内输出已覆盖当前工作流，推送下一专项
- 版本快照/增量同步：两处检查均实时拉，用户已确认不留快照
- AMRO 工卡 PDF 批量下载（GK 字段）：导出类动作，需另行人工确认
- 库存预警功能：仅预留页面空间
- QM_CK_PACKAGE_* 归档视图、BM_GET_ADD_JC：需要时按需人工确认

## Self-Review

- 规格覆盖：spec §二 决策 1~15 → T2（#13/14/12）T3（#4/10）T4（#2/3）T5（#11 工作包部分/10 展示）T6（#5①/7/8）T7（#5②/6/9）一一对应。✓
- 占位符扫描：T7 Step1 集成用例 `data={...}` 为占位，实施时按现有提醒单表单字段补全；T5 upload 页路由名按实际（/upload）对齐。⚠ 实施者注意
- 类型一致性：`fetch` 注入参数仅测试用；`package_items` 输出与 `packages_bp` 现有 item 结构逐键对齐（T5 集成守护）；`get_version_logs` 依赖 `_detect_changes` 产出 `changes[].field=="write_date"`。✓
- agent.md：三提交点（T4/T5/T6+T7 后）各附 e2e 证据；提交/合并/推送逐项请示。✓
