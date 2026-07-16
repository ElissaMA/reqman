# 贡献指南

## 开发环境搭建

```bash
pip install -e ".[dev]"
cp .env.example .env  # 按需编辑
```

## 分支规范

- `main` — 稳定版本
- `dev` — 开发分支
- `feature/*` — 功能分支

## 提交流程

1. Fork 仓库
2. 创建功能分支
3. 运行 `pytest` 确保测试通过
4. 提交 PR 到 `dev` 分支

## 代码规范

- 遵循 PEP 8
- 使用 `ruff` 进行检查
- 类型注解使用 Python 3.10+ 语法
