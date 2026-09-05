# Changelog

## [3.6.1] - Unreleased
### UI（全站重设计）
- 全站统一为“航空运控”视觉系统：深海军蓝窄侧栏 + 主工作区、雾灰画布、统一状态色/间距/表格密度/焦点样式，新增 `static/css/reqman.css` 设计令牌
- 重做公共页面壳：统一页面标题、上下文栏、AMRO 状态区、移动端导航抽屉、Toast/Loader/确认弹窗和无障碍语义
- 新增 `static/js/reqman.js` 公共交互层：统一筛选、清空筛选、列表删除、上传文件反馈、查询进度、轮询、表单提交和 AMRO 状态探活
- 重排工作包、工卡、工卡组、飞机、作废工卡、库存、日志、需求单预览及各类表单页面；统一列表工具栏、空状态、状态反馈和表单分段
- 修复静态资源 WSGI 透传：`RequestLogMiddleware` 不再吞掉 `FileWrapper` 内容，Bootstrap 与应用 CSS/JS 返回完整响应体，避免页面退化为无样式 HTML

### Reliability（方案 A：非 SQLite 数据可靠性加固）
- 作废工卡库修复共享可变默认值与嵌套对象别名；增加 `.bak` 恢复、损坏拒写、原子备份和独立损坏异常
- JsonStore 增加 JSON 结构校验、`generation` 代际标记、唯一临时文件、读写锁和 fail-closed 恢复；损坏或双文件代际不一致时不再自动清空健康数据
- 库存查询遇到 AMRO 会话中途失效时终止整批，不发布部分库存文件、不写回预警缓存
- 新增作废库、JsonStore、库存会话失效故障测试；真实 `data/` 与 Cookie 数据未被测试修改

### Fixed（正确性）
- 工卡列表异常分支渲染漏传 `categories`/`task_types` 导致错误页自身再抛 500、友好提示丢失：抽 `_render_card_list` helper，成功/失败共用同一 kwargs
- 工卡详情/列表 JSON、工卡组详情、飞机详情接口直接 `jsonify` 缺 `success` 字段，前端 `Poller/apiSubmit` 按 `d.success` 分支被当失败：统一改 `api_success(data=...)` / `api_error(...)` 契约，并同步前端两处消费方读取 `d.data`
- 专业排序 `CATEGORY_ORDER` 三处定义漂移（`config.py` 为权威，`generate_bp.py`/`form_generator.py` 内联副本）：统一 `from config import CATEGORY_ORDER`，删两处内联

### Changed（性能 / 数据层）
- 版本检查逐卡 `store.update(write_date=...)` 每卡全文件重读+重写+备份，热路径 O(N²) IO：新增 `CardStore.bulk_update(updates)`（单次读+写，字段白名单 + code_index 维护 + 变更日志），整轮检查内存攒改后单次 `_write()`
- `generate` 后处理循环内逐条 `find_by_code` 回归 N+1：循环前一次性 `find_by_codes([...])` 建索引
- `sync_aircraft` 逐架 add/update/delete 各一次全量读写：内存算 diff，单次 `_write()`
- `_assign_cards_to_set` 遍历全卡逐张 `store.update(set_id=...)`：一次读 + 批量改隶属 + 单次写

### Security（安全）
- 复核确认上传大小上限 16MB 已生效（`MAX_CONTENT_LENGTH` 已配置并应用），部署文档补 `Nginx client_max_body_size` 须 ≥16MB 的硬性约束
- AMRO Cookie 明文文件（`data/cookie/amro_cookies.json`）保持「用户私有目录 + 绝不入代码包/上传/打印」纪律（沿用只读红线，不做 DPAPI 加密，YAGNI）
- 部署文档硬性约束生产 `FLASK_DEBUG=false` / `use_evalex=false`：防 Werkzeug 交互式调试器 RCE 与完整堆栈外泄

### Refactor（清理）
- 删死代码：`raise_or_flash`、`ConflictError`、`ServerError`、`validators` 未用函数（`validate_required_fields`/`validate_str_length`/`validate_int`/`validate_choice`/`validate_tools_mats`）、`get_logs_by_ids`
- 登录配置包脚本生成由静默 `source.replace(...)` 改为 `_replace_once` 断言占位符恰好命中一次，缺失或重复立即抛错，不再静默产出仍指向硬编码 `localhost` 的配置包

