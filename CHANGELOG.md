# Changelog

## [3.3.0] - Unreleased
### Added
- 库存查询功能：上传需求单 Excel 批量查询川航 AMRO 昆明库存，副本回填 G 列并标红/标黄
- 通用连接器框架（services/connectors/）：AMRO 适配器 + 登录凭证临时缓存（TTL 2h 可配）
- 登录脚本（scripts/）：uv 自举 + 国内高速源（阿里云 PyPI / npmmirror playwright），自动上传登录凭证
- 库存查询页（/inventory）：新建配置 / 检查配置 / 登录状态探活 / 查询进度与结果
- 统一提示文案集（P1–P12）

### Fixed
- 登录脚本首次安装改用 uv pip 装包（uv venv 无 pip，原 python -m pip install 失败），内核装沿用 python -m playwright
- 登录脚本窗口控制：服务器模式自举最小化（防误关），本地模式保留窗口并提示登录未完成原因；登录成功追加"请回到网页开始查询"提示
- 库存查询不落盘：上传文件走临时目录、副本内存生成（BytesIO）直接浏览器下载，服务器 output/ 目录无残留文件；统计信息经 X-Query-Stats 响应头返回
- 查询响应头中文编码：X-Query-Stats 改默认 ensure_ascii 转义（HTTP 头仅允许 ASCII，原中文直接入头导致 UnicodeEncodeError、前端卡加载中）；前端查询增加 65s 超时兜底（AbortController + 自动结束加载中）
- 登录状态真实探活：状态卡不再仅读缓存，实时调用 AMRO API 判定登录有效性（缓存+探活失败→提示重新登录），轮询间隔调整为 10 分钟
- 输出文件保留原名（{原文件名}_库存已填_时间戳.xlsx），查询完成改手动下载按钮（暂存 output/ 不怕误关网页，上传新需求单自动清除旧暂存，仅匹配 *_库存已填_*.xlsx 不误删其他文件）
- 补充 README/SERVER_README 库存查询与登录运维文档；「新建配置」ZIP 下载前增加安全确认弹窗
- 登录脚本修复：跳过系统代理直连（trust_env=False，修复系统代理拦截导致上传凭证失败）+ 上传地址可配置（AMRO_PUBLIC_URL，未配置回退当前访问地址）+ 上传失败友好提示（不裸抛 traceback）
- deploy.sh .env 模板补充 AMRO_PUBLIC_URL 配置项（供下次全新部署生成）

### Changed
- 开发过程资产（docs/superpowers/ 设计文档与实现计划）移出 git 追踪（仅本地保留，不上传生产）
- 后续方向更新：定检提醒单、工卡版本数据、飞机数据、更多数据查询
- 服务器更新流程补充依赖安装步骤（venv/bin/pip install -e .），修复更新后因缺依赖导致 502 的根因
- deploy.sh .env 模板补充 AMRO 可配置项注释；README 技术栈补充 httpx
- 登录成功后查询页自动刷新登录状态（focus/visibilitychange 统一探活）
- 登录脚本成功提示弹窗（本地/服务器模式均可见）

## [3.2.5] - Unreleased
### Changed
- agent.md 精简重构为九章工作区规范（工作区/分支/协作/提交/任务/沟通/测试/版本/数据保护）
- 新增库存查询功能设计文档（B方案独立回填，定稿v4）

### Fixed
- 修复 start.bat 启动乱码（UTF-8 BOM + CRLF + chcp 65001），消除"需求单管理系统不是内部或外部命令"报错
- 新增 .gitattributes 规范行结束符（*.bat=crlf / *.sh、*.py 等=lf），防止 core.autocrlf 污染

## [3.2.4] - Unreleased
### Fixed
- 空值校验统一：全角空格/零宽字符/BOM 等不可见字符视为空值（validators.py 新增 is_blank/clean_text）
- 必填校验统一走 validate_required（删除 cards_bp._validate_required），工卡新增/编辑补专业必填
- 工具/航材行名称必填，件号/数量/备注可选（删除"仅填写名称"误拦截）
- 使用类型为空时兜底"必须使用"
- 新增工具/航材行数量默认值取消（默认空白），空数量存空且 Excel 数量列输出空
- 工卡组已选工卡恒渲染（loadAllCards 重构），≥2 工卡判断基于完整已选工卡
- 移除 form_generator category 分组兜底，严格要求数据含 category

### Changed
- 依赖源统一：pyproject.toml 为唯一依赖源，删除 requirements.txt / requirements-dev.txt（dev 依赖并入 [dev] extra，补充 pytest-playwright>=0.5.0）
- deploy.sh 改用 `pip install -e .` 安装

## [3.2.3] - 2026-08-12
### Fixed
- toast 全局不可见（Bootstrap .toast:not(.show) display:none 覆盖自定义样式）
- flash 提示时序 Bug（renderFlashes + DOMContentLoaded）
- 保存成功无反馈（toast + 延时关闭弹窗）
- 0工具/航材幽灵输入行
- 半空行静默丢弃（严格校验抛错）
- category 原生 required 拦截校验提示
### Added
- pytest-playwright 有头浏览器 E2E 测试（tests/e2e/）
- Flask 全局 no-cache 响应头
- safeToast 兜底（alert 降级）
- app.py debug 跟随 FLASK_ENV 配置
### Changed
- 测试流程与版本规则写入 agent.md（第13/14条）
- 新增 requirements-dev.txt

## [3.2.2] - 2026-08-11
### Changed
- 模板变量命名统一（card/set/ac/log）
- 修复 form.html 编辑URL bug（cardId 引用未定义变量，编辑提交错误指向 /card/new）
### Added
- /api/spec JSON 接口保留，/api/docs 移除（原500）
### Fixed
- sets.html 重复 div 结构
- generate_bp 死变量清理

## [3.2.0] - 2026-07-30

### Added
- UI交互增强：拖拽上传、滚动加载、toast提示、全局loader、hover效果
- 工卡保存后postMessage通知父页面标绿
- pre-commit钩子（ruff + ruff-format）+ CONTRIBUTING.md代码规范
- 定检工卡数据更新（组套#954/#977分配、新增工卡#972/#973、物资录入）

### Changed
- 149个ruff错误全部修复
- 数据库拆分为核心文件+运行时文件
- 启动文件自动检测虚拟环境

### Fixed
- 虚拟环境未激活时Flask导入失败

## [3.2.1] - 2026-08-01

### Added
- 航材备注快捷输入"优先使用开封航化"按钮
- 新增tzdata依赖支持北京时间时区

### Changed
- 所有时间显示统一为北京时间（Asia/Shanghai）
- 数据库更新：启动机胶圈数量2→4

### Fixed
- 工作包生成时间非北京时间问题
- 操作日志时间戳非北京时间问题

## [3.1.0] - 2026-07-21

### Added
- 需求单预览页面和输出 Excel 中工卡名称列显示工卡组名称
- 新增工卡时自动填充专业（category）和类型（task_type）

### Changed
- Excel 输出中"工作名称"列优先显示工卡组名称，无组时显示工卡名称

### Fixed
- 输出文件中工卡组名称未正确显示的问题

### Refactored
- 移除 models/entities.py 和 models/repository.py，整合入 json_store.py

## [3.0.0] - 2026-07-16

### Changed
- 项目重构为标准 Python src 布局
- 去除 Request_list_ 冗余前缀
- 配置外置为环境变量 + python-dotenv
- 修复蓝图跨模块导入
- 新增 GitHub CI 自动化流程
- 数据库纳入 Git 版本管理
