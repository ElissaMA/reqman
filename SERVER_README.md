# ReqMan定检准备系统 — 服务器运维手册

> 版本：V3.6.0 | 目标环境：Ubuntu 22.04 LTS (阿里云)

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
      http://127.0.0.1:5001 (Gunicorn 1w×4t)
          ↓
      Flask应用 → data/reqman_db.json
```

**技术栈：**
- 运行时：Python 3.11 + Gunicorn (1 worker × 4 threads，单进程模型——JSON 存储锁为进程内锁)
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

## 5. 代码更新与数据同步

> **操作方式：** 服务器仅通过阿里云 Workbench 终端操作，不使用本地 SSH。

通用流程：**本地 dev 开发提交 → 验证 → 合并本地 main 试用 → 试用通过推送 GitHub main** → 服务器拉取 → 重启

### GitHub 仓库地址

- **仓库：** https://github.com/ElissaMA/reqman
- **服务器配置：** `git remote set-url origin https://github.com/ElissaMA/reqman.git`

### 5.1 本地操作（开发与发布）

```bash
# 1. 所有改动在 dev 分支进行（小步提交）
git checkout dev
# ……修改代码、pytest 全量 + ruff 验证……

# 2. 验证通过后合并进本地 main 试用（本地启动实际使用）
git checkout main && git merge dev

# 3. 试用通过后推送 main（feature 分支流程已废除；dev 仅本地不推送）
git push origin main

# 4. 数据同步不走分支：按需 scp data/ 双文件（见 5.2 第 4 步）
```

### 5.2 服务器操作（拉取最新代码并同步数据）

```bash
cd /root/workspace/reqman

# 1. 拉取最新代码
git pull origin main

# 2. 仓库改过 config/reqman.service 时，刷新 systemd 单元（单元文件不随 pull 更新！）
cp config/reqman.service /etc/systemd/system/reqman.service && systemctl daemon-reload

# 3. 更新依赖（引入新依赖时执行，幂等安全）
./venv/bin/pip install -e .

# 4. 重启服务
sudo systemctl restart reqman

# 5. 上传最新数据（从本地 scp 上传双文件）
#    本地执行：scp data/reqman_db.json data/reqman_db_runtime.json root@8.137.15.167:/root/workspace/reqman/data/

# 6. 验证
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/
```

### 5.3 数据备份

> 自动备份已配置为每天 0:00 执行（cron: `0 0 * * *`），保留 7 天。

```bash
# 手动备份
bash scripts/db.sh backup

# 查看所有备份
bash scripts/db.sh list

# 恢复最近一次备份
bash scripts/db.sh restore

# 恢复指定备份
bash scripts/db.sh restore data/backups/reqman_db_20260820_120000.json.gz
```

### 5.4 分支工作流（dev → 本地 main 试用 → 推送 main）

```bash
# 1. 所有改动在 dev 进行（feature 分支流程已废除）
git checkout dev
# ……开发 → pytest 全量 + ruff → 提交……

# 2. 验证通过 → 合并本地 main 试用（本地启动实际使用验证）
git checkout main && git merge dev

# 3. 试用通过 → 推送 main → 服务器按 5.2 拉取部署
git push origin main

# 4. 回到 dev 继续开发（落后 main 时先 git merge main 同步）
git checkout dev && git merge main
```

> 注意：dev 分支仅本地存在、不推送；只有 main 发布到 GitHub。合并 main 前必须完成全量测试；数据文件（data/）不入分支，始终按 5.2 第 5 步 scp 同步。


---

## 6. 目录结构

