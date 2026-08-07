# 定检需求单管理系统 — 云服务部署计划

> 版本：V3.2.2 | 目标环境：Ubuntu 22.04 LTS (云服务器)  
> 更新日期：2026-08-07

---

## 目录

1. [部署架构概览](#1-部署架构概览)
2. [跨平台兼容修改](#2-跨平台兼容修改)
3. [Docker 容器化](#3-docker-容器化)
4. [一键部署脚本](#4-一键部署脚本)
5. [数据库备份/恢复](#5-数据库备份恢复)
6. [部署流程说明](#6-部署流程说明)
7. [验证清单](#7-验证清单)
8. [部署文件清单](#8-部署文件清单)
9. [踩坑修复说明](#9-踩坑修复说明)

---

## 1. 部署架构概览

```
┌─────────────────────────────────────┐
│          Ubuntu Cloud Server        │
│                                     │
│  ┌──────────────────────────────┐   │
│  │   Docker Container           │   │
│  │   ┌──────────────────────┐   │   │
│  │   │  Gunicorn (4w × 2t)  │   │   │
│  │   │  Flask App           │   │   │
│  │   │  port: 5001          │   │   │
│  │   └──────────────────────┘   │   │
│  │                              │   │
│  │   /app/data/reqman_db.json   │   │
│  │   /app/output/               │   │
│  └──────────────────────────────┘   │
│                                     │
│  ┌──────────┐  ┌───────────────┐   │
│  │ nginx    │  │ db.sh         │   │
│  │ (反向代理)│  │ (每周六备份)  │   │
│  └──────────┘  └───────────────┘   │
└─────────────────────────────────────┘
         ↕
   用户浏览器 (HTTP → 80 → Nginx → 5001)
```

**技术栈：**
- 运行时：Python 3.11 + Gunicorn (4 workers × 2 threads)
- 容器化：Docker + docker-compose
- 反向代理：Nginx (80端口)
- 进程管理：Docker Compose (`restart: unless-stopped`)

**端口映射：**
```
用户浏览器 → 80 (Nginx) → 5001 (Gunicorn) → Flask 应用
              ↑ 外部端口       ↑ 内部端口
```

---

## 2. 跨平台兼容修改

### app.py 平台判断

| 函数 | Windows | Linux/macOS |
|------|---------|-------------|
| `find_pid_by_port()` | `netstat -ano` | `lsof -i :PORT -t` |
| `kill_process()` | `taskkill -f -pid` | `kill -9` |
| `wait_and_open()` | 自动打开浏览器 | 仅打印 URL |

### config.py 环境判断

```python
HOST: str = os.getenv(
    "SERVER_HOST",
    "0.0.0.0" if os.getenv("FLASK_ENV", "development") == "production" else "127.0.0.1",
)
```

---

## 3. Docker 容器化

### Dockerfile

```dockerfile
FROM python:3.11-slim

LABEL maintainer="定检需求单管理系统"
LABEL version="3.2.2"

WORKDIR /app

# pip 清华镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

COPY src/ src/
COPY assets/ assets/

RUN mkdir -p data output

ENV PYTHONPATH=/app/src
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=5001
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 5001

# 多进程、超时120s、日志标准化输出
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "4", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "reqman:create_app()"]
```

### docker-compose.yml

```yaml
services:
  reqman:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: reqman-app
    restart: unless-stopped
    ports:
      - "5001:5001"
    volumes:
      - ./data:/app/data
      - ./output:/app/output
      - ./.env:/app/.env:ro
    environment:
      - FLASK_ENV=production
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=5001
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  nginx:
    image: nginx:alpine
    container_name: reqman-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      # - "443:443"  # HTTPS 如需启用
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      # - ./deploy/ssl:/etc/nginx/ssl:ro  # HTTPS 证书
    depends_on:
      - reqman
    security_opt:
      - no-new-privileges:true
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### Nginx 配置

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 20M;
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    location / {
        proxy_pass http://reqman:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 4. 一键部署脚本

`scripts/deploy.sh` 执行以下步骤：

1. 检查 Docker 是否安装并运行
2. 创建 `.env` 环境变量文件（自动生成 SECRET_KEY）
3. 创建数据目录 `data/` `output/`
4. 构建 Docker 镜像
5. 启动 Docker Compose 服务
6. 配置 cron 定时备份（每周六凌晨2点）
7. 等待服务就绪并验证

---

## 5. 数据库备份/恢复

使用 `scripts/db.sh` 统一管理：

```bash
bash scripts/db.sh backup              # 备份（gzip压缩）
bash scripts/db.sh restore             # 恢复最近备份
bash scripts/db.sh restore <文件>      # 恢复指定备份
bash scripts/db.sh list                # 列出所有备份
bash scripts/db.sh clean [天数]        # 清理过期备份（默认28天）
```

---

## 6. 部署流程说明

### 首次部署

```bash
ssh root@<服务器IP>
# 上传代码后
cd /opt/reqman
bash scripts/deploy.sh
```

### 后续更新

```bash
cd /opt/reqman
git pull origin feature
docker compose down
docker compose build --no-cache
docker compose up -d
```

### 备份恢复

```bash
bash scripts/db.sh list         # 查看可用备份
bash scripts/db.sh restore      # 恢复最近备份
```

---

## 7. 验证清单

- [ ] Docker 容器运行中：`docker compose ps`
- [ ] 应用端口可达：`curl -s -o /dev/null -w "%{http_code}" http://localhost:80/`
- [ ] HTTP 响应码 200
- [ ] 数据持久化：重启后数据不丢失
- [ ] 备份脚本正常：`bash scripts/db.sh backup`
- [ ] cron 自动备份已配置：`crontab -l | grep db.sh`

---

## 8. 部署文件清单

### 需要上传的文件

| 文件/目录 | 说明 |
|-----------|------|
| `src/` | 应用源代码 |
| `assets/` | 需求单模板 |
| `data/` | 数据库目录 |
| `requirements.txt` | Python 依赖 |
| `Dockerfile` | Docker 镜像 |
| `docker-compose.yml` | 容器编排 |
| `.dockerignore` | 构建排除 |
| `.env.example` | 环境变量模板 |
| `deploy/nginx.conf` | Nginx 配置 |
| `scripts/deploy.sh` | 部署脚本 |
| `scripts/db.sh` | 数据库管理 |
| `pyproject.toml` | 项目配置 |

### 不需要上传的文件

`.git/`、`tests/`、`venv/`、`.coverage`、`.pytest_cache`、`.ruff_cache`、`htmlcov/`、`build/`、`.vscode/`、`start.bat`、`tmp_*`

---

## 9. 踩坑修复说明

### 9.1 Dockerfile 优化

| 优化项 | 修改前 | 修改后 | 原因 |
|--------|--------|--------|------|
| 系统依赖 | `apt-get install lsof curl` | 移除 | 容器内不需要，减少镜像体积 |
| pip 源 | 默认 PyPI | 清华镜像源 | 国内下载速度提升 5-10 倍 |
| 健康检查 | `HEALTHCHECK` 段 | 移除 | 简化配置 |
| Gunicorn | 单进程 | 4 workers × 2 threads | 提升并发处理能力 |
| 日志 | 默认配置 | `--log-level info` + stdout | 统一输出到 Docker 日志驱动 |

### 9.2 Compose 优化

| 优化项 | 修改前 | 修改后 | 原因 |
|--------|--------|--------|------|
| version 字段 | `version: "3.8"` | 移除 | Docker Compose V2 不再需要 |
| 健康检查 | reqman 含 healthcheck | 移除 | 简化配置 |
| Nginx 依赖 | `condition: service_healthy` | 简单列表 | 配合健康检查移除 |
| Nginx 端口 | `80:80` | `80:80` | 保持标准 HTTP 端口 |

### 9.3 安全配置

| 配置项 | 说明 |
|--------|------|
| `restart: unless-stopped` | 容器崩溃或服务器重启后自动恢复 |
| `read_only: true` | 容器文件系统只读，防止恶意写入 |
| `no-new-privileges` | 禁止容器内进程提升权限 |
| `X-Frame-Options` | 防止点击劫持 |
| `X-Content-Type-Options` | 防止 MIME 类型嗅探 |
| `X-XSS-Protection` | 启用 XSS 过滤 |