## [3.6.0] - Unreleased
### Added（UI 大改：侧栏布局 + 查询体验统一 + 版本域重构）
- 左侧垂直侧边栏导航：品牌区 + 数据管理组（飞机/工卡/工卡组）+ 顶级（工作包/库存查询/操作日志），当前页蓝条高亮；小屏（<992px）自动变顶部横排；主区顶部右侧白底 sticky 登录框（AMRO 状态徽章 + ⚡一键登录 + 🛠新建配置）
- 数据管理折叠组：飞机信息/工卡信息/工卡组信息折叠进「数据管理」点击展开（当前页默认展开，小屏横排形态）；「数据管理」与 工作包/库存查询/操作日志 同级统一样式（side-link 同款，子页内自身高亮）
- 工卡信息页「编写日期」：清单新增 编写日期 列（YYYY-MM-DD，空显—）+ 详情弹窗行；新建/编辑页基本信息新增 date 输入（留空待 AMRO 同步）；操作日志该字段显示「编写日期」中文标签
- AMRO 工作包查询结果跨页面/刷新保留（内存快照，重启清空），带「查询结果（时间）：获取到 N 个任务包」摘要（学习飞机信息页），导入按钮可直接复用
- 登录状态提示条内联进顶栏左侧（P4 未登录/P7 已过期/P6 提醒与登录按钮同一行，始终位于网页最上方 sticky 区域，小屏自然折行）
- 一键登录协议自定位：register_protocol.bat 用 `%~dp0` 指向自身目录（ZIP 解压任意位置有效），注册完成后立即启动登录（双击一次=注册+登录）
- QueryCard 公共进度助手：四页查询按钮统一接入（running 条纹进度条+已用时 / done 绿色简要 / fail 红色原因）
- 工作包行级「🔍 查询工作包工卡版本」按钮：同步比对包内工卡，生成逐包改版清单 `amro_pkg_version_report_<id>.xlsx`（同包覆盖；例行卡包秒级，含 EO 卡包数分钟）
- 预览页「📥 生成工卡改版下载」按钮：`GET /generate/package-version-report?package_id=`，未查询时 404 提示先在工作包页执行
- 作废工卡库（独立 JSON `data/cancelled_cards.json`，与主库分离降低读写体积）：全量/逐包工卡版本检查检测到 AMRO 清单查无的库内工卡时，自动整卡移入作废库并从主库删除（承接工具/航材/提醒等全部原字段 + 作废日期/来源/原工卡组快照，同号 upsert 幂等）——作废卡自动退出工卡清单/工卡组/匹配/版本检查，不参与任何补查；数据管理新增「🗂 作废工卡」子页（仿工卡列表页：筛选 + 行点击详情弹窗含作废信息，仅查看+彻底删除，无恢复）
- 数据管理四子页（飞机信息/工卡信息/工卡组信息/作废工卡）清单统一新增「新建/编辑日期」日志时间列（数据库条目新建与编辑时间，区别于工卡编写日期），置于操作列紧前并默认按该时间倒序；四页日期列均可点击表头排序、且带「全部时间/近一个月/近3个月/近一年」区间筛选（作废工卡为作废日期）；飞机信息补全 FSN/MSN 列搜索、四页补全「所属工卡组」列搜索、飞机信息操作列去除搜索
### Changed
- AMRO 登录改造（脚本 v3→v4）：浏览器完成登录后**自动**读取账号、只读探活、抓取并上传 Cookie，删除窗口回车与右下角「完成登录」按钮（原 `_INIT_JS` 未自调用致按钮从未出现）；失败分支改为非零退出码，`start_login.bat`/`register_protocol.bat` 成功自动结束、失败传播退出码，不再误报「已完成登录」；动态配置包改为直接复用仓库静态脚本，消除两套实现漂移
- 登录凭证由「2 小时 TTL」改为**长期有效**：`LoginSessionStore` 不再按 `expires_at` 截断，实际可用性由 AMRO 只读探活三态决定（valid/expired/probe_error）——明确失效清缓存、网络异常保留缓存不误报未登录；新增保存 `account`/`login_at`，`/inventory/session` 返回账号与登录时长，顶部状态栏显示「登录账号：XXXX已登录 · 登录时长：X天X小时X分钟」并新增回焦/可见性探活；上传接口要求携带账号并校验 `JSESSIONID`；顶部「新建配置」改「下载登录配置包」，移除过时「检查配置」引导文案
- 数据管理四子页 UI 一致性统一：① 修复飞机信息详情函数游离于 `<script>` 标签外（点行报 showAcDetail is not defined）；② 空状态行补 `empty-state-row` class（对齐公共筛选/排序跳过逻辑）；③ 四页日期列统一 120px 宽度 + 表头与数据居中，作废日期列表截断为 YYYY-MM-DD（详情弹窗保留完整时间）；④ 操作列统一 `text-nowrap` 防按钮换行；⑤ 四页详情弹窗数据字段统一 HTML 转义（公共 `escapeHtml`，防特殊字符破坏 DOM），空值占位统一「—」
- 查询按钮统一命名：查询飞机数据 / 全量查询工卡版本 / 查询工作包 / 查询库存
- 工作包导入语义对齐 Excel：导入仅入库不匹配（is_matched=False、生成日期留空），匹配与生成日期在「重新匹配」或打开预览页时写入
- 查询工作包结果表列：机号|描述|机型|发动机|已分配分队|计划开工|计划总工时（去包号/级别/计划完成）；已导入工作包表列统一：机号|描述|机型|发动机|已分配分队|开工日期|工卡数|生成日期|操作（Excel 导入缺失字段留空，以 AMRO 导入字段为主）
- 已导入工作包表标题由「工作包」改「已导入工作包」；「🔄 重新匹配」+「🔍 查询工作包工卡版本」同行 flex 统一尺寸（列宽 270px）
- 已分配分队取 ZRFD 主分队（剥"(主)"后缀，无标记取首项），计划总工时取 LIMH（语义待真实冒烟校准）
- 版本比对按日期部分（YYYY-MM-DD）：界面 date 只存日期，AMRO 同日不同时间的版本改动不再误报
- 工卡版本查询提速：SMJC/EOJC 两清单均加 `fleet=A320`（AMRO_CARD_FLEET，env 可覆盖，SMJC 1319→745、EOJC 5599→4647）；逐包检查定检例行卡（CSCA 前缀）走 SMJC 全量拉（秒级）、其余（EO/NRC/LS）改用 `TD_JC_ALL_GET_ENTITY_BY_JCNO` 按卡号直查（~50 张 ≈ 2 分钟），不再全量拉 EOJC 深分页（此前约 8 分钟）；新增按卡号直查端点入只读白名单（8 端点）
- 各处查询结果统一库存查询模式：每次查询结果简述持久化至 `output/last_query_<key>.json`（文件持久，重启保留），状态栏显示「上次查询（时间）：简述」；全量/逐包工卡版本检查附「⬇下载改版清单」链接
- 统一各处查询进度条/计时/提示：逐包「查询工作包工卡版本」补上 QueryCard 进度卡（条纹进度条+已用时，此前只有按钮 disable + 文字）；查询工作包列表补成功 toast；五处查询（飞机/全量版本/库存/工作包列表/逐包版本）均使用 QueryCard+计时+toast
- 全局查询互斥：一次只允许一个 AMRO 查询（飞机同步/全量版本/工作包拉取/逐包版本/库存查询），不排队，冲突 409「已有查询任务进行中：{查询名}（{开始时间}）」
- 同步状态迁内存：QUERY_STATUS 注册表取代 `amro_sync_meta` 持久键（重启即清空），全量版本检查后台线程与状态接口统一走 QUERY_STATUS
- 版本报告以提醒单模板输出《工卡改版清单》（全量/逐包同款）：删除模板行 2-5（飞机/工作包信息块+图例行）后按专业分列（电子/发动机/机体，特检/支援/其他不输出），同列先改版后作废——每个条目单单元格三行（自动换行、无底色）：改版 = 工卡号/工卡名称/旧→新，作废 = 工卡号/工卡名称/作废；标题与下载文件名统一「工卡改版清单（标识）查询日期XXXX.XX.XX」（全量标识=全量，逐包标识=机号+描述+开工日期），下载名与预览页同路由同文件
- 逐包「查询工作包工卡版本」持久栏摘要显示机号+描述（如「包 B-3207 C检：改版 X 张，作废 Y 张」），不再显示 package_id 编号串
- 工卡版本查询（全量/逐包）跳过 DP 开头工卡：DP 项目不在 AMRO 清单体系内，不查询、不误报作废
- 工卡版本检查摘要文案统一「改版X张，作废Y张，共检查Z张」：全量 Z=参与比对非 DP 卡数；逐包 Z=工作包内去重卡号数（保留「预览页可下载改版清单」提示，去掉「AMRO 在册 N 张」）
- AMRO 请求限速 2s→1s（AMRO_RATE_SECONDS 默认值，env 可覆盖）；`query_plugin` 瞬态失败自动重试（超时/传输错误/5xx，共 2 次尝试，每次均限速；业务码 100 会话失效与 4xx 不重试），最终失败写 `code=-1` 审计留痕（此前超时零痕迹无法排查）
- 数据管理侧栏新增「作废工卡」子项；工卡信息页操作列对齐与工卡组页统一（居中）
- 库存查询页 UI 重排：库存预警数据库面板移至查询功能栏下方（预留后续清单扩展）
- 工卡版本变动日志增加「工卡名称」列（位于工卡号后，取日志 target_name）
- 提醒单回归单一功能：`/generate/reminder` 纯同步返回 xlsx；移除版本检查勾选框与 T7 异步机器（_TASKS/线程/`/generate/task` 两路由/apply_reminder_version_section），版本检查职责由逐包按钮承担
- `check_cards_against_amro`：移除 new_by_category（包内新卡由匹配流程负责）；版本比对仅对库内已存在的卡
- 工卡改版清单 Excel 第三行标记按类型着色：新增=红、改版=蓝、作废=黑（此前三类均红）；写入单元格显式 wrap_text，超出模板样式行的条目也稳定呈现三行（工卡号/工卡名称/标记）
- 作废工卡清单页移除「作废来源」列（表头/数据行/详情弹窗均不再展示；`cancel_source` 数据字段保留）
- 说明文档重写（README.md / SERVER_README.md）：改为「优势 → 功能 → 操作说明」结构，精简冗长 UI 规范与验收标准，突出用户与运维视角
- 工卡清单「编写日期」、作废清单「作废日期」列新增区间筛选（全部时间 / 近一个月 / 近3个月 / 近一年），与现有文本筛选叠加；共享 `AppFilter` 扩展 `data-date-col` 日期区间筛选
- 全应用日期格式彻底统一为 YYYY-MM-DD（`%Y-%m-%d`）：① 工作包「工卡版本变动清单」编写日期由原始完整时间（如 `2026-08-01 09:00:00`）改为取前 10 位日期（`utils/dates.fmt_date10` 工具统一处理）；② 查询/报表日期与文件名/标题嵌入日期由 `%Y.%m.%d` 点分统一为 `%Y-%m-%d`（需求单/提醒单/全量改版清单/逐包改版清单下载名、工作包与 AMRO 导入包日期默认值、卡片全量改版清单下载名等）；③ 查询完成时刻由 `%Y.%m.%d %H:%M` 点分统一为 `%Y-%m-%d %H:%M`；④ 内部文件名时间戳由 `%Y%m%d_%H%M%S` 统一为 `%Y-%m-%d_%H-%M-%S`（短横替冒号，Windows 文件名安全）；`_dot_date` 改名 `_ymd_date` 并同步输出短横日期。至此全应用不再存在点分 / `YYYYMMDD` 形态的日期格式，瞬时字段保留时分秒（`%Y-%m-%d %H:%M:%S`）
### Fixed
- 库存查询偶发「未登录 AMRO」：登录改造后前置探活把网络抖动/限流（probe_error）误判为未登录 → 401；改为仅 无凭证/明确失效 阻断，网络未知放行（真实失效由查询自身 AMRO 调用暴露并 401），多点几次才成功的问题消除
- 库存查询「下载副本」提示文件不存在：下载链接的文件名未做 URL 编码，文件名含 `+`（如 `68A+24MO`）被 WSGI 解码成空格导致与磁盘文件不符（`&`/`#` 同理截断）；生成与回退链接统一 `quote` 编码、渲染校验先 `unquote`，含特殊字符文件名可正常下载
- 库存预警「编辑/删除」对含 `/` 件号（如 `PR1425CFB1/2`）404：路由 `<part_number>` 改 `<path:part_number>`（跨斜杠捕获，`%2F` 亦兼容）；列表链接编码由 `urlencode`（空格→`+`，路径段不解）改为补 `replace('+','%20')`，含空格件号亦可正常编辑/删除
- 操作日志行点击飞机目标改为弹窗预览（新增 `GET /card/aircraft/<id>` 详情 JSON），不再整页跳编辑页——飞机已删除时与工卡/工卡组一致提示「该记录已删除」，不再整页 404；日志预览渲染字段同步 HTML 转义
- 删除按钮确认文案/URL 改 `data-url`/`data-confirm` 属性传参（`ListUI.delFrom`），件号或名称含引号不再破坏 JS；生成页「新增工卡」跳转 query 参数补 urlencode（防 `&` 截断）；预警编辑表单件号注入改 `tojson`（防单引号破坏 JS）
- 工作包 AMRO 导入字段根因修复：包头字段（机号 ACNO/描述 REVTITLE/定检开工日期 PLANSTD 等）只存在于包列表 BM_TSK_LIST，此前从包内容清单取导致机号/描述为空、日期落成导入日——现由前端把选中列表行随导入请求传入，缺失时按 REVNR 兜底回查包列表
- 全量查询工卡版本 EOJC 深分页超时根因修复（2026-09-03 晚两连挂）：EOJC 深分页延迟逐页递增不可控（实测 p1≈12s→p12≈88s，全量 12 页约 12 分钟），150s 读超时被真实流量击穿且失败零审计痕迹——全量检查改为复用逐包检查的取数策略（CSCA 走 SMJC 全量拉秒级，其余逐卡 `TD_JC_ALL_GET_ENTITY_BY_JCNO` 直查，全程约 3 分钟可预测），彻底移除 EOJC 深分页调用
- 库存查询页持久化摘要的下载链接在旧副本被新查询清理后失效（「文件不存在」）：渲染时回退当前仍存在的最新库存副本，均无则不渲染下载
- 库存查询页移除重复的第二套查询结果输出（#resultBox/loadLatestOutput/renderResult），仅保留持久化摘要块；工卡信息页移除与规范摘要块重复的「⬇下载」锚点
- 登录状态提示条（❌ 查询登录已过期：请重新运行登录脚本）从顶栏下方独立块并入顶栏，始终位于网页最上方
- 工卡版本检查摘要新增「新增 N 张」；库内原无编写日期的工卡经版本检查自动补填日期后归入「新增」而非「改版」（改版仅限跨天日期变化）；改版清单 Excel 单元格内第三行以红字标注（改版=旧→新 / 新增=新增 日期 / 作废=作废），前两行黑字
- 操作日志筛选新增「结束日期」输入：仅填起始=该日起至今，起止同值=单日，起止区间=含两端（沿用 YYYY-MM-DD 切片比较，不动模型层 get_logs）
- 一键登录适配 AMRO 手机验证码步骤：本机登录脚本（`amro_login.py`）打开浏览器后不再按 JSESSIONID 出现即抓取（登录页本身会种 JSESSIONID，易取到半截会话），改为由你人工完成手机验证+账号登录后，点击页面右下角「✅ 完成登录」按钮或回到脚本窗口按回车，脚本才抓取全部 cookie 上传；脚本版本 `AMRO_LOGIN_VERSION` 2→3（`check-config` 门禁标记旧脚本、提示重新下载配置包）
- 工作包接收查询移除日期窗：`list_amro_packages` 不再向 BM_TSK_LIST 传 `planstdstr`/`planstdEnd`（此前按今±7天过滤），返回接收页面全部任务包（单页 `rows=50` 不变）；页面文案「日期窗内暂无任务包」改「暂无任务包」
- 工卡版本检查取数收敛为四权威源实时查询（定检 CSC / 飞机维护 FLA / EO / QEC-R），每次检查均实时拉取 AMRO（无工卡缓存库）；CSC、FLA、QEC-R 走各端点 `fleet=A320` 全量拉取，EO 按包内卡号逐卡直查；任一全量拉取失败回退逐卡查询，避免误判作废。非四家族（含 DP 项目）卡**跳过不查询、不判作废**（此前兜底逻辑会把界外卡误作废）
- 工卡版本检查范围严格二分：全量=库内所有四家族卡；工作包=仅包清单内四家族卡。工作包「新增」判定遵循人工前置入主库约定——包内工卡由人工在查询前新建/编辑入主库，系统不自动建卡；库内原无编写日期、AMRO 查到后补填日期的卡归入「新增」，全量与工作包 toast 均补展示「新增 N 张」（此前仅 persist 摘要含该字段、toast 漏显）
- 一键登录配置通用化：⚡按钮改传 `ReqManLogin://<当前页 host>`，`start_login.bat` 解析协议参数来源、`amro_login.py` 新增 `--server` 按来源动态定址上传（回退烘焙地址）；同一配置包在本地/服务器均可登录，解决「本地建配置→服务器登录取不到 cookie / 反之」不通用的根因
- 工卡版本检查四家族实时取数补全：飞机维护工卡（FLA）批量端点 `TD_JC_NRCJC_LIST`（手册工卡→飞机维护工卡）经实时只读探测确认（code=200、返回 FLA* 前缀、WRITE_DATE 100% 有值、fleet=A320 服务端过滤 646→356），加入只读白名单，FLA 族由逐卡回退切换为全量拉取；至此 CSC/FLA/QEC-R/EO 四家族端点全部确认：CSC（SMJC 1319→745）、FLA（NRCJC 646→356）、QEC/ER（QECJC_LIST 89→56）均经专用端点 fleet=A320 全量拉取实测生效，其中 QEC/ER 工卡（QECJC*/ERJC*）此前误用 EOJC 端点（该端点不含 QEC/ER 工卡，会导致库内 QEC/ER 卡被误判作废移库），本次更正为专用 `TD_JC_ALL_QECJC_LIST` 并加入只读白名单；EO 仍按包内卡号逐卡直查（`TD_JC_ALL_GET_ENTITY_BY_JCNO`）
- 预览页「📥 生成工卡改版下载」未查询工作包工卡版本时点击不弹提示（裸 `<a href>` 直跳、404 仅返回原始 JSON）：改为按钮 + fetch 处理器，命中服务端 404（`NO_VERSION_REPORT`）时经 `safeToast` 弹出「尚未查询该工作包的工卡版本，请先在工作包页点击「查询工作包工卡版本」」，已查询则正常触发下载
### Removed
- 库存查询页登录区块迁移表头（沿用 3.5.0 收尾），「检查配置」相关表述清理完毕
- register_protocol.bat 三级桌面路径探测（%USERPROFILE%/OneDrive/注册表）不再需要（协议自定位替代）

