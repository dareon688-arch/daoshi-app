#!/bin/bash
# backup.sh —— 每天自动备份数据库和上传的照片
#
# 备份内容：DATA_DIR 下的 app.db（数据库）和 uploads/（照片）
# 存放位置：/home/ubuntu/backups/
# 保留策略：只留最近 7 天，自动删更早的
#
# 用 cron 每天定时跑（见部署说明）。

set -e

DATA_DIR="/home/ubuntu/daoshi-app/data"
BACKUP_DIR="/home/ubuntu/backups"
KEEP_DAYS=7

# 确保备份目录存在
mkdir -p "$BACKUP_DIR"

# 用日期+时间命名，避免覆盖
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/daoshi_backup_$STAMP.tar.gz"

# 打包：进到 DATA_DIR，把 app.db 和 uploads 一起压缩
if [ -d "$DATA_DIR" ]; then
    tar -czf "$OUT" -C "$DATA_DIR" app.db uploads 2>/dev/null || \
    tar -czf "$OUT" -C "$DATA_DIR" app.db 2>/dev/null || true
    echo "$(date '+%F %T') 备份完成：$OUT"
else
    echo "$(date '+%F %T') 错误：找不到数据目录 $DATA_DIR"
    exit 1
fi

# 清理超过 KEEP_DAYS 天的旧备份
find "$BACKUP_DIR" -name "daoshi_backup_*.tar.gz" -mtime +$KEEP_DAYS -delete

# 显示当前备份列表（方便确认）
echo "当前备份："
ls -lh "$BACKUP_DIR"/daoshi_backup_*.tar.gz 2>/dev/null | tail -10
