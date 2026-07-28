# 贡献指南

## 开发环境

```bash
pip install -e ".[dev]"
cp .env.example .env
```

## 分支

- `main` — 稳定版
- `dev` — 开发
- `feature/*` — 功能

## 提交

1. Fork
2. 创建分支
3. `pytest` 测试通过
4. PR到`dev`

## 规范

- PEP 8
- ruff检查
- Python 3.10+ 类型注解

## 代码规范

### 提交前检查
- 运行 `ruff check src/ tests/ --fix` 自动修复格式问题
- 安装pre-commit钩子：`pip install pre-commit && pre-commit install`

### 编码规范
- 禁止使用裸 `except Exception`，应指定具体异常类型（如 `except (OSError, ValueError)`）
- import按标准库 → third-party → 本地 排序
- 使用 `dict | None` 而非 `Optional[dict]`（Python 3.10+）
- `datetime.now()` 需指定时区参数（本地应用用 `tz=None`）
- 禁止 `try-except: pass` 吞掉异常，应记录日志或抛出
