#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core 서비스 통합 테스트 스크립트 (Reflex 단일 운영 기준)
# =========================================================================

set -e

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

log_test "1. systemd 데몬 리로드..."
sudo systemctl daemon-reload
log_info "데몬 리로드 완료"
echo ""

log_test "2. 기존 서비스 중지..."
sudo systemctl stop agriAiCore reflex 2>/dev/null || true
sleep 2
log_info "서비스 중지 완료"
echo ""

log_test "3. ChromaDB 시작 확인..."
if ! sudo systemctl is-active --quiet chromadb; then
    log_warn "ChromaDB가 실행 중이 아닙니다. 시작합니다..."
    sudo systemctl start chromadb
    sleep 3
fi

if sudo systemctl is-active --quiet chromadb; then
    log_info "ChromaDB 실행 중 ✓"
    if curl -s http://127.0.0.1:8000/api/v2/heartbeat >/dev/null 2>&1 || curl -s http://127.0.0.1:8000/api/v1/heartbeat >/dev/null 2>&1; then
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

log_test "4. agriAiCore 시작 (기본 운영 경로)..."
sudo systemctl start agriAiCore
sleep 8

if sudo systemctl is-active --quiet agriAiCore; then
    log_info "agriAiCore 실행 중 ✓"
else
    log_error "agriAiCore 시작 실패"
    sudo journalctl -u agriAiCore -n 40 --no-pager || true
    FAILED=1
fi
echo ""

log_test "5. Reflex 포트/HTTP 확인 (3000)..."
if ss -tuln | grep -q ":3000"; then
    log_info "Port 3000 LISTEN ✓"
else
    log_warn "Port 3000 대기 중..."
    sleep 5
    if ss -tuln | grep -q ":3000"; then
        log_info "Port 3000 LISTEN ✓"
    else
        log_error "Port 3000 닫힘"
        FAILED=1
    fi
fi

HTTP_CODE="$(curl -s -o /dev/null -m 5 -w \"%{http_code}\" http://127.0.0.1:3000/ || true)"
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
    log_info "HTTP 응답 정상 ($HTTP_CODE) ✓"
else
    log_error "HTTP 응답 실패 ($HTTP_CODE)"
    FAILED=1
fi
echo ""

log_test "6. 단독 reflex.service 시작 경로 확인..."
sudo systemctl stop agriAiCore
sleep 3
sudo systemctl start reflex
sleep 8

if sudo systemctl is-active --quiet reflex; then
    log_info "reflex.service 실행 중 ✓"
else
    log_error "reflex.service 시작 실패"
    sudo journalctl -u reflex -n 40 --no-pager || true
    FAILED=1
fi

if ss -tuln | grep -q ":3000"; then
    log_info "단독 reflex.service에서도 Port 3000 LISTEN ✓"
else
    log_error "단독 reflex.service Port 3000 실패"
    FAILED=1
fi
echo ""

log_test "7. 기본 운영 상태 복원..."
sudo systemctl stop reflex
sleep 2
sudo systemctl start agriAiCore
sleep 6
if sudo systemctl is-active --quiet agriAiCore; then
    log_info "기본 운영 상태 복원 완료 ✓"
else
    log_error "기본 운영 상태 복원 실패"
    FAILED=1
fi
echo ""

log_test "8. 로그 파일 확인..."
LOG_DIR="/workspace/jayeondeule/logs"
if [ -d "$LOG_DIR" ]; then
    [ -f "$LOG_DIR/scheduler.log" ] && log_info "scheduler.log 존재 ✓" || log_warn "scheduler.log 없음"
    [ -f "$LOG_DIR/reflex.log" ] && log_info "reflex.log 존재 ✓" || log_warn "reflex.log 없음"
else
    log_warn "로그 디렉토리 없음: $LOG_DIR"
fi
echo ""

echo "=========================================="
if [ "$FAILED" -eq 0 ]; then
    log_info "모든 테스트 통과"
else
    log_error "일부 테스트 실패"
    echo "확인: sudo journalctl -u agriAiCore -u reflex -n 100 --no-pager"
fi
echo "=========================================="

exit "$FAILED"
