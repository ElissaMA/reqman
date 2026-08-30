# AMRO 三域数据同步设计文档（飞机 / 工作包 / 工卡版本）v2

> 日期：2026-08-30 | 版本目标：3.5.0 | 分支：feature | 状态：定稿 v2（经九轮需求评审确认，取代 v1）
>
> **v3.6.0 变更记录（UI 大改 + 版本域重构）**：① 布局改左侧垂直侧栏，登录三件套迁主区顶部 sticky 登录框；② 查询按钮统一命名并接入 QueryCard 进度助手；③ 新增全局查询互斥（一次一个 AMRO 查询，冲突 409）；④ **T7 提醒单异步版本检查废弃**——提醒单回退纯同步，版本检查改为工作包行级同步按钮（`POST /packages/<id>/amro-version-check`）+ 预览页改版清单下载；报告按专业分节（卡号|卡名|日期 旧→新），废除蓝底；⑤ 同步状态迁内存 QUERY_STATUS（`amro_sync_meta` 持久键删除）。本文其余章节按 v3.5.0 定稿保留存档。
>
> 实施前提：**方案完全确认前不动需求单代码**；实施顺序 **飞机信息 → 工作包 → 工卡版本** 三阶段，每阶段独立验收。
> 无 cron、无 CLI、无自动重登——全部功能手动触发。

## 一、背景与目标

需求单系统三份基础数据全靠人工：飞机 134 架手工维护、工卡 600 张手工录入（无版本概念，
AMRO 改版无法感知）、工作包靠人工从 AMRO 页面打印 xlsx 再上传解析。本设计接入 amro-research
项目 2026-08-30 已实测验证的 7 个 AMRO 只读查询端点（字段级映射核对通过），实现：

1. **飞机信息**：以 AMRO 为准同步（含 APU 补齐），不在册的清理；
2. **工作包**：从 AMRO 任务接收页直读工卡清单导入，替代人工打印上传；
3. **工卡版本**：以 AMRO 编写日期（WRITE_DATE）为版本主轴，全库版本检查 + 提醒单内
   工作包级版本检查双入口，改版/作废/新工卡三态输出；
4. **登录体验**：AMRO 登录状态与一键登录常驻全系统表头。

同时补上 CHANGELOG 遗留的"AMRO 查询零审计"问题。

## 二、已确认决策（九轮评审记录）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 实施节奏 | 方案完全确认前不动代码；按 飞机→工作包→工卡版本 顺序实施 |
| 2 | 飞机冲突策略 | AMRO 数据覆盖（AMRO 为准）；**库内不在 AMRO 在册集合的飞机删除**（判定集合=在册190，见#3） |
| 3 | 飞机清理判定 | AMRO 拉取后客户端过滤 `MP_ACTYPE=='A320' 且 VALID_STATUS=='1'`（在册 190 架）为准 |
| 4 | 工卡版本字段 | **卡只新增 1 个字段 `write_date`**（AMRO 编写日期）；版本比对按编写日期 |
| 5 | 版本检查入口 | 两处：①工卡数据页"全库版本检查"（输出独立改版清单 Excel）②提醒单生成时对每个工作包内工卡检查（输出在提醒单内） |
| 6 | 比对数据源 | **两处检查都用 AMRO 实时数据，本地不留任何快照** |
| 7 | 工卡范围 | 只比对现有库内工卡 / 包内工卡，不用 AMRO 全量建数据；**库内已在 AMRO 作废的工卡要挑出来** |
| 8 | 作废处置 | 标记 + 提醒单列出，不删除（人工定夺） |
| 9 | 提醒单集成 | 每次生成提醒单实时拉 AMRO 比对（生成异步化）；改版输出"改版工卡"区块；**改版工卡与新工卡行均以蓝色底色标示**（新工卡按专业分组输出工卡名；作废行浅红底+文字标注） |
| 10 | 版本变动日志 | **只写 card_logs 总日志，不建新存储**；工作包页面筛选显示 changes 含 write_date 的条目（简单清单，无日志页全功能） |
| 11 | UI 总形态 | 表头常驻登录三件套；飞机同步做进飞机信息页；工作包同步+版本变动日志做进工作包页面（UI 重排）；工卡版本检查做进工卡数据页 |
| 12 | 库存查询页 | 移除 AMRO 登录相关区块（迁表头），只留库存查询，**预留库存预警数据空间** |
| 13 | 状态检查 | 表头登录状态：**每 10 分钟轮询 + 点击状态栏立即检查**；提示显示在表头提示区 |
| 14 | 桌面一键登录 | 新建配置默认引导保存/解压至桌面；一键登录经一次性注册的 `ReqManLogin://` 协议在**桌面路径**找配置执行（详见 §7） |
| 15 | 只读边界 | 仅调用 7 个已验证查询端点（白名单硬编码）；写/生成端点（BM_RWJS_JS/BM_PRINT_*/BM_GET_ADD_JC 等）一律禁用 |
| 16 | 工作包清单保留 | 工作包页面**保留现有工作包清单功能**（📝工作包表格 wpTable 及搜索/生成/重新匹配全部不动），重排仅为新增区块 |