```
/root/workspace/reqman/
├── src/reqman/             # 应用源代码
├── assets/                 # 需求单 / 提醒单 Excel 模板
│   ├── demand_template.xlsx
│   └── reminder_template.xlsx
├── data/                   # 数据库与运行数据
│   ├── reqman_db.json      # 核心数据
│   ├── reqman_db_runtime.json  # 运行时数据
│   ├── cancelled_cards.json # 作废工卡库（独立存储，降主库体积）
│   ├── cookie/             # AMRO 登录凭证（amro_cookies.json，运行时生成）
│   ├── amro_audit.jsonl    # AMRO 只读调用审计留痕
│   └── backups/            # 数据库备份
├── output/                 # 生成的需求单 Excel
├── config/                 # 部署配置
│   ├── reqman.service      # systemd 服务
│   └── nginx-reqman.conf   # Nginx 站点配置
├── scripts/                # 运维脚本 + 登录脚本
│   ├── deploy.sh           # 一键部署
│   ├── db.sh               # 数据库管理
│   ├── amro_login.py       # AMRO 登录脚本（本地参考副本，服务器动态下发模板）
│   ├── start_login.bat     # 一键登录启动脚本（本地参考副本）
│   └── import_vba_config.py # 旧版 VBA 提醒配置迁移
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
- [ ] cron 自动备份已配置：`crontab -l | grep auto_backup`

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

### 提醒单相关环境变量（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REMINDER_TEMPLATE_FILE` | `assets/reminder_template.xlsx` | 提醒单 Excel 模板路径 |
| `REMINDER_TYPES` | `一般提醒,重点提醒` | 提醒类型选项（逗号分隔） |

### AMRO 相关环境变量（可选）

> 接口基座 `AMRO_API_BASE`（`https://me.sichuanair.com/api/v1/plugins`）硬编码于 `src/reqman/services/connectors/amro.py`，不在环境变量配置；以下为可调项。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AMRO_COOKIE_FILE` | `data/cookie/amro_cookies.json` | 登录凭证临时缓存文件路径 |
| `AMRO_MAX_CONCURRENT` | `10` | 库存查询最大并发数 |
| `AMRO_SESSION_TTL` | `7200` | 登录凭证有效时长（秒），默认 2 小时 |
| `AMRO_LOGIN_VERSION` | `3` | 登录脚本版本号（`check-config` 门禁标记旧脚本） |
| `AMRO_PUBLIC_URL` | 空 | 登录脚本 ZIP 注入的公网地址，如 `http://8.137.15.167`；服务器部署建议配置，保证多用户下载的 ZIP 注入地址一致可达；未配置回退当前访问地址 |
| `AMRO_RATE_SECONDS` | `1` | 两次 AMRO 请求最小间隔（秒，限速保护） |
| `AMRO_AUDIT_FILE` | `data/amro_audit.jsonl` | 只读调用审计留痕（JSONL） |
| `AMRO_AC_FLEET` | `A320` | 飞机同步机族过滤（在册判定） |
| `AMRO_BASE_DEFAULT` | `KM01` | 工作包默认基地代码（昆明） |
| `AMRO_CARD_FLEET` | `A320` | 工卡版本清单机队筛选 |

### 库存查询运维使用说明

**服务器端用户操作流程：**

1. 登录系统打开「库存查询」页
2. 点击「🛠 新建配置」下载配置包（ZIP）
3. 在本机解压配置包，双击 `start_login.bat`（首次自动安装运行环境，国内高速源）
4. 按提示关闭已登录的川航 AMRO 页面并确认，浏览器弹出 AMRO 登录页；先在浏览器中接收并输入手机验证码，再完成账号登录，登录成功后点击页面「✅ 完成登录」按钮或回到脚本窗口按回车，脚本自动上传凭证
5. 登录脚本自动上传登录凭证到服务器，页面状态变为"登录有效"后即可查询
6. 上传需求单 Excel → 开始查询 → 在结果栏点击「下载副本」保存输出文件

**注意事项：**

- 服务器无 GUI 弹浏览器，登录必须在用户本机完成；登录凭证由本机脚本自动上传，服务器不直接持有登录密码
- 登录凭证一次性、临时缓存 2 小时（`AMRO_SESSION_TTL` 可调），过期后需重新运行登录脚本
- 输出文件暂存服务器 `output/` 目录（gitignore 已忽略），用户通过页面「下载副本」获取；上传新需求单查询时自动清除旧的 `*_库存已填_*.xlsx` 暂存
