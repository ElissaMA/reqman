# 库存查询功能并入设计文档

> 日期：2026-08-15 | 版本目标：3.3.0 | 分支：feature | 状态：定稿 v4

## 一、背景与目标

需求单系统（reqman）的航材/备用航材件号需实时库存判断（库存不足标红、告警标黄），
现靠人工登录川航 AMRO 逐件查询，耗时数小时。本功能将上级目录独立工具"库存查询"
（scal，v1.0 已验证）并入本应用，提供 Web 化的批量库存查询与需求单副本回填能力，
并沉淀通用外部连接器框架，为后续新增数据源功能预留。

## 二、已确认决策

| 决策点 | 结论 |
|--------|------|
| 集成形态 | B1 独立回填：选择需求单 Excel → 副本回填 G 列+标红/标黄，原文件不动 |
| 通用框架 | C2 最小实现 + 预留接口（`connectors/`，AMRO 独立成文件，扩展时再抽象） |
| 登录方式 | 仅登录脚本（ZIP 配置包自举，国内源） |
| 登录凭证 | 一次性、不长期储存；临时缓存 2h（`AMRO_SESSION_TTL` 可配置），用完/超时即删 |
| 账号策略 | 任意账号一次性登录（不绑定、不存储、无账号池） |
| 脚本位置 | `scripts/`（模板，服务器动态生成 ZIP 时注入服务器地址） |
| 前端按钮 | ① 新建配置（下载 ZIP）② 检查配置（U1 上传校验，提醒选正确文件） |
| 交互 | 页面进入即探活；有效期内直接查询免脚本；查询按钮点击时 P1 确认弹窗 |
| 会话表述 | 统一使用"登录"，不出现"Cookie"字样，工具统一称"登录脚本" |
| TLS | 标准证书校验（verify=True） |
| 部署 | 本地 Windows 开发验证 + Ubuntu 无头服务器（Gunicorn 4w×2t）生产 |
| 数据源调研 | GitHub 无匹配成熟项目；复用源 scal 存量代码 + 借鉴 pyscrapify 适配器注册思路 |

## 三、核心流程

### 3.1 用户主流程
```
首次使用：
① 打开 /inventory 页面 → 自动探活 → 显示「❌ 系统未登录AMRO」
② 点「🛠 新建配置」→ 下载 ZIP（amro_login.py + start_login.bat + README）
③ 解压 → 双击 start_login.bat → [P1 确认] → 自举环境（国内源，仅首次）→ 弹浏览器登录 → 自动上传
④ 页面刷新 → 「✅ 登录有效，剩余约 2 小时」

登录有效期内（2h）：
⑤ 直接上传需求单 Excel → 点「开始查询」→ [P1 确认弹窗] → 并发查 AMRO → 副本回填标红/标黄 → 下载副本

登录过期后：
⑥ 页面显示「❌ 查询登录已过期」→ 重新运行登录脚本（③）
```

### 3.2 关键机制
| 机制 | 说明 |
|------|------|
| 页面进入即探活 | 打开 `/inventory` 立即调 `/inventory/session`（真实 API 一次），状态卡实时显示 |
| 有效期内免脚本 | 登录有效时纯网页操作；脚本仅登录缺失/过期时运行 |
| 查询前双保险 | 点「开始查询」→ P1 确认 modal → 后端校验登录 →（有效）查询 /（失效）P8 阻断 |
| 一次性语义 | 凭证不长期持久化、不跨用户复用；临时缓存 2h，超时自动清理 |
| 多端互踢警示 | 脚本启动 P1 确认 + 状态卡 P6 警示"登录有效期内若在其他浏览器登录将挤掉当前登录" |

## 四、架构设计

### 4.1 分层（遵循 工厂+蓝图+服务层）
```
blueprints/inventory_bp.py      路由层（页面/配置包/检查/登录状态/上传/查询）
services/inventory_service.py   业务编排（读Excel→去重→并发→回填）
services/xlsx_workbook.py       Excel 读写（迁移自 scal）
services/connectors/amro.py     AMRO 适配器（verify=True，唯一接触 API）
services/connectors/session.py  临时登录缓存（原子写，TTL 2h 可配，预留用户绑定）
config.py                       AMRO 环境变量
templates/inventory/index.html  查询页
```

### 4.2 通用连接器框架（C2 预留接口）
- `connectors/amro.py` 独立成文件，函数化设计（`query_kunming_stock` 等）
- `connectors/session.py` 通用缓存（不绑定 AMRO），未来新数据源复用
- 预留适配器注册注释约定（借鉴 pyscrapify），扩展时再抽象基类