## 三、核心流程

### 3.1 表头登录状态时序
```
页面加载 → GET /inventory/session → 表头提示区显示：
  ✅ 登录有效 剩余 X 分钟（P5） ｜ ❌ 未登录（P4） ｜ 过期（P7） ｜ ⚠ 挤掉警示（P6 常驻小字）
每 10 分钟自动轮询刷新；点击状态栏立即检查一次
```

### 3.2 功能前置检查（四类查询功能通用）
```
点击 库存查询/飞机同步/工作包拉取/工卡版本检查 → 先查会话
  ├─ 有效 → 弹确认（如涉及清理/长任务）→ 执行
  └─ 未登录/过期 → 阻断，显示 P8 语义文案「登录已失效…请重新运行登录脚本后重试」
```

### 3.3 飞机同步流程（飞机信息页）
```
[从 AMRO 同步] → 前置检查 → 确认弹窗（含"将删除不在册飞机"警示）→ 后台线程：
拉 DA_ACREG_LIST(page=1&rows=300, 280条)
→ 过滤 MP_ACTYPE=A320 且 VALID_STATUS=1（在册190）
→ 逐架 reg 三段匹配（原样/去B-/补B-）：
   命中 → 六字段覆盖更新（reg/model/engine/fsn/msn/apu）+ card_logs
   未命中 → 新增飞机 + card_logs
→ 库内在册集合之外的飞机 → 删除 + card_logs（被删清单入报告）
→ 报告写入 amro_sync_meta，页面展示：新增 X / 更新 Y / 清理 Z（附清单）
```

### 3.4 工作包直读流程（工作包页面）
```
[刷新 AMRO 包列表] → BM_TSK_LIST（baseCode=KM01，日期窗=今±7天，revst=WJS|ZB|YZB|KG）
→ 表格展示（包号/状态/机号/机型/描述/级别/计划时间）→ 选包 [导入]
→ 拉 BM_TSK_002_LIST + BM_TSK_002_LIST_QT（revnr）
→ 字段映射为现有 item 结构（§6.3）→ 复用 save_work_package + work_package_matcher 入库
→ 同 (reg, description) 重新导入即覆盖（沿用现有语义）
```

