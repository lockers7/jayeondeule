#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# MCP postgres 서버 (@kazuph/mcp-fetch) 버전 확인 / 갱신
# -----------------------------------------
# npx 캐시 기반 — 별도 install 없이 다음 실행 시 최신 버전 자동 사용.
#
# 사용법:
#   bash setup/mcp_fetch_upgrade.sh          # 버전 확인만
#   bash setup/mcp_fetch_upgrade.sh check    # 버전 확인만
#   bash setup/mcp_fetch_upgrade.sh upgrade  # npx 캐시 갱신
# =========================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

PKG="@kazuph/mcp-fetch"
NAME="mcp fetch"

check_npx() {
    if ! command -v npx >/dev/null 2>&1; then
        log_error "npx 미설치. nodejs_upgrade.sh 또는 npm 설치 필요."
        exit 1
    fi
}

get_latest() {
    npm view "$PKG" version 2>/dev/null
}

check_version() {
    log_title "=========================================="
    log_title "  MCP $NAME 버전 확인"
    log_title "=========================================="
    echo ""
    check_npx
    log_info "Node.js: $(node --version 2>/dev/null || echo '미설치')"
    log_info "npx:     $(npx --version 2>/dev/null || echo '미설치')"
    echo ""

    LATEST=$(get_latest)
    if [ -z "$LATEST" ]; then
        log_error "npm 레지스트리 조회 실패: $PKG"
        exit 1
    fi
    log_info "패키지: $PKG"
    log_info "최신 버전: $LATEST"
    log_info "(npx 캐시 기반 — VSCode 가 다음 실행 시 자동 다운로드)"
    echo ""
    log_warn "캐시 갱신: bash setup/mcp_fetch_upgrade.sh upgrade"
}

do_upgrade() {
    log_title "=========================================="
    log_title "  MCP $NAME 캐시 갱신"
    log_title "=========================================="
    echo ""
    check_npx

    LATEST=$(get_latest)
    log_info "최신 버전: $LATEST"
    log_info "npx 캐시 갱신 중 (최대 30초 — 서버 모드 진입 후 timeout 으로 강제 종료)..."
    # mcp 서버는 stdin 대기형 — --help 도 처리 안 하므로 timeout 으로 종료.
    # 패키지는 npx 시작 직후 다운로드 완료되므로 강제 종료해도 캐시 정상.
    EXIT=0
    timeout 30 npx -y "$PKG" --help > /dev/null 2>&1 || EXIT=$?
    # 124 = timeout 정상 종료 (서버가 살아있다는 뜻 = 다운로드 성공)
    # 0   = --help 가 정상 처리되어 종료
    # 그 외 = 다운로드 자체 실패
    if [ $EXIT -eq 124 ] || [ $EXIT -eq 0 ]; then
        log_info "캐시 갱신 완료 (다음 MCP 호출부터 v$LATEST 사용)"
    else
        log_warn "캐시 갱신 실패 (exit=$EXIT) — 네트워크/npm 레지스트리 확인"
    fi
    echo ""
    log_warn "VSCode 재시작 필요 (MCP 서버가 새 버전으로 재기동)"
}

case "${1:-check}" in
    check)   check_version ;;
    upgrade) do_upgrade ;;
    *)
        echo ""
        echo "사용법: bash $0 [check|upgrade]"
        echo "  check     현재 / 최신 버전 비교"
        echo "  upgrade   npx 캐시 갱신"
        echo ""
        ;;
esac