### Docs
- 文档刷新：README 功能模块补充 AMRO 三域数据同步（飞机同步/工作包/工卡版本比对/作废工卡库），版本迭代标注 V3.6.0 已交付；SERVER_README 环境变量表对齐 config.py（移除已废弃 AMRO_API_URL，新增 AMRO_RATE_SECONDS/AMRO_AUDIT_FILE/AMRO_AC_FLEET/AMRO_BASE_DEFAULT/AMRO_CARD_FLEET），data/ 目录补充 cancelled_cards.json、cookie/、amro_audit.jsonl

### 优化（结构 / 性能 / 安全 / 测试审计）
- 安全：`config.DEBUG` 默认 `False`（仅显式 env 开启）；`generate_bp.package_version_report` 校验 `package_id` 格式（`^[A-Za-z0-9_-]+$`）+ `path.resolve().parent == OUTPUT_DIR` 断言，否则 400；`session._atomic_write` 写后 `os.chmod(0o600)`（父目录 `0o700`），Windows 经 `os.name != "nt"` 跳过只读位陷阱；移除废弃 `AMRO_SESSION_TTL` 与 session 的 `ttl_seconds/remaining_seconds/expires_at` 兼容桩
- 死代码：删除 `amro_sync.package_display_label`/`package_report_label`、`json_store.trim_logs`（已先行移除）；修正 `amro_sync`「待确认加入」→「已确认」过时注释
- 解耦：`MESSAGES` 由 `inventory_bp.py` 迁 `utils/messages.py`，`cards_bp`/`packages_bp`/`inventory_bp` 改 import；`services/import_vba_config.py` 迁 `scripts/lib/`，同步更新 `scripts/import_vba_config.py` 与 `tests/test_import_vba_config.py` 的 import
- 性能：`JsonStore.find_by_codes(codes)` 单次 `_read()` 批量返回（消除逐卡 `find_by_code` 的 N+1 整库重读）；`work_package_matcher.match_work_package_items` 改用批量查、传 `cards_by_code` 给 `propagate_set_data`/`dedup_by_set`；`cards_bp.card_sets` 改单次读（`list_card_sets_with_cards`）；新增对应单测
- 结构（T1）：三大模块拆包——`services/amro_sync`、`blueprints/cards_bp`、`models/json_store` 均拆为包，`__init__` 重导出全部公开符号，外部 `import` 路径零改动。子模块经包级属性运行时取值以兼容测试 monkeypatch：`amro_sync.OUTPUT_DIR`/`QUERY_STATUS`/`sync_aircraft`、`cards_bp.OUTPUT_DIR`、`json_store.os`；拆分后 `JsonStore` 经 `JsonStoreCore → CardStore → WorkPackageStore → LogStore` 继承链组合
- 测试审计（ponytail）：删除 `tests/conftest.py` 未使用的 `make_card`/`make_card_set`/`make_form`/`_ts` 与 `tests/integration/conftest.py` 未使用的 `make_form`/`make_card_form`（其中 `make_form` 在两处重复定义）；ruff 清理对应冗余 import；测试套件保持 514 通过（另 4 项性能 slow 测试通过）