### 3.5 工卡版本检查流程（双入口，均实时拉、无快照）
```
入口① 全库版本检查（工卡数据页按钮）→ 后台线程：
  拉 TD_JC_SMJC_LIST(3页) + TD_JC_ALL_EOJC_LIST(~12页, 去writer, timeout=150)
  → 客户端过滤出库内工卡的 AMRO 记录
  → 逐卡比对：AMRO write_date ≠ 卡 write_date → 更新卡 + card_logs（changes 含 write_date）
  → 作废检测：库内 task_code 不在 AMRO 已发布有效(JC_STATUS=Y&ISSUED)集合 → 作废（不删）
  → 生成改版清单 Excel（改版 sheet + 作废 sheet）→ 页面提示下载
入口② 提醒单生成（generate 页勾选工卡版本检查）→ 后台线程：
  生成提醒单数据 → 实时拉 AMRO（客户端过滤到提醒单涉及工作包的工卡）
  → 包内工卡逐张比对 → 提醒单附加：
     「改版工卡」区块（工卡号/旧编写日期/新编写日期，数据行蓝色底色）
     作废工卡列出（浅红底+行首"已作废"）
     新工卡（包内有/卡库无）按专业分组输出工卡名、蓝色底色
  → 比对后更新相关卡的 write_date
→ 两入口的版本变动均只写 card_logs（changes 含 write_date 即版本日志），工作包页面筛选展示
```

### 3.6 提醒单异步化（必要改造）
实时拉取需 3~15 分钟，同步请求必超 gunicorn 120s 超时：
```
POST /generate/reminder → 立即返回 task_id → 页面轮询任务状态 → 完成后提供 Excel 下载链接
```

## 四、架构设计

### 4.1 分层（路由分散进现有蓝图，不新建页面蓝图）
```
services/connectors/amro.py    +query_plugin 通用只读调用器（白名单/限速/审计/会话异常）
services/amro_sync.py          三域同步编排（sync_aircraft/list_packages/fetch_package/
                               full_version_check/提醒单比对钩子）
blueprints/cards_bp.py         +飞机同步路由、全库版本检查路由、报告下载
blueprints/packages_bp.py      +AMRO 包列表/导入路由；抽取 item→入库共用函数（upload 与直读共用）
blueprints/generate_bp.py      +提醒单异步化（task 状态/下载）；版本检查集成
blueprints/inventory_bp.py     session/上传路由保留（表头复用）；ZIP 配置包 +register_protocol.bat
templates/base.html            表头三件套（状态/一键登录/新建配置）+ 提示区
templates/cards/*.html         飞机信息页/工卡列表页内嵌同步与检查区块
templates/packages/*.html      工作包页面重排（上传兜底+AMRO 拉包+版本变动日志区块）
templates/inventory/index.html 移除登录区块，只留库存查询
models/json_store.py           card+write_date；runtime+amro_sync_meta；版本日志筛选查询
config.py                      +AMRO_RATE_SECONDS/AMRO_AUDIT_FILE/AMRO_AC_FLEET/AMRO_BASE_DEFAULT
```

### 4.2 ponytail 边界
不做连接器抽象基类/注册器；不做任务队列（daemon Thread + amro_sync_meta 状态位）；
不引数据库；不建新蓝图文件；不建版本日志新存储（card_logs 筛选视图）。

## 五、接口设计（统一 api_success/api_error）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/inventory/session` | GET | （现有）表头状态轮询复用 |
| `/inventory/setup-package` | GET | （现有，扩展）ZIP 增加 register_protocol.bat |
| `/card/aircraft/amro-sync` | POST | 飞机同步（后台线程，立即返回 started） |
| `/card/aircraft/amro-status` | GET | 飞机同步进度/报告（amro_sync_meta.aircraft） |
| `/card/amro-version-check` | POST | 全库版本检查（后台线程） |
| `/card/amro-version-status` | GET | 检查进度 |
| `/card/amro-version-report/<ts>` | GET | 改版清单 Excel 下载 |
| `/packages/amro-list` | GET/POST | AMRO 任务接收包列表 |
| `/packages/amro-fetch` | POST | revnr → 拉清单入库 → package_id |
| `/packages/amro-version-logs` | GET | 版本变动日志（card_logs 筛选，倒序） |
| `/generate/reminder` | POST | （改造）异步化：返回 task_id |
| `/generate/task/<id>` | GET | 异步任务状态 |
| `/generate/task/<id>/download` | GET | 完成后下载 |

