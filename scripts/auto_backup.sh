#!/bin/bash
# 每天 0:00 自动备份数据，保留 7 天
cd /root/workspace/reqman || exit 1
BACKUP_DIR="data/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d)
BACKUP_FILE="$BACKUP_DIR/reqman_db_${DATE}.json.gz"
gzip -c data/reqman_db.json > "$BACKUP_FILE"
find "$BACKUP_DIR" -name "reqman_db_*.json.gz" -mtime +7 -delete
