# 定检需求单管理系统 — 服务器运维手册

> 部署架构：**Python 3.11 + venv + Gunicorn + systemd + Nginx**（Ubuntu 22.04 直接部署，无 Docker）
> 更新日期：2026-08-07

---

## 1. 系统概述

定检需求单管理系统用于飞机定检工卡管理：维护工卡/工卡组/飞机信息数据库，解析工卡工作清单（Excel），自动匹配工卡并生成需求单 Excel 文件。

**技术架构：**

```
浏览器
  │  HTTP :80
  ▼
Nginx（反向代理 + 安全头）
  │  转发 127.0.0.1:5001
  ▼
Gunicorn（4 workers × 2 threads，timeout 120s）
  │
  ▼
Flask 应用（src/reqman）
  │
  ▼
JSON 双文件存储：
  data/reqman_db.json        核心数据（工卡/工卡组/飞机）
  data/reqman_db_runtime.json 运行时数据（工作包/日志，自动生成）
```

- **服务器**：Ubuntu 22.04 x86_64，Python 3.11
- **部署目录**：`/root/workspace/reqman`
- **服务端口**：对外 80（Nginx），应用 5001（Gunicorn，仅本机访问）
- **进程管理**：systemd 服务 `reqman`（开机自启，崩溃自动重启）

---

## 2. 快速启动（一键部署）

**前置条件：**

- Ubuntu 22.04 服务器，具备 root 权限
- 可访问公网/内网 IP（可选绑定域名）

**一键部署：**

```bash
# 1. 从本地将项目（或 deploy_package）上传到服务器
scp -r deploy_package/* root@<服务器IP>:/root/workspace/reqman/
# 或 rsync 全量同步
rsync -av --delete --exclude='venv' --exclude='.git' --exclude='data/backups' \
  ./ root@<服务器IP>:/root/workspace/reqman/

# 2. 登录服务器执行部署
ssh root@<服务器IP>
cd /root/workspace/reqman
sudo bash scripts/deploy.sh
```

`scripts/deploy.sh` 自动完成以下步骤：

1. 检查/安装 Python 3.11、`python3.11-venv`、Nginx
2. 创建虚拟环境 `venv/` 并安装 `requirements.txt` + gunicorn
3. 自动生成 `.env`（含随机 `SECRET_KEY`）
4. 安装 systemd 服务 `config/reqman.service` → `reqman.service`
5. 配置 Nginx 站点 `config/nginx-reqman.conf` → `/etc/nginx/sites-available/reqman.conf`（80 端口反代 5001）
6. 启用服务并配置数据库自动备份 cron（每周六 02:00）

部署完成后浏览器访问 `http://<服务器IP>/` 即可使用。

---

## 3. 常用运维命令

### 3.1 服务管理（systemd）

```bash
systemctl status reqman        # 查看服务状态
systemctl start reqman         # 启动
systemctl stop reqman          # 停止
systemctl restart reqman       # 重启（更新代码后常用）
systemctl enable reqman        # 设置开机自启（deploy.sh 已配置）
systemctl is-active reqman     # 快速判断是否运行
```

### 3.2 日志查看

```bash
journalctl -u reqman -f            # 实时跟踪应用日志（访问+错误）
journalctl -u reqman -n 200        # 最近 200 行
journalctl -u reqman --since "1 hour ago"   # 最近 1 小时
tail -f /var/log/nginx/error.log   # Nginx 错误日志
tail -f /var/log/nginx/access.log  # Nginx 访问日志
```

### 3.3 Nginx 操作

```bash
nginx -t                       # 配置语法检查
systemctl reload nginx         # 平滑重载配置（不中断连接）
systemctl restart nginx        # 重启 Nginx
```

### 3.4 端口与进程检查

```bash
ss -lntp | grep -E ':(80|5001)'    # 查看 80/5001 监听
ps aux | grep gunicorn             # 查看 Gunicorn worker 进程
```

---

## 4. 数据库备份与恢复

统一使用 `scripts/db.sh` 管理（备份目录：`data/backups/`，gzip 压缩）：

```bash
cd /root/workspace/reqman

bash scripts/db.sh backup            # 备份：data/backups/reqman_db_时间戳.json.gz
bash scripts/db.sh list              # 列出所有备份
bash scripts/db.sh restore           # 恢复最近一次备份
bash scripts/db.sh restore <文件>    # 恢复指定备份文件
bash scripts/db.sh clean [天数]      # 清理过期备份（默认保留 28 天）
```

