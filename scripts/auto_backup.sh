#!/bin/bash
# 每天 0:00 自动备份数据（核心+运行时文件），保留 7 天
cd /root/workspace/reqman || exit 1
BACKUP_DIR="data/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d)
gzip -c data/reqman_db.json > "$BACKUP_DIR/reqman_db_${DATE}.json.gz"
# 运行时文件含计数器/索引/工作包，缺失会导致恢复后 next_id 回退
[ -f data/reqman_db_runtime.json ] && gzip -c data/reqman_db_runtime.json > "$BACKUP_DIR/reqman_db_runtime_${DATE}.json.gz"
find "$BACKUP_DIR" -name "reqman_db*.json.gz" -mtime +7 -delete
