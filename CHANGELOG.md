# Changelog

## [3.2.5] - Unreleased
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
