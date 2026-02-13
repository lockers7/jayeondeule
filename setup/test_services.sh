#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core 서비스 통합 테스트 스크립트
# =========================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_test()  { echo -e "${BLUE}[TEST]${NC} $1"; }

FAILED=0

echo "=========================================="
echo "  AgriAI Core 서비스 통합 테스트"
echo "=========================================="
echo ""

# -------------------------------------------------------------------
# 1. systemd 데몬 리로드
# -------------------------------------------------------------------
log_test "1. systemd 데몬 리로드..."
sudo systemctl daemon-reload
log_info "데몬 리로드 완료"
echo ""

# -------------------------------------------------------------------
# 2. 기존 서비스 중지
# -------------------------------------------------------------------
log_test "2. 기존 서비스 중지..."
sudo systemctl stop agriAiCore reflex 2>/dev/null || true
sleep 2
log_info "서비스 중지 완료"
echo ""

# -------------------------------------------------------------------
# 3. ChromaDB 시작 확인
# -------------------------------------------------------------------
log_test "3. ChromaDB 시작 확인..."
if ! sudo systemctl is-active --quiet chromadb; then
    log_warn "ChromaDB가 실행 중이 아닙니다. 시작합니다..."
    sudo systemctl start chromadb
    sleep 3
fi

if sudo systemctl is-active --quiet chromadb; then
    log_info "ChromaDB 실행 중 ✓"

    # ChromaDB API 테스트
    if curl -s http://localhost:8000/api/v1/heartbeat > /dev/null 2>&1; then
        log_info "ChromaDB API 응답 정상 ✓"
    else
        log_warn "ChromaDB API 응답 없음"
        FAILED=1
    fi
else
    log_error "ChromaDB 시작 실패"
    FAILED=1
fi
echo ""

# -------------------------------------------------------------------
# 4. agriAiCore 서비스 시작 (기본 모드: Streamlit)
# -------------------------------------------------------------------
log_test "4. agriAiCore 서비스 시작 (UI_MODE=streamlit)..."
sudo systemctl start agriAiCore
sleep 5

if sudo systemctl is-active --quiet agriAiCore; then
    log_info "agriAiCore 서비스 실행 중 ✓"

    # 로그 확인
    log_test "   로그 확인..."
    if sudo journalctl -u agriAiCore -n 10 --no-pager | grep -q "백그라운드 서비스 시작"; then
        log_info "   스케줄러 시작 로그 확인 ✓"
    else
        log_warn "   스케줄러 시작 로그 없음"
    fi

    if sudo journalctl -u agriAiCore -n 10 --no-pager | grep -q "Streamlit"; then
        log_info "   Streamlit 시작 로그 확인 ✓"
    else
        log_warn "   Streamlit 시작 로그 없음"
    fi
else
    log_error "agriAiCore 서비스 시작 실패"
    sudo journalctl -u agriAiCore -n 20 --no-pager
    FAILED=1
fi
echo ""

# -------------------------------------------------------------------
# 5. 포트 확인
# -------------------------------------------------------------------
log_test "5. 포트 확인..."

# Streamlit 포트 (8501)
sleep 3
if ss -tuln | grep -q ":8501"; then
    log_info "Streamlit 포트 8501 열림 ✓"

    # HTTP 응답 확인
    if curl -s http://localhost:8501 > /dev/null 2>&1; then
        log_info "Streamlit HTTP 응답 정상 ✓"
    else
        log_warn "Streamlit HTTP 응답 대기 중..."
        sleep 5
        if curl -s http://localhost:8501 > /dev/null 2>&1; then
            log_info "Streamlit HTTP 응답 정상 ✓"
        else
            log_error "Streamlit HTTP 응답 없음"
            FAILED=1
        fi
    fi
else
    log_error "Streamlit 포트 8501 닫힘"
    FAILED=1
fi
echo ""

# -------------------------------------------------------------------
# 6. PID 파일 확인
# -------------------------------------------------------------------
log_test "6. PID 파일 확인..."

if [ -f /tmp/scheduler.pid ]; then
    SCHEDULER_PID=$(cat /tmp/scheduler.pid)
    if kill -0 "$SCHEDULER_PID" 2>/dev/null; then
        log_info "스케줄러 프로세스 실행 중 (PID: $SCHEDULER_PID) ✓"
    else
        log_error "스케줄러 PID 파일 존재하나 프로세스 없음"
        FAILED=1
    fi
else
    log_warn "스케줄러 PID 파일 없음"
fi

if [ -f /tmp/streamlit.pid ]; then
    STREAMLIT_PID=$(cat /tmp/streamlit.pid)
    if kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        log_info "Streamlit 프로세스 실행 중 (PID: $STREAMLIT_PID) ✓"
    else
        log_error "Streamlit PID 파일 존재하나 프로세스 없음"
        FAILED=1
    fi
