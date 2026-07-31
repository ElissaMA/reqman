# 贡献指南

## 开发环境

```bash
pip install -e ".[dev]"
cp .env.example .env
```

## 分支

- `main` — 稳定版，日常使用、数据更新
- `dev` — UI完善、功能小改
- `feature` — 底层重构、功能大改

### 工作流程
1. 日常数据更新直接在 `main` 操作
2. **开始 dev/feature 工作前**：先 `git merge main` 同步最新数据
3. UI/小功能改进在 `dev` 开发，完成后合并到 `main`
4. 大改动/重构在 `feature` 开发，稳定后合并到 `main`
5. 合并后分支保留，继续开发

## 提交

1. 根据改动类型选择分支（main/dev/feature）
2. 在对应分支开发
3. `pytest` 测试通过
4. 合并到 `main`

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
