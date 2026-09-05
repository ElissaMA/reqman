# ReqMan 定检准备系统 — 服务器运维手册

> V3.6.0 | 目标环境：Ubuntu 22.04 LTS（阿里云）| 公网 80 端口

## 架构与优势

- **稳定单进程**：Gunicorn 1 worker × 4 threads，JSON 存储用进程内锁，无多进程竞态。
- **反向代理**：Nginx 80 → 127.0.0.1:5001；systemd 托管，开机自启。
- **数据安全**：核心 / 运行时双文件分层；每日自动备份（保留 7 天）；AMRO 调用全程审计留痕。
- **只读合规**：对接川航 AMRO 仅读不写，限速 + JSONL 审计，无绕过开关。

```
用户 → Nginx:80 → Gunicorn:5001 → Flask → data/reqman_db.json
```

## 快速部署

```bash
cd /root/workspace/reqman
bash scripts/deploy.sh
git remote set-url origin https://github.com/ElissaMA/reqman.git   # 首次需执行
```

访问 http://8.137.15.167

## 日常运维

**服务管理**

```bash
systemctl start|stop|restart|status|enable reqman
```

**日志查看**

```bash
journalctl -u reqman -f        # 实时
journalctl -u reqman -n 100    # 最近 100 行
journalctl -u reqman --since today
```

**Nginx**

```bash
systemctl restart nginx
nginx -t                      # 测试配置语法
```

**备份 / 恢复**

```bash
bash scripts/db.sh backup            # 备份（gzip）
bash scripts/db.sh restore           # 恢复最近一次
bash scripts/db.sh restore <文件>     # 恢复指定
bash scripts/db.sh list              # 列出全部
bash scripts/db.sh clean 28          # 清理 >28 天
```

> 自动备份：每周六 02:00 全量、每日 00:00 增量（保留 7 天）。

## 代码更新与数据同步

流程：**本地 dev 开发 → 测试 → 合并本地 main 试用 → 推送 GitHub main → 服务器拉取 → 重启**；数据文件走 scp（不入分支）。

**服务器更新**

```bash
cd /root/workspace/reqman
git pull origin main
cp config/reqman.service /etc/systemd/system/reqman.service && systemctl daemon-reload  # 改过单元时
./venv/bin/pip install -e .     # 有新依赖时（幂等）
sudo systemctl restart reqman
# 本地 scp 上传数据：
# scp data/reqman_db.json data/reqman_db_runtime.json root@8.137.15.167:/root/workspace/reqman/data/
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/   # 验证
```

> dev 分支仅本地不推送；只有 main 发布到 GitHub。合并 main 前须完成全量测试；数据文件始终按 scp 同步。

## 目录结构（要点）

```
src/reqman/           应用源码
assets/              需求单 / 提醒单 Excel 模板
data/                reqman_db.json(核心) · reqman_db_runtime.json(运行时) · cancelled_cards.json · cookie/ · amro_audit.jsonl · backups/
output/             生成的需求单 / 改版清单
config/             reqman.service · nginx-reqman.conf
scripts/            deploy.sh · db.sh · amro_login.py · start_login.bat · import_vba_config.py
.env                环境变量
```

## 环境变量（可调，改后重启）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AMRO_SESSION_TTL` | 0 | 已废弃：登录凭证长期有效，实际可用性由 AMRO 只读探活决定 |
| `AMRO_RATE_SECONDS` | 1 | AMRO 请求最小间隔（限速保护） |
| `AMRO_CARD_FLEET` | A320 | 工卡版本机队筛选 |
| `AMRO_AC_FLEET` | A320 | 飞机同步机队过滤 |
| `AMRO_BASE_DEFAULT` | KM01 | 工作包默认基地（昆明） |
| `AMRO_MAX_CONCURRENT` | 10 | 库存查询最大并发 |
| `AMRO_PUBLIC_URL` | 空 | 登录 ZIP 注入公网地址（建议配服务器 IP） |
| `AMRO_COOKIE_FILE` | data/cookie/amro_cookies.json | 登录凭证缓存路径 |
| `AMRO_AUDIT_FILE` | data/amro_audit.jsonl | 只读调用审计路径 |

> 接口基座 `AMRO_API_BASE` 硬编码于 `src/reqman/services/connectors/amro.py`，不在环境变量。

## 库存查询运维注意

- 服务器无 GUI，AMRO 登录必须由用户在本机完成；凭证由本机脚本上传，服务器不持有密码。
- 登录脚本（v4）在浏览器完成登录后自动读取账号、探活并上传，无需人工点击按钮或窗口回车；上传接口要求携带账号，Cookie 长期有效但实际可用性以 AMRO 探活为准（明确失效会清缓存，网络异常不误判）。
- `data/cookie/` 存放明文会话 Cookie，属敏感文件，禁止纳入代码包或上传；`/inventory/login/upload` 当前无鉴权，公网部署应配合 HTTPS 与访问控制。
- **上传大小上限 16 MB**：应用层 `MAX_CONTENT_LENGTH`（config.py）已强制，超出返回 413；Nginx `client_max_body_size` 须 ≥16MB，否则 413 早于应用触发，表现为「上传失败」。
- **生产严禁 `FLASK_DEBUG=1`**：Werkzeug 交互式调试器存在 RCE 风险且错误页外泄完整堆栈；`config.DEBUG` 默认关闭，部署仅经 systemd + Gunicorn 运行，绝不显式开启调试。
- 输出暂存 `output/`，用户经页面「下载副本」获取；新查询自动清理旧 `*_库存已填_*.xlsx` 暂存。

## 常见问题

- **端口占用**：`lsof -i :80` / `:5001` → `kill -9 <PID>`。
- **启动慢 / 超时**：`ps aux | grep gunicorn` → `systemctl restart reqman`。
- **库损坏**：`bash scripts/db.sh restore`。
- **上传失败**：查 `config/nginx-reqman.conf` 的 `client_max_body_size` 与磁盘 `df -h`。
- **磁盘不足**：`bash scripts/db.sh clean 14`。

## 验证清单

- [ ] `systemctl status reqman` 运行中
- [ ] `curl ... localhost:5001/` 返回 2xx/3xx
- [ ] 重启后数据不丢失
- [ ] `bash scripts/db.sh backup` 成功
- [ ] `crontab -l | grep auto_backup` 自动备份已配置
