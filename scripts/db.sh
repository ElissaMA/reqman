#!/usr/bin/env bash
#
# ReqMan定检准备系统 — 数据库管理脚本
# 用法:
#   bash scripts/db.sh backup              # 备份数据库（gzip 压缩）
#   bash scripts/db.sh restore             # 恢复最近一次备份
#   bash scripts/db.sh restore <文件>      # 恢复指定备份
#   bash scripts/db.sh list                # 列出所有备份
#   bash scripts/db.sh clean [天数]        # 清理过期备份（默认28天）
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/data/backups"
DB_FILE="${PROJECT_DIR}/data/reqman_db.json"
RT_FILE="${PROJECT_DIR}/data/reqman_db_runtime.json"  # 运行时文件（计数器/索引/工作包）
KEEP_DAYS=28  # 默认保留4周

# ---------- 辅助函数 ----------
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die()  { log "ERROR: $*"; exit 1; }

ensure_dirs() { mkdir -p "$BACKUP_DIR"; }

# ---------- backup ----------
do_backup() {
    ensure_dirs
    [ -f "$DB_FILE" ] || die "数据库文件不存在: $DB_FILE"

    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="${BACKUP_DIR}/reqman_db_${TIMESTAMP}.json.gz"

    gzip -c "$DB_FILE" > "$BACKUP_FILE"
    if [ -f "$RT_FILE" ]; then
        gzip -c "$RT_FILE" > "${BACKUP_DIR}/reqman_db_runtime_${TIMESTAMP}.json.gz"
        log "运行时文件已备份: ${BACKUP_DIR}/reqman_db_runtime_${TIMESTAMP}.json.gz"
    fi
    FILE_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "备份完成: ${BACKUP_FILE} (${FILE_SIZE})"

    # 自动清理过期备份
    do_clean "$KEEP_DAYS"
}

# ---------- restore ----------
do_restore() {
    local RESTORE_FILE=""

    if [ -n "${1:-}" ]; then
        RESTORE_FILE="$1"
    else
        RESTORE_FILE=$(ls -t "${BACKUP_DIR}"/reqman_db_*.json.gz 2>/dev/null | head -1)
    fi

    [ -z "$RESTORE_FILE" ] && die "未找到备份文件，请先运行: bash scripts/db.sh backup"
    [ -f "$RESTORE_FILE" ] || die "文件不存在: $RESTORE_FILE"

    log "恢复文件: $RESTORE_FILE"

    # 安全备份当前数据（含运行时文件）
    if [ -f "$DB_FILE" ]; then
        SAFETY="${DB_FILE}.pre_restore"
        cp "$DB_FILE" "$SAFETY"
        log "当前数据已备份: ${SAFETY}"
    fi
    if [ -f "$RT_FILE" ]; then
        cp "$RT_FILE" "${RT_FILE}.pre_restore"
        log "当前运行时文件已备份: ${RT_FILE}.pre_restore"
    fi

    # 恢复（支持 .gz 和非 .gz）
    if [[ "$RESTORE_FILE" == *.gz ]]; then
        gzip -dc "$RESTORE_FILE" > "$DB_FILE"
    else
        cp "$RESTORE_FILE" "$DB_FILE"
    fi

    # 按同名时间戳配对恢复运行时文件；缺失则跳过（计数器/索引可自愈，工作包以恢复后现状为准）
    local RT_RESTORE=""
    local base
    base=$(basename "$RESTORE_FILE")
    if [[ "$base" == reqman_db_*.json.gz ]]; then
        local candidate="${BACKUP_DIR}/reqman_db_runtime_${base#reqman_db_}"
        [ -f "$candidate" ] && RT_RESTORE="$candidate"
    fi
    if [ -n "$RT_RESTORE" ]; then
        gzip -dc "$RT_RESTORE" > "$RT_FILE"
        log "运行时文件已恢复: $RT_RESTORE"
    else
        log "警告: 未找到配对的运行时文件备份，next_id/code_index 将在应用启动时自愈"
    fi

    log "数据恢复完成"
}

# ---------- list ----------
do_list() {
    ensure_dirs
    local count=0

    echo "备份列表（${BACKUP_DIR}）:"
    echo "----------------------------------------------"
    for f in $(ls -t "${BACKUP_DIR}"/reqman_db_*.json.gz 2>/dev/null); do
        local size
        size=$(du -h "$f" | cut -f1)
        local date
        date=$(stat -c '%y' "$f" 2>/dev/null || stat -f '%Sm' "$f" 2>/dev/null || echo "unknown")
        local base
        base=$(basename "$f")
        echo "  ${base}  (${size})  ${date}"
        count=$((count + 1))
    done

    # 也列出未压缩的备份（兼容旧格式）
    for f in $(ls -t "${BACKUP_DIR}"/reqman_db_*.json 2>/dev/null); do
        local size
        size=$(du -h "$f" | cut -f1)
        local date
        date=$(stat -c '%y' "$f" 2>/dev/null || stat -f '%Sm' "$f" 2>/dev/null || echo "unknown")
        local base
        base=$(basename "$f")
        echo "  ${base}  (${size})  ${date}  [未压缩]"
        count=$((count + 1))
    done

    echo "----------------------------------------------"
    echo "共 ${count} 个备份"
}

# ---------- clean ----------
do_clean() {
    local days="${1:-$KEEP_DAYS}"
    ensure_dirs

    local deleted=0

    # 清理 .gz 备份
    while IFS= read -r old_file; do
        rm -f "$old_file"
        deleted=$((deleted + 1))
    done < <(find "$BACKUP_DIR" -name "reqman_db_*.json.gz" -mtime +"$days" -type f 2>/dev/null)

    # 同时清理旧格式未压缩备份
    while IFS= read -r old_file; do
        rm -f "$old_file"
        deleted=$((deleted + 1))
    done < <(find "$BACKUP_DIR" -name "reqman_db_*.json" -mtime +"$days" -type f 2>/dev/null)

    if [ "$deleted" -gt 0 ]; then
        log "已清理 ${deleted} 个超过 ${days} 天的备份"
    fi
}

# ---------- 入口 ----------
CMD="${1:-}"
shift 2>/dev/null || true

case "$CMD" in
    backup)  do_backup ;;
    restore) do_restore "$@" ;;
    list)    do_list ;;
    clean)   do_clean "$@" ;;
    *)
        echo "用法: bash scripts/db.sh <子命令>"
        echo ""
        echo "子命令:"
        echo "  backup              备份数据库（gzip 压缩）"
        echo "  restore [文件]      恢复最近/指定备份"
        echo "  list                列出所有备份"
        echo "  clean [天数]        清理过期备份（默认28天）"
        exit 1
        ;;
esac