## 六、数据与安全

### 6.1 数据库变动（最小，零迁移）
| 变动 | 内容 |
|------|------|
| card | `_FIELDS["card"]` +`write_date: ""`（`_norm` 自动补默认，旧数据零迁移） |
| runtime | `_RUNTIME_KEYS` +`amro_sync_meta`（各功能运行状态/报告/错误） |
| 不变 | work_packages / card_sets / card_logs 结构；**无版本快照存储** |

### 6.2 只读与审计
- `READONLY_PLUGINS` frozenset 硬编码 7 端点：DA_ACREG_LIST / DA_MPACTYPE_HELP /
  TD_JC_SMJC_LIST / TD_JC_ALL_EOJC_LIST / BM_TSK_LIST / BM_TSK_002_LIST / BM_TSK_002_LIST_QT
- 请求间隔 ≥2s（AMRO_RATE_SECONDS）；每次调用追加 `data/amro_audit.jsonl`（.gitignore）
- code=100 → `AmroSessionExpired` → 路由层 401 + P8 文案；不自动重登

### 6.3 字段映射（amro-research 实测，全量见 plan 基线表）
- 飞机：ACNO→reg、CONF_ACTYPE→model、ENG_TYPE→engine、FSN→fsn、MSN→msn、**APU_TYPE→apu**
- 工作包清单：JCNO→task_code、TASK→task_type、**ZY→category（"机身"→"机体"沿用解析器）**、
  JCTITLE→task_name、PPCBZSM→remark（含"撤销"→cancelled）；包头 REVNR/ACNO/ACTYPE/ENGTYPE/
  REVTITLE/CHKTP/PLANSTD ↔ xlsx Row2 的包号/机号/机型/描述/级别
- 工卡版本：JC_NO→task_code 精确匹配，**WRITE_DATE 为版本主轴**（两清单零缺失）

## 七、登录与桌面一键协议设计

```
新建配置：下载 ZIP（amro_login.py + start_login.bat + register_protocol.bat + README）
  README 引导解压至【桌面】（浏览器下载目录无法由网页控制，ZIP 内含"移至桌面"的 .bat 辅助可选项）
register_protocol.bat（双击一次，每台机器一次）：
  检测真实桌面路径（%USERPROFILE%\Desktop 或 OneDrive 桌面重定向）
  → reg add HKCU\Software\Classes\ReqManLogin ... command 指向桌面路径 start_login.bat
一键登录（表头按钮）：
  已注册 → location.href='ReqManLogin://login' → 系统唤起桌面脚本 → 浏览器弹一次安全确认 → 登录 → 自动上传 cookie
  未注册 → 降级：提示下载配置包并按 README 操作（P10/P11/P12）
```
约束声明：浏览器沙箱不能直接执行本地文件，协议注册是实现"真一键"的必要一次性成本；
服务器端登录上传端点（/inventory/login/upload）维持现状。

## 八、前端页面设计（DOM 级具体方案）

### 8.1 表头 `templates/base.html`（全页面常驻）
导航栏右侧追加状态区，导航栏正下方追加提示条：
```
[nav-right] <span id="amroStatus">✅ 剩余58分</span>（badge，onclick=checkNow()）
            <button id="amroQuickLogin" class="btn btn-outline-light btn-sm">⚡一键登录</button>
            <a class="btn btn-outline-light btn-sm" href="/inventory/setup-package">🛠新建配置</a>
[提示条]    <div id="amroAlert">…P4/P5/P6/P7 文案…</div>（紧贴导航栏下方，可手动关闭）
JS：checkNow() 调 GET /inventory/session 渲染徽章与提示区；setInterval(checkNow, 600000)；
    一键登录=location.href='ReqManLogin://login'，8 秒无响应视为未注册 → toast 降级指引（P10/P11/P12）
```

