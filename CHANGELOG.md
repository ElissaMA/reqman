# Changelog

## [3.4.0] - Unreleased
### Added
- 工卡提醒并入：工卡/工卡组新增提醒字段（card_ok / reminder_confirmed / reminder_type），保存校验统一 + card_ok 自动置位 + 确认重置接口
- 提醒单下载：基于 reminder_template.xlsx 生成例行（黑字）/其他（红字）/重点（黄底）提醒单，无未识别表
- 工卡列表筛选：按提醒状态/重点过滤，未确认与重点提醒红框高亮，无需提醒列留白
- VBA 配置迁移脚本（scripts/import_vba_config.py）：不导无需提醒、弃用清单、重点覆盖一般、飞机防重复，初始 card_ok=False
- 确认字段统一：no_reminder 重命名为 reminder_confirmed；工具/航材/提醒三块对称确认（有数据自动确认/无数据须勾选），任一未确认进新工卡区；提醒单补定检级别/FSN/MSN/APU（按机号查库）；UI 布局统一（总确认置表头、分项确认置区块下、备注置底部）
- 预览新工卡区仅显示总体"未确认"badge（card_ok=False），不重复显示分项确认；提醒区块确认无需提醒后红框联动置灰锁定（section-disabled）；确认勾选框移出红框外，可随时取消

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
- 移除登录脚本成功弹窗（模态阻塞导致浏览器/窗口不自动关闭），恢复登录成功后浏览器自动关闭、脚本窗口自动隐藏
- deploy.sh .env 模板补充 AMRO_PUBLIC_URL 配置项（供下次全新部署生成）
- 查询页弹窗改常驻提示（P1 警示条 + 配置包下载提示），开始查询/下载配置不再弹确认
- 文档同步：README 库存查询使用流程对齐最新交互；deploy.sh 配置项 GENERATED_DIR 更正为 OUTPUT_DIR（与 config.py 一致）
- 登录启动窗口前台化：移除服务器模式 start /min 静默化（安装/运行全部前台，防中途误关闪退）；安装环境每步 if errorlevel 兜底跳 :fail 统一提示；所有窗口结尾无条件停留（[已完成登录] 本窗口可安全关闭 + pause），脚本补 UTF-8 BOM 消除中文误读
- 登录脚本安装兼容性：cd 路径加引号防空格；UV_PYTHON_INSTALL_MIRROR 改 python-build-standalone 镜像（原 aliyun python-release 实测 404）；bat 统一豁免代理（NO_PROXY=* + 清空 HTTP/HTTPS/ALL_PROXY）；.runtime\.installed 标记防 venv 半成品跳过；登录失败区分 [登录未完成]（修复无条件显示已完成登录回归）+ 未检测到 Python 独立提示
- 登录脚本自举优化：uv 改用 astral 官方脚本安装（免 Python 依赖，兼容无真 Python 仅 Store 存根的机器）；删除 .installed 标记改为 venv 实跑校验（python --version 失败即删 .runtime 重建，修复拷贝 .runtime 后 trampoline 失效）；Python 探测改实跑替代 where 防 Store 存根误判；提示明确区分未检测到可用 Python 与网络/安装失败
- 登录脚本免 Python 自举修复：移除 install 块多余 Python 检测与 :nopython 分支（astral 脚本已免 Python，office 电脑无 Python 也能装）；uv 安装失败改用 uv.agentsmirror.com 备用源（npmmirror 实测无 uv 二进制），下载 zip 解压至 %USERPROFILE%\.local\bin\uv.exe 并 uv --version 验证，失败统一 goto :fail
- 登录脚本 uv 下载主备对调：首选国内镜像 uv.agentsmirror.com（实测 1.7MB/s 最快最稳，官方 GitHub 源仅 23KB/s 卡慢速），失败才兜底官方 astral.sh 安装脚本
- 登录脚本裸机自适配：uv 下载解压到临时目录后递归定位实际 uv.exe 再拷入 .local\bin（根治 zip 内 uv-x86_64-pc-windows-msvc/ 子目录结构导致的路径不存在 bug），备用源由 astral.sh 安装脚本改为 GitHub 官方 zip（同样递归定位）；补 "%UV%" python install 3.11（裸机无 Python 也能建 venv）；venv --seed 失败回退最小 venv；依赖安装镜像 2 级 aliyun → tuna；playwright import 校验失败 --force-reinstall 兜底
- 登录脚本浏览器三级回退：Chrome → msedge → 显式 Edge 路径（%ProgramFiles% 与 x86 变体探测），三级全失败打印中文提示退出
- 登录配置包改用系统浏览器：chromium.launch 改用 channel="chrome" 失败回退 channel="msedge"（Win10/11 必装，办公电脑无需下载 120MB chromium）；弃用 playwright install chromium（set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1）；两浏览器皆缺提示安装后重试

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