### UI 交互优化（可访问性 + 体验 + 内网自托管）
- 抽公共 `window.apiSubmit(form, url, opts)`：统一 4 个表单的 fetch 提交（禁用按钮防连点 + loader + 字段级错误高亮 + 成功回调），消除重复样板
- 字段级错误回显：后端 `api_error` 新增 `field` 透传，校验失败前端高亮对应 `name`/`id` 字段并聚焦、toast 提示；不再只看整页错误
- 校验失败丢数据修复：工卡/工卡组/飞机 新建·编辑 校验失败改为用 `request.form` 回填 re-render（不再 `redirect` 到空白表单），已填内容不丢
- 表单 `label[for]` 与 `input[id]` 关联（工卡/工卡组/飞机/库存预警/生成需求单 5 个表单），点击标签聚焦输入框，读屏可朗读
- 列表详情行键盘可达：工卡/飞机/工卡组/作废工卡 行加 `tabindex=0 role=button`，Enter/空格触发详情
- 可访问性补齐：skip-link「跳到主内容」、`:focus-visible` 焦点轮廓、`.status-cancelled` 对比度达标（白底深灰字）、`prefers-reduced-motion` 关闭动画；AMRO 状态徽章可键盘触发检查；JS 生成的行内「×」删除按钮加 `aria-label="删除此行"`；库存上传区键盘可达（Tab+回车选文件）
- 自定义确认模态 `window.confirmModal()` 替原生 `confirm()/alert()`：可样式化、非阻塞、支持危险态红色；覆盖表单删除/重置、生成需求单、飞机 AMRO 同步、工作包重新匹配、工卡组重置
- 删除/重置成功就地更新 DOM（移除行 / 局部刷新）替整页 `location.reload()`，减少闪烁；失败回退整页刷新
- 内网自托管 Bootstrap：`static_folder` 由 `None` 改 `"static"`，Bootstrap 5.3.3 CSS/JS 入 `static/vendor/bootstrap/`，`base.html` CDN 引用改 `url_for('static', ...)`，断网/内网可用、去外部依赖（jsDelivr 内网多被墙）
- 冗余清理：删除被 `apiSubmit` 替代的 4 表单 fetch 样板、被 `confirmModal` 替代的原生 `confirm/alert` 调用、危险的弹窗提交 `form.submit()` 兜底；全局 ruff + grep 扫描无孤立引用