### 8.2 飞机信息页 `templates/cards/aircraft.html`
```
card-header：[飞机信息 N]  ……  [+ 新增飞机] [⟳ 从 AMRO 同步](btn#amroSyncAir, outline-primary sm)
点击 → 前置会话检查（P8 阻断）→ 确认 modal：
   「将从 AMRO 覆盖更新在册飞机；不在册的 M 架将被删除（列表见报告）。确认同步？」
→ 按钮禁用+spinner，轮询 /card/aircraft/amro-status
→ 完成：header 下插入报告卡（新增 X / 更新 Y / 清理 Z + 被删清单 <details> 折叠）→ acTable 自动刷新
```

### 8.3 工卡数据页 `templates/cards/list.html`
```
card-header：[工卡信息 N]  ……  [+ 新增工卡] [🔍 工卡版本检查](btn#amroVerCheck, outline-primary sm)
点击 → 前置会话检查 → 确认（「实时比对 AMRO，约 3~15 分钟，后台执行」）→ 完成后 header 下插入结果卡：
   改版 X 张 / 作废 Y 张 + [⬇ 下载改版清单]（GET /card/amro-version-report/<ts>）
卡片列表不加列（write_date 在工卡编辑页表单中展示，只读）
```

### 8.4 工作包页面 `templates/packages/upload.html` 重排（四卡片；**现有功能全保留**）
```
Card 0【新增·页首】从 AMRO 拉取工作包
   [刷新包列表] → 表格（包号/状态/机号/机型/描述/级别/计划开工/操作[导入]）→ 导入=前置检查+进度+行内完成标记
Card 1【保留不动】上传工作清单（例行/其他双 upload-zone，现有 /upload 逻辑）
Card 2【保留不动】📝工作包 清单（wpTable：搜索过滤/点击跳生成/重新匹配，全部现有功能）
Card 3【新增·页尾空白处】工卡版本变动日志（简单清单：时间|工卡号|旧编写日期|新编写日期|来源）
   数据=GET /packages/amro-version-logs（card_logs 筛选视图），倒序最近 50 条，无筛选/删除功能
空状态文案：「暂无工作包，请上传工作清单或从 AMRO 拉取」
```

### 8.5 提醒单 `templates/generate/form.html` + Excel
```
生成按钮区（"✅ 生成需求单下载"旁）：
   <label>[x] 工卡版本检查（实时比对 AMRO，约 3~15 分钟）</label>（默认勾选）
点击生成 → POST /generate/reminder → {task_id} → 进度条+轮询 /generate/task/<id> → 完成 toast+下载链接
Excel 输出底色规则（openpyxl PatternFill）：
   「改版工卡」区块数据行 = 蓝色底色（0000FF）
   新工卡（既有④区块）按专业分组、数据行 = 蓝色底色
   作废工卡 = 浅红底（FFC7CE）+ 行首"已作废"标注
```

### 8.6 库存查询页 `templates/inventory/index.html`
```
删除：登录状态卡、新建配置/检查配置卡（全部迁表头）
保留：库存查询卡（原样）
底部：<!-- 库存预警数据预留区 -->（注释占位，本期不渲染任何控件）
```
遵循现有 Bootstrap 5.3 CDN、toast/loader、卡片布局；所有 UI 改动按 agent.md 附 e2e 验证。

## 九、统一提示文案（沿用 P1~P12，新增 S 系列）

| # | 场景 | 文案 |
|---|------|------|
| S1 | 同步进行中 | `同步进行中，请勿重复操作（工卡全量检查约 3~15 分钟）` |
| S2 | 飞机完成 | `飞机同步完成：新增 X，更新 Y，清理 Z（清单见下）` |
| S3 | 工作包导入完成 | `工作包 {REVNR} 已导入：例行 A 项，其他 B 项，其中新工卡 N 项` |
| S4 | 版本检查完成 | `版本检查完成：改版 X 张，作废 Y 张，改版清单已生成` |
| S5 | 提醒单完成 | `提醒单已生成（含版本检查），点击下载` |
| S6 | 前置阻断 | 沿用 P8：`登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试` |