- **自动备份**：cron 每周六 02:00 执行 `db.sh backup`（查看：`crontab -l | grep db.sh`）
- **保留策略**：默认 28 天（4 周），备份时自动清理过期文件
- **安全恢复**：`db.sh restore` 执行前会把当前数据另存为 `data/reqman_db.json.pre_restore`，防止误恢复
- 恢复后需重启应用生效：`systemctl restart reqman`

---

## 5. 更新方式

### 5.1 代码更新

```bash
# 1. 本地执行：上传新代码（排除生产数据、依赖、配置）
rsync -av --delete \
  --exclude='venv' --exclude='.git' --exclude='__pycache__' \
  --exclude='data' --exclude='output' --exclude='.env' \
  ./ root@<服务器IP>:/root/workspace/reqman/

# 2. 服务器上执行：依赖有变化时更新（requirements.txt 变更后必须执行）
cd /root/workspace/reqman
./venv/bin/pip install -r requirements.txt

# 3. 重启应用
systemctl restart reqman
systemctl status reqman
```

> ⚠️ 上传时务必排除 `data/`、`output/`、`.env`、`venv/`，避免覆盖服务器生产数据。
> 最小化更新可只上传变更目录：`src/`、`assets/`、`scripts/`、`config/`、`requirements.txt`。

### 5.2 Nginx 配置更新（config/nginx-reqman.conf 有变化时）

```bash
cp config/nginx-reqman.conf /etc/nginx/sites-available/reqman.conf
nginx -t && systemctl reload nginx
```

### 5.3 systemd 服务更新（config/reqman.service 有变化时）

```bash
cp config/reqman.service /etc/systemd/system/reqman.service
systemctl daemon-reload
systemctl restart reqman
```

### 5.4 脚本更新

```bash
chmod +x scripts/*.sh   # 确保脚本可执行权限
```

### 5.5 回滚

```bash
# 代码回滚：上传旧版本代码后重启
systemctl restart reqman

# 数据回滚：恢复到指定备份
bash scripts/db.sh list
bash scripts/db.sh restore data/backups/reqman_db_20260801_120000.json.gz
systemctl restart reqman
```

---

## 6. 常见问题（故障排查）

| 现象 | 排查与处理 |
|------|-----------|
| 页面无法访问，80 端口无监听 | `systemctl status nginx`；`nginx -t`；`ss -lntp \| grep :80` |
| 502 Bad Gateway | 应用未启动：`systemctl status reqman`；`journalctl -u reqman -n 50` 查日志；`systemctl restart reqman` |
| 页面 500 错误 | `journalctl -u reqman -n 100` 查看异常堆栈 |
| 上传 Excel 失败 | Nginx 限制 20M：`client_max_body_size 20M`；检查磁盘空间 `df -h` |
| 应用响应慢/卡死 | `ps aux \| grep gunicorn` 确认 4 个 worker 存活；`top` 查看 CPU/内存 |
| 数据库疑似损坏 | `bash scripts/db.sh list` → `bash scripts/db.sh restore` 恢复最近备份 |
| 自动备份未执行 | `crontab -l \| grep db.sh` 确认定时任务；手动运行 `bash scripts/db.sh backup` 测试 |
| 端口 5001 被占用 | `ss -lntp \| grep 5001` 找出占用进程，处理后 `systemctl restart reqman` |
| 修改 Nginx 配置不生效 | 确认执行 `nginx -t` 通过后 `systemctl reload nginx` |

---

## 7. 目录结构

```
/root/workspace/reqman/
├── src/reqman/            # Flask 应用源代码（蓝图、服务、模板、静态资源）
├── assets/                # 模板/静态资源
├── data/
│   ├── reqman_db.json     # 核心数据库（工卡/工卡组/飞机信息）
│   ├── reqman_db_runtime.json   # 运行时数据（工作包/日志，自动生成）
│   └── backups/           # 数据库备份（gzip，db.sh 生成）
├── config/
│   ├── reqman.service     # systemd 服务单元
│   └── nginx-reqman.conf  # Nginx 站点配置
├── scripts/
│   ├── deploy.sh          # 一键部署脚本
│   └── db.sh              # 数据库备份/恢复/清理脚本
├── venv/                  # Python 3.11 虚拟环境
├── requirements.txt       # Python 依赖
├── pyproject.toml         # 项目配置
└── .env                   # 环境变量（deploy.sh 自动生成，勿手动修改 SECRET_KEY）
```