## 五、接口设计（统一 api_success/api_error）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/inventory` | GET | 查询页 |
| `/inventory/session` | GET | 登录状态（未登录/有效+剩余分钟/过期），含探活 |
| `/inventory/setup-package` | GET | 新建配置：动态生成 ZIP（注入当前服务器地址） |
| `/inventory/check-config` | POST | 检查配置：上传脚本/zip 校验（完整性/地址/版本） |
| `/inventory/login/upload` | POST | 登录凭证上传（登录脚本自动调用） |
| `/inventory/query` | POST | 执行查询（multipart 上传需求单 Excel） |

响应规范：`api_success(data, message)` / `api_error(message, error_code, status_code)`；
业务异常用 `ApiException` 抛出由全局处理器转换。

## 六、数据与安全

| 项 | 设计 |
|----|------|
| 临时凭证缓存 | `data/cookie/amro_cookies.json`（gitignore），**临时**（TTL 2h，超时自动删/覆盖） |
| 原子写 | 复用 `json_store._atomic_write` 模式，防并发写坏 |
| 跨 worker | Gunicorn 4w×2t 下临时文件共享读写 + 进程锁 |
| 数据保护 | 原 Excel 只读，副本输出；真实 `data/reqman_db.json` 零触碰 |
| 安全 | ZIP 动态生成防目录穿越；上传接口来源校验 |

## 七、登录脚本设计（ZIP 配置包 · 自举）

### 7.1 配置包内容（服务器动态生成）
```
├─ amro_login.py        # 模板，注入 SERVER_URL + 上传接口 + MSG 文案集
├─ start_login.bat      # 自举入口
└─ README.txt           # 3 步图文指引
```

### 7.2 自举流程（国内源）
```
双击 start_login.bat
 ├─ [已有配置检测] 检查脚本同级 .runtime/ 目录
 │    ├─ ✅ 完整（uv/Python/venv/chromium 已装）→ 跳过自举，直接登录
 │    └─ ❌ 缺失/不完整 → 自举（仅首次 ~1-2min）：
 │         pip install uv（阿里云 PyPI https://mirrors.aliyun.com/pypi/simple/）
 │         uv python install 3.11 → uv run 建 venv 装依赖
 │         PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright/
 │         playwright install chromium
 ├─ ⚠️ [P1 确认对话框] 关闭已登录 AMRO 页面警示 → 点击 [确认] 继续
 ├─ 弹浏览器 → 人工登录（账号/密码/验证码）→ 检测 JSESSIONID
 ├─ 提取登录凭证 → 自动上传 /inventory/login/upload
 └─ [P3 成功] → 自动关闭
```
- 环境存脚本同级 `.runtime/` 目录，仅首次下载，后续秒开
- 已有配置检测标准：`.runtime/` 存在 + `venv/Scripts/python.exe` 存在 + 版本戳一致；不完整则增量补齐

### 7.3 国内下载源（已实测核实）
| 组件 | 源 |
|------|-----|
| Python 包 | `https://mirrors.aliyun.com/pypi/simple/`（✅ 200） |
| uv 本体 | PyPI 安装（`pip install uv`） |
| Python 解释器 | 阿里云 `python-release/` 镜像（✅ 200） |
| playwright 内核 | `https://registry.npmmirror.com/-/binary/playwright/`（✅ 200，chromium/ffmpeg/driver 全量） |

## 八、前端页面设计（`/inventory`）

```
┌──────────────────────────────────────────────────┐
│ ① 登录状态卡（页面进入自动探活）                    │
│    ✅ 登录有效 剩余 1h 58m ｜ ❌ 系统未登录AMRO      │
│    ⚠️ P6 警示（有效期内挤掉风险）                  │
├──────────────────────────────────────────────────┤
│ ② 配置区                                        │
│    [🛠 新建配置]（下载 ZIP，P10 提示）             │
│    [🔍 检查配置]（上传校验，P11/P12）              │
│    [❓ 使用指引]（3 步图文弹窗）                   │
├──────────────────────────────────────────────────┤
│ ③ 库存查询区                                      │
│    [选择需求单.xlsx]（upload-zone 拖拽/点击）       │
│    [开始查询] → [P1 确认 modal] → 进度条+计数      │
│    结果摘要 + [下载副本] [打开目录]（P9 完成）      │
└──────────────────────────────────────────────────┘
```
遵循现有视觉规范：Bootstrap 5.3 CDN、全局 toast/loader、hover、卡片布局、空状态。

## 九、统一提示文案集（P1–P12 定稿）

