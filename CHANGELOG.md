# Changelog

## [3.2.0] - 2026-07-28

### Added
- 虚拟环境自动检测（app.py启动时自动切换venv）
- 日志功能测试（test_card_logs.py）
- 工作包功能测试（test_work_packages.py）
- 双文件存储测试（test_dual_file.py）
- 日志清理测试（test_log_cleanup.py）

### Changed
- 数据库拆分为核心文件+运行时文件（json_store.py双文件读写）
- .gitignore忽略运行时文件（reqman_db_runtime.json）
- 启动脚本简化（start.bat/start.sh）
- 测试覆盖从138提升至169

### Fixed
- 虚拟环境未激活时Flask导入失败

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