## [3.5.0] - Unreleased
### Added（AMRO 三域数据同步——基于 amro-research 实测的 7 个只读端点，全程只读+审计留痕）
- 通用只读调用器 `query_plugin`：端点白名单硬编码（写/导出/生成类一律拒绝）、全局限速 ≥2s、JSONL 审计（`data/amro_audit.jsonl`）、会话失效统一 401+P8 文案
- 飞机信息同步：飞机信息页「⟳ 从 AMRO 同步」——在册（A320 且有效）六字段覆盖/新增（含 APU 补齐），不在册飞机清理（确认弹窗+报告+日志留档）
- 工作包直读：工作包页新增「🔄 从 AMRO 拉取工作包」（任务接收列表，日期窗今±7天）→ 选包导入自动匹配入库；上传功能原样保留（硬性验收项）
- 工卡版本检查：工卡数据页「🔍 工卡版本检查」——实时拉 SMJC+EOJC 全量清单比对编写日期，改版自动更新卡并记版本日志；已作废工卡列出不删除；生成改版清单 Excel 下载
- 提醒单集成：勾选「工卡版本检查」（默认勾选）→ 异步生成（任务轮询下载），提醒单附加改版工卡/新工卡（蓝底）与作废工卡（浅红底）区块；不勾选走原同步路径
- 数据模型：卡新增 `write_date`（AMRO 编写日期，旧数据零迁移）；runtime 新增 `amro_sync_meta` 同步状态
- 表头常驻 AMRO 登录三件套：状态徽章（10 分钟轮询+点击即查）+ ⚡一键登录（ReqManLogin:// 协议，未注册自动降级）+ 🛠新建配置（ZIP 含 register_protocol.bat 一次性注册）
- 库存查询页移除登录区块（迁表头），预留库存预警空间
### Changed
- 提醒单生成支持异步化：长任务 daemon 线程 + 状态轮询（规避 gunicorn 120s 超时），不勾选版本检查时保留原同步路径

