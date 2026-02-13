#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# ChromaDB 버전 확인 및 업그레이드 스크립트 (네이티브 설치용)
# -----------------------------------------
# venv 환경의 ChromaDB를 최신 버전으로 업그레이드합니다.
#
# 사용법:
#   bash setup/chromadb_upgrade.sh          # 버전 확인만
#   bash setup/chromadb_upgrade.sh check    # 버전 확인만
#   bash setup/chromadb_upgrade.sh upgrade  # 업그레이드 실행
#
# =========================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIP="$PROJECT_DIR/venv/bin/pip"
DATA_DIR="$PROJECT_DIR/chromadb/database"

# =================================================================
# venv 확인
# =================================================================
check_venv() {
    if [ ! -f "$PIP" ]; then
        log_error "venv가 존재하지 않습니다: $PIP"
        exit 1
    fi
}

# =================================================================
# 버전 확인
# =================================================================
check_version() {
    log_title "=========================================="
    log_title "  ChromaDB 버전 확인"
    log_title "=========================================="
    echo ""

    check_venv

    # 현재 설치 버전
    CURRENT=$("$PIP" show chromadb 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ -z "$CURRENT" ]; then
        log_error "chromadb가 설치되어 있지 않습니다."
        log_info "설치: $PIP install chromadb"
        exit 1
    fi

    # PyPI 최신 버전
    LATEST=$(curl -s https://pypi.org/pypi/chromadb/json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null)

    if [ -z "$LATEST" ]; then
        log_error "최신 버전을 확인할 수 없습니다. (네트워크 확인 필요)"
        log_info "현재 버전: $CURRENT"
        exit 1
    fi

    log_info "현재 버전: $CURRENT"
    log_info "최신 버전: $LATEST"
    echo ""

    if [ "$CURRENT" = "$LATEST" ]; then
        log_info "이미 최신 버전입니다."
        return 1
    else
        log_warn "업그레이드 가능: $CURRENT -> $LATEST"
        log_info "업그레이드 실행: bash setup/chromadb_upgrade.sh upgrade"
        return 0
    fi
}

# =================================================================
# 업그레이드
# =================================================================
do_upgrade() {
    log_title "=========================================="
    log_title "  ChromaDB 업그레이드"
    log_title "=========================================="
    echo ""

    check_venv

    # 현재 버전 확인
    CURRENT=$("$PIP" show chromadb 2>/dev/null | grep "^Version:" | awk '{print $2}')
    LATEST=$(curl -s https://pypi.org/pypi/chromadb/json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null)

    if [ "$CURRENT" = "$LATEST" ]; then
        log_info "이미 최신 버전입니다. ($CURRENT)"
        exit 0
    fi

    log_info "업그레이드: $CURRENT -> $LATEST"
    echo ""

    # 1단계: 데이터 백업
    log_info "[1/4] 데이터 백업 중..."
    BACKUP_DIR="$PROJECT_DIR/chromadb/backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    cp -r "$DATA_DIR/" "$BACKUP_DIR/"
    log_info "백업 완료: $BACKUP_DIR"

    # 2단계: chromadb 서비스 중지
    log_info "[2/4] ChromaDB 서비스 중지..."
    if systemctl is-active --quiet chromadb 2>/dev/null; then
        sudo systemctl stop chromadb
        log_info "서비스 중지 완료"
    else
        log_warn "chromadb 서비스가 실행 중이 아닙니다."
    fi

    # 3단계: pip 업그레이드
    log_info "[3/4] chromadb 패키지 업그레이드 중..."
    "$PIP" install --upgrade chromadb 2>&1 | tail -5

    NEW_VERSION=$("$PIP" show chromadb 2>/dev/null | grep "^Version:" | awk '{print $2}')
    log_info "업그레이드된 버전: $NEW_VERSION"

    # 4단계: 서비스 재시작 및 동작 확인
    log_info "[4/4] ChromaDB 서비스 시작 및 확인..."
    if systemctl is-enabled --quiet chromadb 2>/dev/null; then
        sudo systemctl start chromadb
        sleep 3

        RETRY=0
        MAX_RETRY=6
        while [ $RETRY -lt $MAX_RETRY ]; do
            HEARTBEAT=$(curl -s http://localhost:8000/api/v2/heartbeat 2>/dev/null)
            if echo "$HEARTBEAT" | grep -q "nanosecond"; then
                log_info "ChromaDB 정상 작동 확인"
                break
            fi
            RETRY=$((RETRY + 1))
            log_warn "대기 중... ($RETRY/$MAX_RETRY)"
            sleep 5
        done

        if [ $RETRY -eq $MAX_RETRY ]; then
            log_error "ChromaDB가 응답하지 않습니다."
            log_warn "롤백: sudo systemctl stop chromadb && $PIP install chromadb==$CURRENT && sudo systemctl start chromadb"
            exit 1
        fi
    else
        log_warn "chromadb systemd 서비스가 등록되지 않았습니다. 수동으로 시작하세요."
    fi

    echo ""
    log_title "=========================================="
    log_title "  업그레이드 완료"
    log_title "=========================================="
    echo ""
    log_info "  $CURRENT -> $NEW_VERSION"
    log_info "  백업 위치: $BACKUP_DIR"
    echo ""
}

# =================================================================
# 메인
# =================================================================
case "${1:-check}" in
    check)
        check_version
        ;;
    upgrade)
        do_upgrade
        ;;
    *)
        echo ""
        echo "사용법: bash $0 [명령어]"
        echo ""
        echo "명령어:"
        echo "  check     현재 버전과 최신 버전 비교 (기본)"
        echo "  upgrade   최신 버전으로 업그레이드"
        echo ""
        ;;
esac