## 十、文件与代码结构变化（函数级）

### 新增
```
src/reqman/services/amro_sync.py        # 三域同步编排（核心，全部新函数）
tests/test_amro_sync.py                 # 三域编排单测（mock AMRO）
tests/integration/test_amro_sync_api.py # 同步路由集成
```

`services/amro_sync.py` 函数签名：
```python
# 飞机域
async def sync_aircraft(store, client, cookies) -> dict
    # 拉 DA_ACREG_LIST → 过滤 MP_ACTYPE==AMRO_AC_FLEET 且 VALID_STATUS=='1'
    # → reg 三段匹配（原样/去B-/补B-）→ upsert 六字段 / 清理删除 → card_logs → meta
# 工作包域
async def list_amro_packages(client, cookies, base=None, days=7) -> list[dict]
def package_items(rows_routine, rows_other) -> dict   # 与 xlsx 解析 item 同构
async def import_amro_package(store, client, cookies, revnr) -> dict
    # 拉 BM_TSK_002_LIST+_QT → package_items → persist_package → {package_id, routine, other}
# 工卡版本域
async def full_version_check(store, client, cookies) -> dict
    # 拉两清单（SMJC 3页+EO ~12页, timeout=150, 无 writer）→ 库内卡比对 → 更新+card_logs
    # → {revised:[{task_code,old_wd,new_wd}], cancelled:[...]}
def build_version_report_excel(report) -> bytes       # openpyxl：改版 sheet + 作废 sheet
async def check_cards_against_amro(store, client, cookies, task_codes) -> dict
    # 提醒单用：实时拉（客户端过滤到 task_codes）→ 比对更新 → {revised, cancelled, new_by_category}
def apply_reminder_version_section(ws, report) -> None
    # 提醒单 Excel 附加区块：改版行/新工卡行蓝色底色(0000FF)，作废行浅红底(FFC7CE)
def _run_in_thread(app, domain, fn)                   # daemon 线程助手，写 amro_sync_meta 状态位
```

### 修改（函数/路由级）
```
services/connectors/amro.py
  + READONLY_PLUGINS: frozenset[str]           # 7 端点
  + class AmroSessionExpired(RuntimeError)
  + _throttle() / _audit()                     # 模块级节流（≥2s）+ JSONL 审计
  + async query_plugin(client, cookies, plugin, form, *, timeout=30) -> dict
  + async fetch_all_pages(client, cookies, plugin, base_form, *, timeout=30, max_pages=30) -> list[dict]

models/json_store.py
  ~ _FIELDS["card"]/_CARD_FIELDS  +write_date: ""
  ~ _RUNTIME_KEYS                 +{"amro_sync_meta"}
  + get_amro_sync_meta() / set_amro_sync_meta(domain, payload)
  + get_version_logs(limit=100)                # card_logs 倒序筛选 changes[].field=="write_date"

blueprints/cards_bp.py
  + POST /card/aircraft/amro-sync              # 前置检查→daemon 线程→started
  + GET  /card/aircraft/amro-status            # amro_sync_meta.aircraft
  + POST /card/amro-version-check              # daemon 线程
  + GET  /card/amro-version-status
  + GET  /card/amro-version-report/<ts>        # xlsx 下载（send_file）
  + _require_amro_session()                    # 前置检查助手：失效→401+P8

blueprints/packages_bp.py
  + GET/POST /packages/amro-list               # BM_TSK_LIST 包装
  + POST /packages/amro-fetch                  # revnr → import_amro_package → package_id
  + GET  /packages/amro-version-logs           # get_version_logs 视图
  ~ 抽取 persist_package(store, data)          # 现 /upload 尾段，upload 与 amro-fetch 共用

blueprints/generate_bp.py
  ~ POST /generate/reminder → 异步化           # 勾选版本检查时后台线程拉 AMRO 比对+更新卡
  + GET  /generate/task/<id>                   # {status: pending|running|done|error}
  + GET  /generate/task/<id>/download
  + _TASKS = {}                                # 进程内 task 注册表

blueprints/inventory_bp.py
  ~ setup-package ZIP +register_protocol.bat   # 桌面路径检测（含 OneDrive 重定向）+注册 ReqManLogin 协议
  （/inventory/session、/inventory/login/upload 不变，供表头复用）

templates：base.html（表头三件套+提示区+JS）、cards/{aircraft,list}.html（header 按钮+modal+报告卡）、
  packages/upload.html（四卡片重排，Card1/Card2 保留不动）、generate/form.html（勾选框+异步交互）、
  inventory/index.html（删登录区块+预警占位注释）

config.py    + AMRO_RATE_SECONDS(2.0) / AMRO_AUDIT_FILE(data/amro_audit.jsonl) /
               AMRO_AC_FLEET("A320") / AMRO_BASE_DEFAULT("KM01")
__init__.py  无新蓝图注册（路由全部进现有 bp）
.gitignore   + data/amro_audit.jsonl
CHANGELOG.md / README.md / pyproject.toml / SERVER_README.md   # 3.5.0
```

