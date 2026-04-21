#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Ollama 버전 확인 및 업그레이드 스크립트
# -----------------------------------------
# 시스템 설치된 ollama (/usr/local/bin/ollama, systemd ollama.service) 를
# 최신 버전으로 업그레이드합니다. 모델 데이터(.ollama/models)는 보존됩니다.
#
# 사용법:
#   bash setup/ollama_upgrade.sh          # 버전 확인만
#   bash setup/ollama_upgrade.sh check    # 버전 확인만
#   bash setup/ollama_upgrade.sh upgrade  # 업그레이드 실행
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
OLLAMA_BIN="/usr/local/bin/ollama"
OLLAMA_API="http://localhost:11434"
MODELS_DIR="${OLLAMA_MODELS:-$PROJECT_DIR/.ollama/models}"

# =================================================================
# ollama 설치 확인
# =================================================================
check_installed() {
    if [ ! -x "$OLLAMA_BIN" ]; then
        log_error "ollama 가 설치되어 있지 않습니다: $OLLAMA_BIN"
        log_info "설치: curl -fsSL https://ollama.com/install.sh | sh"
        exit 1
    fi
}

# =================================================================
# 현재 버전 추출 (예: "ollama version is 0.20.7" → "0.20.7")
# =================================================================
get_current_version() {
    "$OLLAMA_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}

# =================================================================
# GitHub 최신 릴리스 버전 (예: "v0.21.0" → "0.21.0")
# =================================================================
get_latest_version() {
    curl -s https://api.github.com/repos/ollama/ollama/releases/latest 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tag_name'].lstrip('v'))" 2>/dev/null
}

# =================================================================
# 버전 확인
# =================================================================
check_version() {
    log_title "=========================================="
    log_title "  Ollama 버전 확인"
    log_title "=========================================="
    echo ""

    check_installed

    CURRENT=$(get_current_version)
    if [ -z "$CURRENT" ]; then
        log_error "현재 ollama 버전을 확인할 수 없습니다."
        exit 1
    fi

    LATEST=$(get_latest_version)
    if [ -z "$LATEST" ]; then
        log_error "GitHub 최신 버전을 확인할 수 없습니다. (네트워크 확인 필요)"
        log_info "현재 버전: $CURRENT"
        exit 1
    fi

    log_info "현재 버전: $CURRENT"
    log_info "최신 버전: $LATEST"
    echo ""

    # 서비스 상태
    if systemctl is-active --quiet ollama 2>/dev/null; then
        log_info "ollama 서비스: 실행 중"
    else
        log_warn "ollama 서비스: 중지 상태"
    fi

    # 모델 디렉토리
    if [ -d "$MODELS_DIR" ]; then
        SIZE=$(du -sh "$MODELS_DIR" 2>/dev/null | awk '{print $1}')
        COUNT=$(find "$MODELS_DIR/manifests" -type f 2>/dev/null | wc -l)
        log_info "모델 저장소: $MODELS_DIR (${SIZE:-?}, manifest ${COUNT}개)"
    else
        log_warn "모델 저장소 없음: $MODELS_DIR"
    fi
    echo ""

    if [ "$CURRENT" = "$LATEST" ]; then
        log_info "이미 최신 버전입니다."
        return 1
    else
        log_warn "업그레이드 가능: $CURRENT -> $LATEST"
        log_info "업그레이드 실행: bash setup/ollama_upgrade.sh upgrade"
        return 0
    fi
}

# =================================================================
# heartbeat 확인 — Ollama API 응답 대기
# =================================================================
wait_for_ready() {
    RETRY=0
    MAX_RETRY=12  # 60초 (5초 × 12)
    while [ $RETRY -lt $MAX_RETRY ]; do
        if curl -s --max-time 3 "$OLLAMA_API/api/version" 2>/dev/null | grep -q "version"; then
            return 0
        fi
        RETRY=$((RETRY + 1))
        log_warn "API 응답 대기... ($RETRY/$MAX_RETRY)"
        sleep 5
    done
    return 1
}

# =================================================================
# 업그레이드
# =================================================================
do_upgrade() {
    log_title "=========================================="
    log_title "  Ollama 업그레이드"
    log_title "=========================================="
    echo ""

    check_installed

    CURRENT=$(get_current_version)
    LATEST=$(get_latest_version)

    if [ -z "$CURRENT" ] || [ -z "$LATEST" ]; then
        log_error "버전 확인 실패. 현재=$CURRENT 최신=$LATEST"
        exit 1
    fi

    if [ "$CURRENT" = "$LATEST" ]; then
        log_info "이미 최신 버전입니다. ($CURRENT)"
        exit 0
    fi

    log_info "업그레이드: $CURRENT -> $LATEST"
    echo ""

    # 1단계: 모델 디렉토리 안내 (자동 백업하지 않음 — 용량이 매우 클 수 있음)
    log_info "[1/4] 모델 데이터 보존 확인..."
    if [ -d "$MODELS_DIR" ]; then
        SIZE=$(du -sh "$MODELS_DIR" 2>/dev/null | awk '{print $1}')
        log_info "모델 저장소: $MODELS_DIR (${SIZE:-?})"
        log_info "  → install.sh 는 모델 디렉토리를 건드리지 않으므로 자동 보존됩니다."
        log_info "  → 별도 백업이 필요하면 수동으로: cp -a $MODELS_DIR <backup_path>"
    else
        log_warn "모델 저장소가 없습니다. 업그레이드 후 모델 다시 받아야 할 수 있습니다."
    fi

    # 2단계: 서비스 중지
    log_info "[2/4] ollama 서비스 중지..."
    if systemctl is-active --quiet ollama 2>/dev/null; then
        sudo systemctl stop ollama
        log_info "서비스 중지 완료"
        sleep 2
    else
        log_warn "ollama 서비스가 실행 중이 아닙니다."
    fi

    # 3단계: 공식 install.sh 실행 (자동 binary 교체)
    log_info "[3/4] ollama 최신 버전 설치 (install.sh 실행)..."
    if ! curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tail -10; then
        log_error "install.sh 실행 실패"
        log_warn "롤백: 이전 binary 가 남아 있다면 systemctl start ollama 후 정상 동작 확인"
        exit 1
    fi

    NEW_VERSION=$(get_current_version)
    log_info "업그레이드된 버전: $NEW_VERSION"

    # 4단계: 서비스 시작 + heartbeat 확인
    log_info "[4/4] ollama 서비스 시작 및 확인..."
    if systemctl is-enabled --quiet ollama 2>/dev/null; then
        # install.sh 가 이미 시작했을 수도 있음 — 한 번 더 보장
        if ! systemctl is-active --quiet ollama 2>/dev/null; then
            sudo systemctl start ollama
        fi
        sleep 3

        if wait_for_ready; then
            log_info "Ollama API 정상 응답 확인 ($OLLAMA_API/api/version)"
            # 모델 목록 확인
            MODELS=$(curl -s --max-time 5 "$OLLAMA_API/api/tags" 2>/dev/null \
                     | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('models',[])))" 2>/dev/null)
            if [ -n "$MODELS" ]; then
                log_info "보유 모델 수: $MODELS 개"
            fi
        else
            log_error "Ollama API 가 응답하지 않습니다."
            log_warn "확인: sudo journalctl -u ollama -n 50"
            exit 1
        fi
    else
        log_warn "ollama systemd 서비스가 등록되지 않았습니다. 수동으로 시작하세요:"
        log_warn "  sudo systemctl enable --now ollama"
    fi

    echo ""
    log_title "=========================================="
    log_title "  업그레이드 완료"
    log_title "=========================================="
    echo ""
    log_info "  $CURRENT -> $NEW_VERSION"
    if [ -d "$MODELS_DIR" ]; then
        log_info "  모델 저장소 (보존됨): $MODELS_DIR"
    fi
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
        echo "  upgrade   최신 버전으로 업그레이드 (모델 데이터 보존)"
        echo ""
        ;;
esac
