#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core 통합 서비스 시작 스크립트
# 백그라운드 서비스(스케줄러)와 Reflex UI를 함께 실행
#
# 환경 변수:
#   REFLEX_ENV=prod (기본값) → 프로덕션 모드 (단일 포트)
#   REFLEX_ENV=dev          → 개발 모드 (프론트엔드/백엔드 분리)
# =========================================================================

set -e

# 작업 디렉토리 이동
cd /workspace/jayeondeule

# Python 캐시 파일 생성 방지
export PYTHONDONTWRITEBYTECODE=1

# Python 가상환경 경로
PYTHON_BIN="/workspace/jayeondeule/venv/bin/python"
REFLEX_BIN="/workspace/jayeondeule/venv/bin/reflex"

# PID 파일 경로
SCHEDULER_PID="/tmp/scheduler.pid"
REFLEX_PID="/tmp/reflex.pid"

# 로그 파일 경로
LOG_DIR="${LOG_PATH:-/workspace/jayeondeule/logs}"
mkdir -p "$LOG_DIR"

# Reflex 실행 환경 설정
REFLEX_ENV="${REFLEX_ENV:-prod}"
REFLEX_USE_GRANIAN="${REFLEX_USE_GRANIAN:-false}"

is_port_listening() {
    local port_hex
    port_hex=$(printf '%04X' "$1")
    awk -v p="$port_hex" '
        NR > 1 {
            split($2, addr, ":")
            if (toupper(addr[2]) == p && $4 == "0A") {
                found = 1
                exit 0
            }
        }
        END { if (!found) exit 1 }
    ' /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

wait_reflex_ready() {
    local timeout_sec="${1:-60}"
    local waited=0

    while [ "$waited" -lt "$timeout_sec" ]; do
        # reflex 런처 프로세스 자체가 죽었으면 즉시 실패
        if [ -f "$REFLEX_PID" ]; then
            local pid
            pid=$(cat "$REFLEX_PID" 2>/dev/null || true)
            if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
                return 1
            fi
        fi

        # prod(single-port): 3000 오픈 확인
        if [ "$REFLEX_ENV" = "prod" ]; then
            if is_port_listening 3000; then
                return 0
            fi
        else
            # dev 모드: 프론트/백엔드 모두 오픈 확인
            if is_port_listening 3000 && is_port_listening 8001; then
                return 0
            fi
        fi

        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

start_reflex_ui() {
    # Reflex는 agri_ai_core 디렉토리에서 실행해야 app_name 경로와 일치함
    cd /workspace/jayeondeule/agri_ai_core

    # 이전 비정상 종료로 남은 Reflex/gunicorn 잔존 프로세스 정리
    pkill -f "/workspace/jayeondeule/venv/bin/gunicorn.*main.main:app\\(\\)" 2>/dev/null || true
    pkill -f "/workspace/jayeondeule/venv/bin/reflex run" 2>/dev/null || true

    # venv/bin을 PATH에 추가 (gunicorn, uvicorn 등 실행 파일 접근용)
    export PATH="/workspace/jayeondeule/venv/bin:$PATH"
    export PYTHONPATH="/workspace/jayeondeule:${PYTHONPATH}"
    export REFLEX_USE_GRANIAN

    # Reflex 초기화 (최초 1회)
    if [ ! -d "/workspace/jayeondeule/agri_ai_core/.web" ]; then
        $REFLEX_BIN init --template blank >> "$LOG_DIR/reflex.log" 2>&1
    fi

    if [ "$REFLEX_ENV" = "prod" ]; then
        $REFLEX_BIN run --env prod --single-port --frontend-port 3000 \
            >> "$LOG_DIR/reflex.log" 2>&1 &
    else
        $REFLEX_BIN run --env "$REFLEX_ENV" --frontend-port 3000 --backend-port 8001 \
            >> "$LOG_DIR/reflex.log" 2>&1 &
    fi
    REFLEX_PID_NUM=$!
    echo $REFLEX_PID_NUM > "$REFLEX_PID"

    if wait_reflex_ready 75; then
        echo "Reflex UI 시작됨 (PID: $REFLEX_PID_NUM)"
    else
        echo "Reflex UI 시작 실패 (PID: $REFLEX_PID_NUM)"
        echo "최근 로그:"
        tail -n 30 "$LOG_DIR/reflex.log" || true
        return 1
    fi
}

# -------------------------------------------------------------------
# 프로세스 종료 핸들러
# -------------------------------------------------------------------
cleanup() {
    echo "서비스 종료 중..."

    # Reflex 종료
    if [ -f "$REFLEX_PID" ]; then
        REFLEX_PID_NUM=$(cat "$REFLEX_PID")
        if kill -0 "$REFLEX_PID_NUM" 2>/dev/null; then
            echo "Reflex 종료 중 (PID: $REFLEX_PID_NUM)..."
            kill "$REFLEX_PID_NUM"
            wait "$REFLEX_PID_NUM" 2>/dev/null || true
        fi
        rm -f "$REFLEX_PID"
    fi
    # Reflex 자식(gunicorn worker) 잔존 프로세스 정리
    pkill -f "/workspace/jayeondeule/venv/bin/gunicorn.*main.main:app\\(\\)" 2>/dev/null || true
    pkill -f "/workspace/jayeondeule/venv/bin/reflex run" 2>/dev/null || true

    # 스케줄러 종료
    if [ -f "$SCHEDULER_PID" ]; then
        SCHEDULER_PID_NUM=$(cat "$SCHEDULER_PID")
        if kill -0 "$SCHEDULER_PID_NUM" 2>/dev/null; then
            echo "스케줄러 종료 중 (PID: $SCHEDULER_PID_NUM)..."
            kill "$SCHEDULER_PID_NUM"
            wait "$SCHEDULER_PID_NUM" 2>/dev/null || true
        fi
        rm -f "$SCHEDULER_PID"
    fi

    echo "모든 서비스 종료 완료"
    exit 0
}

# SIGTERM, SIGINT 시그널 처리
trap cleanup SIGTERM SIGINT

# -------------------------------------------------------------------
# 서비스 시작
# -------------------------------------------------------------------
echo "=========================================="
echo "  AgriAI Core 서비스 시작"
echo "  Reflex UI (모드: $REFLEX_ENV)"
echo "=========================================="
echo ""

# 백그라운드 서비스 시작 (ChromaDB 연결, 스케줄러)
echo "백그라운드 서비스 시작 중 (스케줄러)..."
$PYTHON_BIN -m agri_ai_core.run_scheduler >> "$LOG_DIR/scheduler.log" 2>&1 &
SCHEDULER_PID_NUM=$!
echo $SCHEDULER_PID_NUM > "$SCHEDULER_PID"
echo "백그라운드 서비스 시작됨 (PID: $SCHEDULER_PID_NUM)"

# 초기화 완료 대기
sleep 3

# Reflex UI 시작
echo "Reflex UI 시작 중..."
start_reflex_ui
if [ "$REFLEX_ENV" = "prod" ]; then
    echo "  - Reflex: http://0.0.0.0:3000 (프로덕션 모드)"
else
    echo "  - Reflex Frontend: http://0.0.0.0:3000"
    echo "  - Reflex Backend: http://0.0.0.0:8001"
fi

echo ""
echo "=========================================="
echo "  서비스 시작 완료"
echo "=========================================="
echo ""

# 모든 프로세스가 종료될 때까지 대기
wait