### 遗留（实施/冒烟注意）
- 工作包「撤销」判定沿用「备注含撤销」（PPCBZSM 独立标志未实测，首个含撤销项的包需对照 xlsx 校正）
- BM_TSK_LIST 日期窗参数格式（planstdstr/planstdEnd）按 ISO 日期实现，待真实会话冒烟验证
- 协议注册为每台机器一次性成本，杀软可能拦截；未注册自动降级为手动双击登录

## [3.4.6] - 2026-08-30
### Changed
- 分支工作流调整：所有改动在 `dev` 分支进行 → 验证通过合并本地 `main` 试用 → 试用通过推送 `main`；feature 分支流程废除，`dev` 仅本地不推送
- 文档同步：agent.md §二、SERVER_README §5.1/§5.2/§5.4 按新流程重写；SERVER_README 版本与架构描述纠偏（Gunicorn 1w×4t）
- 服务器部署流程补充：仓库改过 `config/reqman.service` 时，pull 后必须手动刷新 systemd 单元（`cp` + `daemon-reload`）

## [3.4.5] - 2026-08-30
### Fixed（数据安全四项严重缺陷，均经服务器最新数据实证）
- next_id 计数器落后于现存实体（1032 vs 1036），新建工卡/工卡组会静默覆盖现有数据。读取时自愈为 max(实体ID)+1，分配时跳过已占用 ID
- code_index 索引悬挂/错映射（`CSCA320-783200-W1-1-1` 误指向卡 1023），原条数检查查不出。改为双向校验（键→卡存在且工卡号匹配、数量一致），不一致即重建
- 原子写失败 fallback 直接截断覆盖好文件（磁盘满/写失败即毁库）。改为失败保留原文件并抛异常（json_store + session）
- 启动日志裁剪阈值 200 低于现存 264 条审计日志，每次启动无提示删除 64 条。阈值调整为 2000
### Fixed（其他）
- `save_work_package` 读改写补加线程锁（原为唯一无锁写路径，并发丢失更新）
- 编辑工卡号校验不得占用其他卡的编号（脏索引产生源头），页面返回错误提示
- 数据文件读取损坏时拒绝一切写入并告警，防止"半张库"被合法化持久化；修复启动自愈死代码（损坏检测从未生效）
- 备份体系补齐运行时文件 `reqman_db_runtime.json`（.bak / 关闭备份 / cron / db.sh 恢复全链路；此前该文件无任何备份）；关闭备份改用项目根绝对路径
- 上传工作包 AJAX 响应回传真实 `package_id`（曾恒为 null，前端无法跳转预览）
- `get_all` 对缺 `task_code` 键的数据容错（曾直接 KeyError 500）
- 飞机机号新增/编辑增加必填与重复校验；移除无读者的 `next_ac_id` 死键

