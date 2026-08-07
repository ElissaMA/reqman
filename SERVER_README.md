# 定检需求单管理系统 — 服务器运维手册

> 版本：V3.2.2 | 目标环境：Ubuntu 22.04 LTS (云服务器)

---

## 1. 系统概述

定检需求单管理系统用于航空维修中的工卡管理、工具/航材核对和定检需求单自动生成。

- **运行架构**：Python 3.11 + Gunicorn + Nginx Docker 容器化部署
- **对外访问端口**：**80**
- **部署目录**：`/opt/reqman`

---

## 2. 快速启动

```bash
# 一键部署（自动检查 Docker、创建配置、构建镜像、启动服务）
bash scripts/deploy.sh
```

部署完成后访问：`http://<服务器IP>`（80端口）或 `http://<服务器IP>:8080`（如使用8080端口）

---

## 3. 常用运维命令

### 服务管理

```bash
# 启动服务
docker compose up -d

# 停止服务
docker compose down

# 重启服务
docker compose restart

# 重新构建并启动（代码更新后）
docker compose up -d --build

# 查看服务状态
docker compose ps

# 查看容器资源占用
docker stats
```

### 日志查看

```bash
# 查看应用日志（实时）
docker compose logs -f reqman

# 查看最近 100 行日志
docker compose logs --tail 100 reqman

# 查看 Nginx 日志
docker compose logs -f nginx
```

### 进入容器

```bash
# 进入应用容器（调试用）
docker compose exec reqman bash
```

---

## 4. 数据库备份

```bash
# 备份（gzip 压缩，自动清理过期备份）
bash scripts/db.sh backup

# 恢复最近一次备份
bash scripts/db.sh restore

# 恢复指定备份文件
bash scripts/db.sh restore backups/reqman_db_20260805_020000.json.gz

# 查看所有备份
bash scripts/db.sh list

# 清理超过 28 天的备份
bash scripts/db.sh clean 28
```

> 自动备份已配置为每周六凌晨 2:00 执行（cron: `0 2 * * 6`）

---

## 5. 常见问题

### Q: 服务无法启动，端口被占用

```bash
# 查看端口占用
lsof -i :80
# 或查看后端端口
lsof -i :5001

# 终止占用进程
kill -9 <PID>
```

### Q: 页面加载慢或超时

```bash
# 检查 Gunicorn 工作进程
docker compose exec reqman ps aux | grep gunicorn

# 重启服务
docker compose restart
```

### Q: 数据库文件损坏

```bash
# 恢复最近备份
bash scripts/db.sh restore

# 查看所有备份选择合适的
bash scripts/db.sh list
bash scripts/db.sh restore backups/reqman_db_20260801_020000.json.gz
```

### Q: Excel 上传失败

```bash
# 检查 Nginx 配置中的上传限制
docker compose exec nginx cat /etc/nginx/conf.d/default.conf | grep client_max_body_size

# 检查磁盘空间
df -h /opt/reqman/data
```

### Q: 容器内磁盘空间不足

```bash
# 清理 Docker 无用镜像
docker system prune -f

# 清理旧备份
bash scripts/db.sh clean 14
```

### Q: 如何更新代码

```bash
# 1. 上传新代码到服务器
# 2. 重新构建并重启
cd /opt/reqman
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Q: 如何查看系统版本

```bash
docker compose images reqman
```

---

## 6. 目录结构

```
/opt/reqman/
├── src/                    # 应用源代码
│   └── reqman/             # Flask 应用
├── assets/                 # 需求单 Excel 模板
├── data/                   # 数据库文件（持久化）
│   ├── reqman_db.json      # 核心数据
│   └── reqman_db_runtime.json  # 运行时数据
├── output/                 # 生成的需求单 Excel（持久化）
├── backups/                # 数据库备份
├── deploy/                 # 部署配置
│   └── nginx.conf          # Nginx 反向代理
├── scripts/                # 运维脚本
│   ├── deploy.sh           # 一键部署
│   └── db.sh               # 数据库管理
├── .env                    # 环境变量（勿提交到 Git）
├── Dockerfile              # Docker 镜像定义
└── docker-compose.yml      # 容器编排
```

> `data/` 和 `output/` 通过 Docker volume 挂载，容器重启后数据不丢失。
