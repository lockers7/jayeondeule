#!/bin/bash
# ============================================================
# OS 루트(/) 백업 동기화 스크립트
# Samsung SSD 850 EVO (/) → ADATA SP600 (/mnt/os_backup)
# 매일 1회 cron으로 실행
# ============================================================

SRC="/"
DST="/mnt/os_backup/"
LOG="/var/log/os_backup_sync.log"
LOCK="/tmp/os_backup_sync.lock"

# 중복 실행 방지
if [ -f "$LOCK" ]; then
    PID=$(cat "$LOCK")
    if kill -0 "$PID" 2>/dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [SKIP] 이전 백업이 진행 중 (PID: $PID)" >> "$LOG"
        exit 0
    fi
    rm -f "$LOCK"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# 백업 디스크 마운트 확인
if ! mountpoint -q "$DST"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] $DST 가 마운트되어 있지 않습니다." >> "$LOG"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') [START] OS 루트 백업 시작" >> "$LOG"

rsync -aAX --delete \
    --exclude='/dev/*' \
    --exclude='/proc/*' \
    --exclude='/sys/*' \
    --exclude='/tmp/*' \
    --exclude='/run/*' \
    --exclude='/mnt/*' \
    --exclude='/media/*' \
    --exclude='/workspace/*' \
    --exclude='/snap/*' \
    --exclude='/lost+found' \
    --exclude='/swap.img' \
    --exclude='/usr/share/ollama/*' \
    --exclude='/var/log/journal/*' \
    --exclude='/var/log/*.1' \
    --exclude='/var/log/*.gz' \
    --exclude='/var/log/btmp*' \
    "$SRC" "$DST" 2>> "$LOG"

STATUS=$?

if [ $STATUS -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [DONE] OS 루트 백업 완료" >> "$LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] rsync 오류 코드: $STATUS" >> "$LOG"
fi
