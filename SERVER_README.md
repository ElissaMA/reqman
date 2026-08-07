# 定检需求单管理系统 — 服务器运维手册

> 版本：V3.2.2 | 目标环境：Ubuntu 22.04 LTS (阿里云)

---

## 1. 系统概述

- **运行架构**：Python 3.11 + Gunicorn + Nginx（systemd 管理）
- **对外访问端口**：**80**
- **部署目录**：`/root/workspace/reqman`
- **服务器IP**：8.137.15.167

---

## 2. 快速启动

```bash
# 一键部署（首次）
cd deploy_package
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

### 方式一：通过 deploy_package 更新（推荐）

```bash
# 1. 本地更新 deploy_package/ 内的源码文件
# 2. 上传到服务器
scp -r deploy_package/src/ root@8.137.15.167:/root/workspace/reqman/
# 3. 重启服务
ssh root@8.137.15.167 "systemctl restart reqman"
```

### 方式二：SSH 直接更新

```bash
ssh root@8.137.15.167
cd /root/workspace/reqman
# 编辑代码后重启
systemctl restart reqman
```

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