### Changed
- 日志保留策略统一：操作日志上限改为 500 条，每次新增日志后自动清理多余旧条目（本地/服务器同一行为）；移除启动时裁剪；裁剪排序改为按 (时间, 日志id) 双键，时间平局时正确保留最新
- 系统更名：全站统一为 **ReqMan定检准备系统**——浏览器标题（12 个页面模板）、导航栏品牌（改为文字层级设计：ReqMan 加粗 + 中点分隔 + 定检准备系统细体，移除 emoji）、启动横幅、README/SERVER_README 标题、systemd Description、部署与数据库脚本、OpenAPI 文档标题、AMRO 登录脚本提示文案
- 部署：服务器 gunicorn 由 4进程×2线程 调整为 1进程×4线程。JSON 存储锁为进程内锁，多进程并发读写同一对数据文件存在丢更新与 ID 竞争；内部工具单进程足够，并消除 4 份重复关闭备份。未来确需多 worker：先为 JsonStore 增加 fcntl/msvcrt 跨进程文件锁
- 版本号统一为 3.4.5（README 此前 3.4.0、启动横幅此前 3.2.5）

### 服务器更新步骤（本地为数据源）
1. 本地启动一次应用完成数据自愈，确认日志出现 next_id 自愈/索引重建记录，且工卡/工卡组列表完整
2. 服务器 `git pull` 并重启：`systemctl restart reqman`（新代码加载即单进程模型）
3. 同步已自愈的数据：`scp data/reqman_db.json data/reqman_db_runtime.json root@<server>:/root/workspace/reqman/data/`（数据文件不进 Git，需手动同步；服务器重启后自愈逻辑会再兜底一次）
   - ⚠️ 覆盖前先在服务器留存副本：`cp data/reqman_db.json data/backups/reqman_db_pre_sync_$(date +%Y%m%d).json`。v3.4.5 开发期间本地曾以旧阈值(200)裁掉 64 条审计日志（264→200），服务器现存数据中仍是全量 264 条，覆盖后即不可找回；如需留存审计可事后按日志 id 合并
