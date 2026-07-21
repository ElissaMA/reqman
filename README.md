# 定检需求单管理系统 V3

飞机定检需求单管理系统，支持工卡管理、工作清单上传解析、需求单自动生成。

## 功能特性

- **工卡管理** — CRUD + 搜索/筛选 + 工卡组 + 工具/航材管理
- **工作包匹配** — 上传工作清单 Excel，自动与工卡数据库匹配
- **需求单生成** — 生成定检需求单 Excel，支持预览与下载
- **工卡组显示** — 匹配工卡组时，Excel 中显示工卡组名称而非单个工卡名称
- **飞机信息管理** — 维护飞机基础信息

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（Windows）
start.bat

# 启动（Linux/macOS）
bash start.sh

# 或直接运行
export PYTHONPATH=src
python src/reqman/app.py
```

启动后访问 http://127.0.0.1:5001

## 项目结构

```
需求单v1.0/
├── src/reqman/          # 核心源码包
│   ├── __init__.py      # Flask 应用工厂
│   ├── app.py           # 启动入口
│   ├── config.py        # 环境变量驱动配置
│   ├── blueprints/      # 路由蓝图层
│   ├── services/        # 业务服务层
│   ├── models/          # 数据模型与持久化
│   ├── templates/       # Jinja2 模板
│   └── utils/           # 工具模块
├── tests/               # 测试
├── assets/              # 静态资源（Excel 模板）
├── data/                # 运行时数据库
├── output/              # 生成的需求单输出
├── pyproject.toml       # 项目统一配置
├── .env.example         # 环境变量模板
└── .github/workflows/   # CI 自动化
```

## 环境变量

复制 `.env.example` 为 `.env`，按需修改以下配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SERVER_HOST` | 服务绑定地址 | `127.0.0.1` |
| `SERVER_PORT` | 服务端口 | `5001` |
| `DB_FILE` | 数据库路径 | `data/reqman_db.json` |
| `TEMPLATE_FILE` | 需求单模板路径 | `assets/demand_template.xlsx` |
| `GENERATED_DIR` | 生成文件输出目录 | `output` |
| `CATEGORIES` | 工卡分类 | `发动机,机体,电子,特检,支援` |

## 技术栈

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Flask](https://img.shields.io/badge/flask-3.1+-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

- **后端**: Flask 3.1+ (工厂模式 + 蓝图)
- **Excel 处理**: openpyxl
- **配置**: python-dotenv, pathlib
- **测试**: pytest, pytest-cov

## FAQ

**Linux 下生成的 Excel 中文乱码？**

需要安装中文字体（如 `fonts-wqy-zenhei`），模板中使用了 SimSun 字体。

**数据库文件在哪里？**

默认路径为 `data/reqman_db.json`，纳入 Git 版本管理。可通过 `DB_FILE` 环境变量自定义。