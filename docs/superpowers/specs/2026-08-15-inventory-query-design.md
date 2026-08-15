# 库存查询功能并入设计文档

> 日期：2026-08-15 | 版本目标：3.3.0 | 分支：feature

## 一、背景与目标

需求单系统（reqman）的航材/备用航材件号需实时库存判断（库存不足标红、告警标黄），
现靠人工登录川航 AMRO 逐件查询，耗时数小时。本功能将上级目录独立工具"库存查询"
（scal，v1.0 已验证）并入本应用，提供 Web 化的批量库存查询与需求单副本回填能力，
并沉淀通用外部连接器框架，为后续新增数据源功能预留。

## 二、已确认决策

| 决策点 | 结论 |
|--------|------|
| 集成形态 | B1 独立回填：查询页选择需求单 Excel → 副本回填 G 列+标红/标黄，原文件不动 |
| 通用框架 | C2 最小实现 + 预留接口：`connectors/` 目录，AMRO 独立成文件，后续扩展时再抽象 |
| Cookie 存储 | D1 独立文件 `data/cookie/amro_cookies.json`（gitignore），原子写入 |
| 登录形态 | F2 仅 Cookie 导入：本地与服务器一致，无 playwright 依赖 |
| 账号策略 | G1 全局单账号，存储层预留用户绑定扩展 |
| TLS | 标准证书校验（`verify=True`） |
| 部署 | 本地 Windows 开发验证 + Ubuntu 无头服务器（Gunicorn 4w×2t）生产 |
| 数据源调研 | GitHub 无匹配成熟项目；复用源 scal 存量代码 + 借鉴 pyscrapify 适配器注册思路 |

## 三、架构设计

### 3.1 新增目录结构

```
src/reqman/
├── services/
│   ├── connectors/            # 通用外部连接器（预留扩展）
│   │   ├── __init__.py
│   │   ├── amro.py            # AMRO 库存查询适配器（首个实现）
│   │   └── session.py         # Cookie 会话存储（原子写，预留用户绑定）
│   ├── inventory_service.py   # 业务编排：读Excel→去重→并发查询→副本回填
│   └── xlsx_workbook.py       # 需求单 Excel 读写（迁移自 scal）
├── blueprints/
│   └── inventory_bp.py        # 独立查询页蓝图
└── templates/
    └── inventory/
        └── index.html         # 查询页
```

### 3.2 核心流程

```
查询页选择需求单.xlsx
  → 读航材区（定检专业（航材））+ 备用区（备用航材需求）件号
  → 件号标准化去重
  → 检查会话（Cookie 8h TTL + API 探活）
  → httpx 并发查询 AMRO（昆明=SWERK前缀KM 的 CLABS 求和）
  → 生成副本 {原文件}_库存已填_{时间戳}.xlsx
  → G 列回填库存；库存<需求 标红 / 需求≤库存<需求+2 标黄
```

### 3.3 会话管理

- Cookie 存 `data/cookie/amro_cookies.json`（gitignore），复用源 `cookie_manager` 逻辑 + 原子写
- 导入入口：查询页粘贴 Cookie JSON 或上传源 scal 的 `amro_cookies.json` 文件
- TTL 8h；查询前 `check_session` 探活（调一次 API 判断 code=100 会话过期）
- 存储结构预留 `user` 字段，为后续用户体系绑定 Cookie 留位

## 四、接口设计（遵循统一 API 响应格式）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/inventory` | GET | 查询页 |
| `/inventory/cookie` | GET | 会话状态（未登录/有效/过期） |
| `/inventory/cookie` | POST | 导入 Cookie（JSON 或文件上传） |
| `/inventory/query` | POST | 执行查询（multipart 上传需求单 Excel） |

统一响应：`api_success` / `api_error`（success/data/message + success/message/error_code）。

## 五、文件改动清单

### 新增
- `src/reqman/services/connectors/__init__.py`
- `src/reqman/services/connectors/amro.py`
- `src/reqman/services/connectors/session.py`
- `src/reqman/services/inventory_service.py`
- `src/reqman/services/xlsx_workbook.py`
- `src/reqman/blueprints/inventory_bp.py`
- `src/reqman/templates/inventory/index.html`
- `tests/test_amro_connector.py`
- `tests/test_inventory_service.py`
- `tests/integration/test_inventory_api.py`

### 修改
- `src/reqman/app.py`：注册 `inventory_bp`
- `src/reqman/config.py`：新增 AMRO_API_URL / AMRO_COOKIE_FILE / AMRO_MAX_CONCURRENT
- `pyproject.toml`：+httpx 依赖
- `.gitignore`：+data/cookie/
- `src/reqman/templates/base.html`：导航 +库存查询
- `CHANGELOG.md` / `README.md`：同步更新，版本 3.3.0

## 六、测试策略

- 单测 `test_amro_connector.py`：mock httpx 响应（code=200/100/异常、昆明/非昆明 SWERK、件号去重）
- 单测 `test_inventory_service.py`：读 Excel（fixture 临时 xlsx）、去重、回填、标红/标黄判定、查无库存填 0
- 集成 `test_inventory_api.py`：会话状态接口、Cookie 导入、查询接口（mock AMRO）
- 遵循隔离 DB 副本原则，真实 `data/reqman_db.json` 不被污染；AMRO 外部 API 全部 mock

## 七、风险与应对

| 风险 | 应对 |
|------|------|
| 外部直连被 WAF/限流 | 并发默认 10 可配置（AMRO_MAX_CONCURRENT）；失败重试策略 |
| Cookie 失效 | 查询前探活；失效提示重新导入 |
| 服务器多 worker 并发 | Cookie 原子写入；查询任务互斥锁 |
| API 字段变更 | 集中封装在 `amro.py`，改动限单文件 |

## 八、验收标准

1. `/inventory` 页面可访问，遵循现有视觉规范（toast/loader/hover）
2. Cookie 导入 + 会话状态接口正常（mock 环境）
3. 上传需求单 → 并发查询 → 副本回填 G 列 + 标红/标黄逻辑正确（mock 测试覆盖）
4. 全量测试通过：`pytest -m "not slow"` + `ruff check src/ tests/`
5. 真实 DB 未被污染
