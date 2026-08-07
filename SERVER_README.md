# 定检需求单管理系统 — 服务器运维手册

> 版本：V3.2.2 | 目标环境：Ubuntu 22.04 LTS (阿里云)

---

## 1. 系统概述

- **运行架构**：Python 3.11 + Gunicorn + Nginx（systemd 管理）
- **对外访问端口**：**80**
- **部署目录**：`/root/workspace/reqman`
- **服务器IP**：8.137.15.167

### 架构图

```
┌─────────────────────────────────────────────────┐
│            Ubuntu 22.04 LTS (阿里云)            │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  Nginx（80端口，反向代理 + 安全头）        │  │
│  │  config/nginx-reqman.conf                 │  │
│  └──────────────────┬────────────────────────┘  │
│                     │ 127.0.0.1:5001            │
│  ┌──────────────────▼────────────────────────┐  │
│  │  Gunicorn（4 workers × 2 threads）        │  │
│  │  systemd 服务：reqman.service             │  │
│  └──────────────────┬────────────────────────┘  │
│                     │                           │
│  ┌──────────────────▼────────────────────────┐  │
│  │  Flask 应用（src/reqman）                 │  │
│  │  create_app() 工厂                        │  │
│  └──────────────────┬────────────────────────┘  │
│                     │                           │
│  ┌──────────────────▼────────────────────────┐  │
│  │  data/reqman_db.json        核心数据       │  │
│  │  data/reqman_db_runtime.json 运行时数据    │  │
│  │  output/                    需求单 Excel   │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  ┌──────────────┐   ┌─────────────────────┐     │
│  │ db.sh        │   │ cron（每周六 02:00）│     │
│  │ (备份/恢复)  │   │ 自动备份            │     │
│  └──────────────┘   └─────────────────────┘     │
└─────────────────────────────────────────────────┘
         ↕
   用户浏览器（HTTP → 80 → Nginx → 5001 → Flask）
```

---

## 2. 快速启动

```bash
# 一键部署（首次）
cd reqman
bash scripts/deploy.sh
```

部署完成后访问：`http://8.137.15.167`（80端口）

---

## 3. 常用运维命令

### 服务管理

```bash
# 启动服务
systemctl start reqman

# 停止服务
systemctl stop reqman

# 重启服务
systemctl restart reqman

# 查看服务状态
systemctl status reqman

# 开机自启
systemctl enable reqman
```

### 日志查看

```bash
# 查看应用日志（实时）
journalctl -u reqman -f

# 查看最近 100 行日志
journalctl -u reqman -n 100

# 查看今天日志
journalctl -u reqman --since today
```

### Nginx 管理

```bash
# 重启 Nginx
systemctl restart nginx

# 查看 Nginx 状态
systemctl status nginx

# 测试配置语法
nginx -t
```

---

## 4. 数据库备份

```bash
# 备份（gzip 压缩，自动清理过期备份）
bash scripts/db.sh backup

# 恢复最近一次备份
bash scripts/db.sh restore

# 恢复指定备份文件
bash scripts/db.sh restore data/backups/reqman_db_20260805_020000.json.gz

# 查看所有备份
bash scripts/db.sh list

# 清理超过 28 天的备份
bash scripts/db.sh clean 28
```

> 自动备份已配置为每周六凌晨 2:00 执行（cron: `0 2 * * 6`）

---

## 5. 代码更新方式

### 更新前准备

```bash
# 备份数据库（推荐）
cp -r data data.bak.$(date +%Y%m%d)
```

### 步骤1：替换源码

将新代码上传或解压覆盖 `/root/workspace/reqman/src/` 目录。

**注意：** 保留 `data/`、`.env`、`venv/` 等运行时文件，切勿覆盖。

### 步骤2：重新安装包（关键步骤）

由于项目以 editable 模式安装，若仅修改了 Python 源码且未变更依赖/入口点，无需重装。

但若涉及以下任一情况，**必须执行重装**：
- `pyproject.toml` 或 `requirements.txt` 有变更
- 新增/删除了模块、蓝图、模板目录结构
- 入口函数 `create_app()` 所在文件路径变化

```bash
cd /root/workspace/reqman && ./venv/bin/pip install -e .
```

### 步骤3：重启服务

```bash
sudo systemctl restart reqman
```

### 步骤4：验证

```bash
# 确认服务状态
systemctl status reqman --no-pager | head -10

# 确认应用响应
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/
# 返回 2xx/3xx 表示正常
```

> **注意：** `data/` 目录存放运行时数据库 JSON，`.env` 含敏感配置，更新代码时切勿覆盖这两个位置。


---

## 6. 目录结构

```
/root/workspace/reqman/
├── src/reqman/             # 应用源代码
├── assets/                 # 需求单 Excel 模板
├── data/                   # 数据库文件
│   ├── reqman_db.json      # 核心数据
│   ├── reqman_db_runtime.json  # 运行时数据
│   └── backups/            # 数据库备份
├── output/                 # 生成的需求单 Excel
├── config/                 # 部署配置
│   ├── reqman.service      # systemd 服务
│   └── nginx-reqman.conf   # Nginx 站点配置
├── scripts/                # 运维脚本
│   ├── deploy.sh           # 一键部署
│   └── db.sh               # 数据库管理
├── venv/                   # Python 虚拟环境
├── .env                    # 环境变量
└── requirements.txt        # Python 依赖
```

---

## 7. 常见问题

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
# 检查 Gunicorn 进程
ps aux | grep gunicorn

# 重启服务
systemctl restart reqman
```

### Q: 数据库文件损坏

```bash
# 恢复最近备份
bash scripts/db.sh restore

# 查看所有备份选择合适的
bash scripts/db.sh list
bash scripts/db.sh restore data/backups/reqman_db_20260801_020000.json.gz
```

### Q: Excel 上传失败

```bash
# 检查 Nginx 配置中的上传限制
cat /root/workspace/reqman/config/nginx-reqman.conf | grep client_max_body_size

# 检查磁盘空间
df -h /root/workspace/reqman/data
```

### Q: 磁盘空间不足

```bash
# 清理旧备份
bash scripts/db.sh clean 14

# 查看备份目录大小
du -sh /root/workspace/reqman/data/backups/
```

---

## 8. 环境变量配置

编辑 `/root/workspace/reqman/.env`：

```bash
# 修改业务参数后重启服务
systemctl restart reqman
```

---

## 9. 验证清单

部署完成后逐项检查：

- [ ] systemd 服务运行中：`systemctl status reqman` 显示 `active (running)`
- [ ] 应用后端可达：`curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/` 返回 200
- [ ] 对外访问正常：浏览器打开 `http://8.137.15.167` 页面正常加载
- [ ] Nginx 配置语法：`nginx -t` 无报错
- [ ] 数据持久化：`systemctl restart reqman` 后数据不丢失
- [ ] 备份脚本正常：`bash scripts/db.sh backup` 生成 gzip 备份
- [ ] cron 自动备份已配置：`crontab -l | grep db.sh` 存在 `0 2 * * 6`
- [ ] 日志无异常：`journalctl -u reqman -n 50` 无 ERROR/TRACEBACK