else
    log_warn "Streamlit PID 파일 없음"
fi
echo ""

# -------------------------------------------------------------------
# 7. UI 모드 변경 테스트 (Reflex)
# -------------------------------------------------------------------
log_test "7. UI 모드 변경 테스트 (UI_MODE=reflex)..."

# 서비스 중지
sudo systemctl stop agriAiCore
sleep 2

# Reflex 모드로 재시작
sudo systemctl set-environment UI_MODE=reflex
sudo systemctl start agriAiCore
sleep 10

if sudo systemctl is-active --quiet agriAiCore; then
    log_info "agriAiCore 서비스 실행 중 (Reflex 모드) ✓"

    # Reflex 로그 확인
    if sudo journalctl -u agriAiCore -n 10 --no-pager | grep -q "Reflex"; then
        log_info "Reflex 시작 로그 확인 ✓"
    else
        log_warn "Reflex 시작 로그 없음"
    fi

    # Reflex 포트 확인 (3000, 8001)
    sleep 5
    if ss -tuln | grep -q ":3000"; then
        log_info "Reflex Frontend 포트 3000 열림 ✓"
    else
        log_warn "Reflex Frontend 포트 3000 대기 중..."
        sleep 5
        if ss -tuln | grep -q ":3000"; then
            log_info "Reflex Frontend 포트 3000 열림 ✓"
        else
            log_error "Reflex Frontend 포트 3000 닫힘"
            FAILED=1
        fi
    fi

    if ss -tuln | grep -q ":8001"; then
        log_info "Reflex Backend 포트 8001 열림 ✓"
    else
        log_warn "Reflex Backend 포트 8001 닫힘"
    fi
else
    log_error "agriAiCore 서비스 시작 실패 (Reflex 모드)"
    sudo journalctl -u agriAiCore -n 20 --no-pager
    FAILED=1
fi
echo ""

# -------------------------------------------------------------------
# 8. 기본 모드로 복원
# -------------------------------------------------------------------
log_test "8. 기본 모드로 복원 (UI_MODE=streamlit)..."
sudo systemctl stop agriAiCore
sleep 2
sudo systemctl unset-environment UI_MODE
sudo systemctl start agriAiCore
sleep 5

if sudo systemctl is-active --quiet agriAiCore; then
    log_info "기본 모드 복원 완료 ✓"
else
    log_error "기본 모드 복원 실패"
    FAILED=1
fi
echo ""

# -------------------------------------------------------------------
# 9. 로그 파일 확인
# -------------------------------------------------------------------
log_test "9. 로그 파일 확인..."

LOG_DIR="/workspace/jayeondeule/logs"
if [ -d "$LOG_DIR" ]; then
    log_info "로그 디렉토리 존재 ✓"

    if [ -f "$LOG_DIR/scheduler.log" ]; then
        log_info "스케줄러 로그 파일 존재 ✓"
        SIZE=$(du -h "$LOG_DIR/scheduler.log" | cut -f1)
        echo "         크기: $SIZE"
    fi

    if [ -f "$LOG_DIR/streamlit.log" ]; then
        log_info "Streamlit 로그 파일 존재 ✓"
        SIZE=$(du -h "$LOG_DIR/streamlit.log" | cut -f1)
        echo "         크기: $SIZE"
    fi

    if [ -f "$LOG_DIR/reflex.log" ]; then
        log_info "Reflex 로그 파일 존재 ✓"
        SIZE=$(du -h "$LOG_DIR/reflex.log" | cut -f1)
        echo "         크기: $SIZE"
    fi
else
    log_warn "로그 디렉토리 없음"
fi
echo ""

# -------------------------------------------------------------------
# 10. 최종 상태 확인
# -------------------------------------------------------------------
log_test "10. 최종 상태 확인..."
sudo systemctl status chromadb agriAiCore --no-pager | grep -E "(Active|Loaded|Main PID)" || true
echo ""

# -------------------------------------------------------------------
# 결과 출력
# -------------------------------------------------------------------
echo "=========================================="
if [ $FAILED -eq 0 ]; then
    log_info "모든 테스트 통과! ✓✓✓"
    echo ""
    echo "서비스 접속:"
    echo "  - ChromaDB:  http://localhost:8000"
    echo "  - Streamlit: http://localhost:8501"
    echo ""
    echo "UI 모드 변경 방법:"
    echo "  sudo systemctl set-environment UI_MODE=reflex"
    echo "  sudo systemctl restart agriAiCore"
else
    log_error "일부 테스트 실패"
    echo ""
    echo "로그 확인:"
    echo "  sudo journalctl -u agriAiCore -f"
fi
echo "=========================================="
