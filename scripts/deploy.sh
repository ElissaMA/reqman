#!/usr/bin/env bash
#
 # ReqMan定检准备系统 — 一键部署脚本（Python 直接部署）
# 用法: sudo bash scripts/deploy.sh
#
# 部署目标: /root/workspace/reqman
# 系统要求: Ubuntu 22.04 LTS, Python 3.11
#
set -euo pipefail

APP_NAME="reqman"
DEPLOY_DIR="/root/workspace/reqman"
SERVICE_NAME="reqman"
PYTHON_BIN="python3.11"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*"; exit 1; }

# 必须以 root 运行（systemd/nginx 需要）
if [ "$(id -u)" -ne 0 ]; then
    die "请以 root 权限运行: sudo bash scripts/deploy.sh"
fi

log "=========================================="
log "  ReqMan定检准备系统 — 部署开始"
log "=========================================="

# ---------- 1. 检查 Python 3.11 ----------
log "[1/10] 检查 Python 3.11..."
if command -v "$PYTHON_BIN" > /dev/null 2>&1; then
    log "  Python 3.11 已安装: $($PYTHON_BIN --version)"
else
    die "未找到 python3.11，请先安装: sudo apt install python3.11"
fi

# ---------- 2. 安装系统依赖 ----------
log "[2/10] 安装系统依赖（python3.11-venv, nginx）..."
apt-get update -qq
apt-get install -y -qq python3.11-venv python3.11-dev nginx lsof

# ---------- 3. 创建部署目录 ----------
log "[3/10] 创建部署目录..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

mkdir -p "$DEPLOY_DIR"
# 如果当前目录不是部署目录，则复制项目文件
if [ "$PROJECT_DIR" != "$DEPLOY_DIR" ]; then
    log "  复制项目文件到 $DEPLOY_DIR ..."
    rsync -a --exclude='venv' --exclude='.git' --exclude='__pycache__' \
        "$PROJECT_DIR/" "$DEPLOY_DIR/"
else
    log "  已在部署目录中，跳过复制"
fi

cd "$DEPLOY_DIR"
mkdir -p data output

# ---------- 4. 创建虚拟环境 ----------
log "[4/10] 创建虚拟环境..."
if [ ! -d "venv" ]; then
    "$PYTHON_BIN" -m venv venv
    log "  venv 已创建"
else
    log "  venv 已存在"
fi

# ---------- 5. 安装 Python 依赖 ----------
log "[5/10] 安装 Python 依赖..."
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -e . -q
./venv/bin/pip install gunicorn -q
log "  依赖安装完成"

# ---------- 6. 生成 .env 配置文件 ----------
log "[6/10] 生成 .env 配置文件..."
if [ ! -f ".env" ]; then
    SECRET=$(openssl rand -hex 32 2>/dev/null || "$PYTHON_BIN" -c "import secrets; print(secrets.token_hex(32))")
    cat > ".env" << EOF
# 服务基础配置
FLASK_APP=reqman.app:create_app
FLASK_ENV=production
SERVER_HOST=0.0.0.0
SERVER_PORT=5001
SECRET_KEY=${SECRET}

# 文件路径配置
DB_FILE=./data/reqman_db.json
TEMPLATE_FILE=./assets/demand_template.xlsx
OUTPUT_DIR=./output

# 业务枚举配置
CATEGORIES=发动机,机体,电子,特检,支援
TASK_TYPES=A,EO分段,DP项目,20MO,24MO

# 数据库后端
DB_BACKEND=json

# AMRO 库存查询（默认值已在代码内，留空即用默认）
# AMRO_API_URL=
# AMRO_SESSION_TTL=7200
# AMRO_PUBLIC_URL=http://8.137.15.167

# 域名配置（获取证书后配置 HTTPS）
DOMAIN_NAME=localhost
EOF
    chmod 600 .env
    log "  .env 已生成"
else
    log "  .env 已存在，跳过"
fi

# ---------- 7. 配置 systemd 服务 ----------
log "[7/10] 配置 systemd 服务..."
SERVICE_SRC="${DEPLOY_DIR}/config/reqman.service"
if [ -f "$SERVICE_SRC" ]; then
    # 替换为实际部署路径
    sed "s|/root/workspace/reqman|${DEPLOY_DIR}|g" "$SERVICE_SRC" > /etc/systemd/system/${SERVICE_NAME}.service
    systemctl daemon-reload
    log "  systemd 服务文件已安装: /etc/systemd/system/${SERVICE_NAME}.service"
else
    die "未找到 ${SERVICE_SRC}"
fi

# ---------- 8. 配置 Nginx 站点 ----------
log "[8/10] 配置 Nginx 站点..."
NGINX_SRC="${DEPLOY_DIR}/config/nginx-reqman.conf"
if [ -f "$NGINX_SRC" ]; then
    cp "$NGINX_SRC" /etc/nginx/sites-available/reqman.conf
    # 启用站点（如未启用）
    if [ ! -L "/etc/nginx/sites-enabled/reqman.conf" ]; then
        ln -sf /etc/nginx/sites-available/reqman.conf /etc/nginx/sites-enabled/reqman.conf
    fi
    # 禁用默认站点
    rm -f /etc/nginx/sites-enabled/default
    nginx -t 2>/dev/null && log "  Nginx 配置测试通过" || log "  [警告] Nginx 配置测试失败"
else
    die "未找到 ${NGINX_SRC}"
fi

# ---------- 9. 启动服务 ----------
log "[9/10] 启动服务..."
systemctl enable --now ${SERVICE_NAME}
systemctl enable --now nginx
systemctl restart ${SERVICE_NAME}
systemctl reload nginx
log "  服务已启动: systemctl status ${SERVICE_NAME}"

# ---------- 10. 配置备份 cron ----------
log "[10/10] 配置定时备份（每周六凌晨2点）..."
CRON_LINE="0 2 * * 6 ${DEPLOY_DIR}/scripts/db.sh backup >> /var/log/reqman/backup.log 2>&1"
mkdir -p /var/log/reqman
(crontab -l 2>/dev/null | grep -v "db.sh backup"; echo "$CRON_LINE") | crontab -
log "  cron 已配置: 0 2 * * 6"

log ""
log "=========================================="
log "  部署完成！"
log "  部署目录: ${DEPLOY_DIR}"
log "  应用地址: http://localhost:5001"
log "  Nginx地址: http://<服务器IP> (80端口)"
log "  服务状态: systemctl status reqman"
log "  查看日志: journalctl -u reqman -f"
log "=========================================="
