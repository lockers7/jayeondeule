#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core 통합 서비스 시작 스크립트
# 백그라운드 서비스(스케줄러)와 Streamlit UI를 함께 실행
# =========================================================================

set -e

# 작업 디렉토리 이동
cd /workspace/jayeondeule

# Python 캐시 파일 생성 방지
export PYTHONDONTWRITEBYTECODE=1

# 환경 변수 로드 (systemd의 EnvironmentFile이 처리하므로 불필요)
# .env 파일은 systemd가 직접 로드함

# Python 가상환경 경로
PYTHON_BIN="/workspace/jayeondeule/venv/bin/python"
STREAMLIT_BIN="/workspace/jayeondeule/venv/bin/streamlit"

# PID 파일 경로
SCHEDULER_PID="/tmp/scheduler.pid"
STREAMLIT_PID="/tmp/streamlit.pid"

# 로그 파일 경로
LOG_DIR="${LOG_PATH:-/workspace/jayeondeule/logs}"
mkdir -p "$LOG_DIR"

# -------------------------------------------------------------------
# 프로세스 종료 핸들러
# -------------------------------------------------------------------
cleanup() {
    echo "서비스 종료 중..."

    # Streamlit 종료
    if [ -f "$STREAMLIT_PID" ]; then
        STREAMLIT_PID_NUM=$(cat "$STREAMLIT_PID")
        if kill -0 "$STREAMLIT_PID_NUM" 2>/dev/null; then
            echo "Streamlit 종료 중 (PID: $STREAMLIT_PID_NUM)..."
            kill "$STREAMLIT_PID_NUM"
            wait "$STREAMLIT_PID_NUM" 2>/dev/null || true
        fi
        rm -f "$STREAMLIT_PID"
    fi

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

# Streamlit UI 시작
echo "Streamlit UI 시작 중..."
$STREAMLIT_BIN run /workspace/jayeondeule/agri_ai_core/ui/streamlit_app/main.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    >> "$LOG_DIR/streamlit.log" 2>&1 &
STREAMLIT_PID_NUM=$!
echo $STREAMLIT_PID_NUM > "$STREAMLIT_PID"
echo "Streamlit UI 시작됨 (PID: $STREAMLIT_PID_NUM)"

echo ""
echo "=========================================="
echo "  서비스 시작 완료"
echo "=========================================="
echo "  - Streamlit: http://0.0.0.0:8501"
echo "=========================================="
echo ""

# 두 프로세스가 종료될 때까지 대기
wait
