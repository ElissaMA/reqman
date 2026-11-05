# ReqMan 定检准备系统 — 服务器运维手册

> V3.7.1 | 目标环境：Ubuntu 22.04 LTS（阿里云）| 公网 80 端口

## 架构与优势

- **稳定单进程**：Gunicorn 1 worker × 4 threads，JSON 存储用进程内锁；`data/reqman_db.json.lock` 实例锁拒绝第二个进程启动，防多进程并发写丢数据（误配多 worker / 双开服务会被明确拦下）。
- **反向代理**：Nginx 80 → 127.0.0.1:5001；systemd 托管，开机自启。
- **数据安全**：核心 / 运行时双文件分层；每日自动备份（保留 7 天）；AMRO 调用全程审计留痕。
- **只读合规**：对接川航 AMRO 仅读不写，限速 + JSONL 审计，无绕过开关。工作包导入（AMRO/Excel）只保存原始工卡行，匹配与派生统计仅在点击「重新匹配」时执行；预览与下载要求已匹配。导入时即校验并标注每张工卡的 `CONDITION`，详情缺状态则拒绝导入并保留原数据；按详情 `PPCBZSM` 备注含“撤销”及 `CONDITION=D/CX` 识别撤销，`BM_CONDITION` 字典给出 `D/CX=撤销`、`N/XZ=新增`，`REVST/PGZT` 不用于工卡撤销判定。

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
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/   # 验证
# 本地 scp 上传数据：
# scp data/reqman_db.json data/reqman_db_runtime.json root@8.137.15.167:/root/workspace/reqman/data/
```

> dev 分支仅本地不推送；只有 main 发布到 GitHub。合并 main 前须完成全量测试；数据文件始终按 scp 同步。

**升级到 V3.7（作废工卡并入主库）一次性迁移**

旧版独立的 `data/cancelled_cards.json` 已并入主库（作废 = 主库 `cancelled` 标记）。服务器首次升级到 V3.7+ 时，**停服后**用 venv 解释器跑迁移（幂等，可重复执行；同号同名自动合并、不同名跳过并报告）：

```bash
systemctl stop reqman
./venv/bin/python3 scripts/migrate_cancelled_cards.py --dry-run   # 先看数量
./venv/bin/python3 scripts/migrate_cancelled_cards.py            # 执行并归档原文件
systemctl start reqman
```

> 也可跳过服务器迁移：用本地已迁移好的 `reqman_db.json` 直接 scp 覆盖（见上），再把服务器旧 `cancelled_cards.json` 改名留档即可。二选一，不要都做。

## 目录结构（要点）

```
src/reqman/           应用源码
assets/              需求单 / 提醒单 Excel 模板
data/                reqman_db.json(核心，含作废标记) · reqman_db_runtime.json(运行时) · reqman_db.json.lock(实例锁) · cookie/ · amro_audit.jsonl · backups/
output/             生成的需求单 / 改版清单
config/             reqman.service · nginx-reqman.conf
scripts/            deploy.sh · db.sh · migrate_cancelled_cards.py · amro_login.py · start_login.bat · import_vba_config.py
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
| `AMRO_PUBLIC_URL` | 空 | 登录 ZIP 注入的服务器地址。**当前部署已在 `config/reqman.service` 固定为 `http://8.137.15.167`**——配置后 Host 头被改写也不会把凭证导向错误主机；未配置时回退当前访问 Host |
| `AMRO_ALLOWED_HOSTS` | 空 | 允许注入登录脚本的访问域名（逗号分隔）。**留空即信任当前 Host**（内网/反代场景，默认不阻断）；已配 `AMRO_PUBLIC_URL` 时本项不参与判定 |
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
- **启动报"数据库已被进程 X 使用"**：实例锁检测到另一存活进程持有 `data/reqman_db.json.lock`。确认无第二实例后删除该锁文件重启；排查命令 `./venv/bin/python3 -m reqman.utils.instance_lock data/reqman_db.json`。
- **启动慢 / 超时**：`ps aux | grep gunicorn` → `systemctl restart reqman`。
- **库损坏**：`bash scripts/db.sh restore`。
- **上传失败**：查 `config/nginx-reqman.conf` 的 `client_max_body_size` 与磁盘 `df -h`。
- **AMRO 请求返回 403（网关拦截）**：AMRO 网关按 User-Agent 拦截非浏览器指纹，代码已统一使用 `ReqMan/3.7.1 (AMRO read-only)`（`connectors/amro.py` 的 `AMRO_USER_AGENT`）。若仍 403，说明该主机网络出口不可达 AMRO，需确认公司网络/VPN；排查 `python scripts/amro_diag.py`（只读，打印 DNS/TLS/带与不带 UA 的探活结果）。服务器与用户本机对该策略的差异只在网络出口，与登录配置无关。
- **登录配置包版本过旧**：登录脚本 `LOGIN_VERSION` 与 `AMRO_LOGIN_VERSION`（默认 5）不一致时 `check-config` 会拒绝，重新下载配置包即可。
- **登录脚本报 `All connection attempts failed`**：脚本上传凭证时连不上 ReqMan 服务器（httpx 异步客户端连 `127.0.0.1:5001` 的典型报错），即上传地址被回退成本机地址。常见原因：① 换服务器或重新下载配置包后**没重跑 `register_protocol.bat`**，`ReqManLogin://` 仍指向旧配置包目录；② 双击 `start_login.bat` 时配置包内 `UPLOAD_URL` 未注入正确地址。处理：从当前 ReqMan 页面重下配置包 → 解压 → **运行 `register_protocol.bat`（会覆盖旧指向）** → 再点「登录 AMRO」。脚本窗口会打印 `[目标服务器] <地址>` 与 `[上传凭证] <URL>`，据此确认。
- **一键协议指向旧目录**：注册表 `HKCU\Software\Classes\ReqManLogin\shell\open\command` 记录某个 `start_login.bat` 的绝对路径；每换一次配置包目录都需重跑 `register_protocol.bat`。
- **磁盘不足**：`bash scripts/db.sh clean 14`。

## 验证清单

- [ ] `systemctl status reqman` 运行中
- [ ] `curl ... localhost:5001/` 返回 2xx/3xx
- [ ] 重启后数据不丢失
- [ ] 「作废工卡」页可见历史作废记录（升级 V3.7 后验证迁移生效）
- [ ] `bash scripts/db.sh backup` 成功
- [ ] `crontab -l | grep auto_backup` 自动备份已配置