4. 核对：服务器启动日志无损坏/自愈告警，工卡、工卡组、日志条数与本地一致

### 遗留问题（后续迭代取用）
- AMRO 会话 cookie 明文落盘 `data/cookie/`，登录上传端点无鉴权，nginx 无 basic auth
- AMRO 查询零审计（谁/何时/查了什么无记录）；单全局会话 TTL 2h，异地登录互踢
- AMRO API URL/表单字段/cookie 名 `JSESSIONID` 全硬编码，接口改版即断
- 工作清单 Excel 列位/日期解析硬编码，模板变化静默产出空值；`_parse_qty` 对 "1,000"/"1.2.3" 误解析
- 工卡状态判定逻辑三处重复（matcher/card_service/generate_bp），v3.4.4 漏改即其产物
- 工卡组提醒字段无条件覆盖子卡（`sync_set_to_cards`）
- 大规模爬取差距：同步阻塞+前端 65s 硬超时、无重试/限速/断点/任务状态、多用户输出互踩
- 工卡版本(revision)数据模型不存在；提醒为人工字段+手动下载，无主动通知
- 结构：前端 CSS/JS 内联模板、双 venv、uv.lock 不入库、docs/superpowers 不入库

## [3.4.3] - Unreleased
### Changed
- 数据同步：停止 Git 追踪 `reqman_db.json`，改为手动 scp 同步
- 数据备份：新增 `scripts/auto_backup.sh`，服务器 cron 每天 0:00 自动备份，保留 7 天
### Fixed
- 工卡匹配索引：修复从服务器导入数据后 code_index 不完整的问题（自动重建）

## [3.4.2] - Unreleased
### Fixed
- 工卡匹配索引：修复从服务器导入数据后 code_index 为空导致所有工卡进入新工卡区的问题（自动重建空索引）

## [3.4.1] - Unreleased
### Added
- 工卡组详情API：新增 `GET /card/sets/<id>` 接口，支持工卡组数据预览
- 日志预览功能：操作日志页面点击条目弹窗查看工卡/工卡组详情（基本信息+工具+航材+提醒+确认状态）

### Fixed
- 确认勾选框联动：修复提醒/工具/航材确认勾选框在有数据时仍被错误勾选的bug
- 提醒类型显示：修复工卡/工卡组列表中提醒类型已确认时不显示的问题
- 确认状态统一：统一modal预览中提醒确认状态显示格式（改为badge模式，与工具/航材一致）

### Changed
- 提醒单匹配：工卡属于工卡组时输出工卡组名称（set_name）而非单个工卡名，同组工卡去重
- 列表搜索统一：工卡列表专业/类型筛选改为下拉框，工卡组列表专业筛选改为下拉框
- 移除排序：工卡/工卡组/飞机信息列表移除列标题排序功能

### Fixed
- 飞机信息搜索：修复搜索框不可用问题（补充 data-col 属性绑定）

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
