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
用户 → http://服务器IP:80 (Nginx)
          ↓ 反向代理
      http://127.0.0.1:5001 (Gunicorn 4w×2t)
          ↓
      Flask应用 → data/reqman_db.json
```

**技术栈：**
- 运行时：Python 3.11 + Gunicorn (4 workers × 2 threads)
- 反向代理：Nginx (80端口)
- 进程管理：systemd

---

## 2. 快速启动

### 首次部署（Workbench 终端执行）

```bash
cd /root/workspace/reqman
bash scripts/deploy.sh
```

### GitHub 仓库配置（首次需执行）

```bash
cd /root/workspace/reqman
git remote set-url origin https://github.com/ElissaMA/reqman.git
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

## 5. 代码更新与数据库同步

> **操作方式：** 服务器仅通过阿里云 Workbench 终端操作，不使用本地 SSH。

### 5.1 GitHub 仓库地址

- **仓库：** https://github.com/ElissaMA/reqman
- **服务器配置：** `git remote set-url origin https://github.com/ElissaMA/reqman.git`

### 5.2 代码更新流程

#### 本地开发 → 服务器更新

```bash
# === 本地操作 ===
# 1. 在 dev 分支开发
git checkout dev

# 2. 开发完成后合并到 main
git checkout main && git merge dev

# 3. 推送到 GitHub
git push origin main

# === Workbench 终端操作 ===
# 4. 服务器拉取最新代码
cd /root/workspace/reqman && git pull origin main

# 5. 重启服务
sudo systemctl restart reqman

# 6. 验证
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/
```

#### 仅重启服务（无代码变更时）

```bash
sudo systemctl restart reqman
```

### 5.3 数据库同步流程

#### 原则

1. **服务器是数据源：** 日常数据修改优先通过 Web 界面操作
2. **本地修改前拉取：** 批量修改数据库前，先从服务器下载最新版本
3. **更新服务器前备份：** 执行 `git pull` 前，先运行 `bash scripts/db.sh backup`
4. **避免双向修改：** 同一时间段内，只在一处修改数据库

#### 场景A：本地修改数据库后同步到服务器

```bash
# === 本地操作 ===
# 1. 先拉取服务器最新数据库
scp root@8.137.15.167:/root/workspace/reqman/data/reqman_db.json data/reqman_db.json

# 2. 本地修改数据库

# 3. 提交到 git
git add data/reqman_db.json && git commit -m "chore(db): 描述修改内容"
git push origin main

# === Workbench 终端操作 ===
# 4. 服务器拉取
cd /root/workspace/reqman && git pull origin main

# 5. 重启服务
sudo systemctl restart reqman
```

#### 场景B：服务器 Web 界面修改后同步到本地

```bash
# === 本地操作 ===
# 1. 从服务器拉取最新数据库
scp root@8.137.15.167:/root/workspace/reqman/data/reqman_db.json data/reqman_db.json

# 2. 提交到 git（如需保留版本历史）
git add data/reqman_db.json && git commit -m "chore(db): 同步服务器数据"
git push origin main
```

#### 场景C：更新服务器前的安全检查

```bash
# === Workbench 终端操作 ===
# 1. 备份当前数据库
cd /root/workspace/reqman && bash scripts/db.sh backup

# 2. 拉取最新代码
git pull origin main

# 3. 如有数据库冲突，查看差异
git diff data/reqman_db.json

# 4. 重启服务
sudo systemctl restart reqman
```

### 5.4 feature 分支操作提示

#### 本地 feature 分支工作流

```bash
# 1. 从 main 创建 feature 分支
git checkout main
git checkout -b feature/xxx

# 2. 开发完成后合并到 dev 测试
git checkout dev && git merge feature/xxx

# 3. 测试通过后合并到 main
git checkout main && git merge feature/xxx

# 4. 推送到 GitHub
git push origin main

# 5. 可选：清理 feature 分支
git branch -d feature/xxx
```

#### 注意事项

- **feature 分支不直接推送到服务器**，必须合并到 main 后才推送
- **合并前确保 dev 分支测试通过**
- **合并后切回 dev 继续开发**


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
└── pyproject.toml          # Python 依赖（唯一依赖源）
```

---

## 7. 验证清单

部署完成后，逐项验证：

- [ ] 服务运行中：`systemctl status reqman`
- [ ] 应用端口可达：`curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/`
- [ ] HTTP 响应码 2xx/3xx
- [ ] 数据持久化：重启后数据不丢失
- [ ] 备份脚本正常：`bash scripts/db.sh backup`
- [ ] cron 自动备份已配置：`crontab -l | grep db.sh`

---

## 8. 常见问题

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

## 9. 环境变量配置

编辑 `/root/workspace/reqman/.env`：

```bash
# 修改业务参数后重启服务
systemctl restart reqman
```