## 十一、测试策略

| 测试 | 覆盖 |
|------|------|
| `test_amro_connector.py`（扩展） | query_plugin 白名单拒绝/节流/审计行/code=100 异常/分页拉全（total 恒 0 语义） |
| `test_amro_sync.py` | 飞机映射/upsert/B-前缀/清理判定（在册集合）/清理日志；工作包 item 映射（机身→机体/撤销/ORTP→source）；版本比对（改版判定/作废判定/只动库内卡）；版本日志筛选 |
| `test_amro_sync_api.py`（集成） | 各路由前置检查 401、后台线程启动与状态轮询、Excel 报告生成、提醒单异步任务、/inventory 简化后路由不回归 |
| e2e（agent.md 硬性要求） | 表头状态/一键登录降级链/三页内嵌区块交互/工作包页重排/提醒单异步流程，附截图证据 |

全量 `pytest -m "not slow"` + `pytest -m e2e` + `ruff check src/ tests/`；AMRO 全 mock；隔离 DB 副本。

## 十二、风险与应对

| 风险 | 应对 |
|------|------|
| 实时拉取 3~15 分钟（EO 深分页 38~105s/页） | 提醒单/版本检查全部后台线程+状态轮询；提示 S1 明示等待时长 |
| 飞机清理是破坏性操作 | 确认弹窗列清理数量；card_logs 全量留档；报告附被删清单 |
| 协议注册每机一次性成本/杀软拦截 | 未注册自动降级为下载+指引流程，功能不缺失 |
| 提醒单异步改造动到现有生成流程 | task 状态机最小化（pending/running/done/error）；旧同步路径保留开关一个版本 |
| 撤销判定字段未实测（PPCBZSM 文本 vs 独立标志） | 先按"备注含撤销"（与解析器一致）；首个含撤销项工作包对照 xlsx 校正 |
| 会话 2h/互踢 | 表头状态+前置阻断；失败记录 meta.error 无副作用 |
| AMRO 接口改版 | 端点/参数集中 connectors/amro.py 常量区；审计日志定位漂移 |

## 十三、明确不做

- 工卡改版主动推送提醒（邮件/站内信）：提醒单内输出已覆盖当前工作流
- AMRO 全量工卡/飞机数据落地存储（快照）：两处检查均实时拉
- AMRO 工卡 PDF 批量下载（GK 字段）：导出类动作需另行人工确认
- QM_CK_PACKAGE_* 归档视图、BM_GET_ADD_JC：任务接收流程用不到，需要时按需人工确认
- 库存预警功能：仅预留页面空间，不在本期

## 十四、实施任务

见 `docs/superpowers/plans/2026-08-30-amro-data-sync.md`（Task 1~8，TDD 逐任务，三阶段）。