| # | 场景 | 文案 | 位置 |
|---|------|------|------|
| P1 | 使用前关闭已登录 AMRO 警示 | `⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。` **[确认]** | 登录脚本启动对话框 + 网页查询按钮 modal |
| P2 | 脚本登录中 | `已打开登录页面，请在浏览器中完成川航 AMRO 登录（账号/密码/验证码），登录后请保持页面不动。` | 登录脚本 |
| P3 | 登录成功 | `✅ 登录成功，本页面即将就绪。` | 登录脚本 |
| P4 | 未登录 | `❌ 系统未登录AMRO：请先点击「检查配置」选择脚本位置，或「新建配置」下载登录脚本，解压后双击运行完成登录` | 网页状态卡 |
| P5 | 登录有效 | `✅ 登录有效，剩余约 X 分钟` | 网页状态卡 |
| P6 | 挤掉警示 | `⚠️ 登录有效期内若在其他浏览器/设备登录川航 AMRO，当前登录将被挤掉失效，需重新运行登录脚本` | 网页状态卡 |
| P7 | 登录过期 | `❌ 查询登录已过期：请重新运行登录脚本` | 网页状态卡 |
| P8 | 查询前阻断 | `登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试` | 网页查询失败 |
| P9 | 查询完成 | `查询完成。` | 网页结果 |
| P10 | 新建配置 | `下载配置包（ZIP）后请解压，双击其中 start_login.bat 完成登录` | 网页按钮 |
| P11 | 检查失败 | `未检测到有效配置：请选择正确的 amro_login.py 或配置包（ZIP）文件；若配置缺失或版本过旧，请点击「新建配置」重新下载` | 网页提示 |
| P12 | 检查成功 | `✅ 配置正常：版本与当前系统匹配，可运行登录脚本完成登录` | 网页提示 |

**统一管理**：后端 `MESSAGES` 常量 / 前端 `const MSG` / 脚本 `MSG = {}`，三端集中定义，禁止散落硬编码。

## 十、文件清单

### 新增（应用内）
```
src/reqman/services/connectors/__init__.py
src/reqman/services/connectors/amro.py
src/reqman/services/connectors/session.py
src/reqman/services/inventory_service.py
src/reqman/services/xlsx_workbook.py
src/reqman/blueprints/inventory_bp.py
src/reqman/templates/inventory/index.html
```

### 新增（脚本）
```
scripts/amro_login.py
scripts/start_login.bat
scripts/requirements-login.txt
```

### 新增（测试）
```
tests/test_amro_connector.py
tests/test_inventory_service.py
tests/integration/test_inventory_api.py
```

### 修改
```
src/reqman/app.py          注册 inventory_bp
src/reqman/config.py       +AMRO_API_URL/COOKIE_FILE/MAX_CONCURRENT/SESSION_TTL(默认2h)
pyproject.toml             +httpx（服务依赖）；playwright 归入脚本依赖
.gitignore                 +data/cookie/
src/reqman/templates/base.html  导航 +库存查询
CHANGELOG.md / README.md   版本 3.3.0
```

## 十一、测试策略

| 测试文件 | 覆盖 |
|----------|------|
| `test_amro_connector.py` | mock httpx：code=200/100/异常、昆明/非昆明 SWERK、件号去重 |
| `test_inventory_service.py` | fixture xlsx：区域识别、去重、回填、标红/标黄、查无库存填 0 |
| `test_inventory_api.py` | 集成：session 探活、setup-package 生成、check-config 校验、login 上传、query（mock AMRO） |

全量：`pytest -m "not slow"` + `ruff check src/ tests/`；AMRO 全 mock，CI 可跑；隔离 DB 副本，真实数据零污染。

## 十二、风险与应对

| 风险 | 应对 |
|------|------|
| 外部直连 WAF/限流 | 并发默认 10（`AMRO_MAX_CONCURRENT` 可配），失败重试 |
| 登录 2h 过期 | 状态卡实时显示 + 页面进入探活 + 过期 P7 提示重登 |
| 多端互踢 | 脚本启动 P1 确认 + 状态卡 P6 警示 + 查询前探活 P8 阻断 |
| 多 worker 并发 | 临时文件原子写 + 进程锁 |
| ZIP 注入地址 | 按请求主机动态生成；防目录穿越 |

## 十三、实施任务（feature 分支，3.3.0）

| # | 任务 | 负责人 | 验收 |
|---|------|--------|------|
| 301 | 后端服务层（connectors+inventory_service+xlsx_workbook） | 后端工程师 | 单测绿、ruff 过 |
| 302 | 后端蓝图+配置+注册（session/setup-package/check-config/login-upload/query） | 后端工程师 | 路由可访问，mock 测试绿 |
| 303 | 登录脚本+自举+ZIP 生成（含 P1/P2/P3 文案与已有配置检测） | 后端工程师 | 本地双击可登录上传 |
| 304 | 前端查询页（状态/配置/查询三区块 + P1/P4–P12 文案） | 前端工程师 | 交互完整，视觉统一 |
| 305 | 测试验证 | 测试工程师 | 全量 pytest+ruff 绿，DB 零污染 |

**派发顺序**：301→302→303（后端串行）→304（依赖 302 路由）→305（依赖全部产物）。
每步完成后测试工程师独立验证，总工抽查审核、汇总汇报。
