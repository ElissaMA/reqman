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
