#!/bin/bash
# ============================================================
# HDD 백업 미러 동기화 스크립트
# NVMe SSD (/workspace) → HDD (/mnt/hdd_backup)
# 30분 주기 cron으로 실행
# ============================================================

SRC="/workspace/"
DST="/mnt/hdd_backup/"
LOG="/var/log/hdd_backup_sync.log"
LOCK="/tmp/hdd_backup_sync.lock"

# 중복 실행 방지
if [ -f "$LOCK" ]; then
    PID=$(cat "$LOCK")
    if kill -0 "$PID" 2>/dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [SKIP] 이전 동기화가 진행 중 (PID: $PID)" >> "$LOG"
        exit 0
    fi
    rm -f "$LOCK"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# HDD 마운트 확인
if ! mountpoint -q "$DST"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] $DST 가 마운트되어 있지 않습니다." >> "$LOG"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') [START] 동기화 시작" >> "$LOG"

rsync -a --delete \
    --exclude='lost+found' \
    "$SRC" "$DST" 2>> "$LOG"

STATUS=$?

if [ $STATUS -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [DONE] 동기화 완료" >> "$LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] rsync 오류 코드: $STATUS" >> "$LOG"
fi
