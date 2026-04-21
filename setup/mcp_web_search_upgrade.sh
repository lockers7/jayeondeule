#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# MCP web-search 서버 (pskill9/web-search) 업그레이드
# -----------------------------------------
# git pull + npm install + npm run build 로 로컬 빌드 갱신.
# .mcp/web-search/ 디렉토리에 클론된 저장소를 가정.
#
# 사용법:
#   bash setup/mcp_web_search_upgrade.sh          # 버전 확인
#   bash setup/mcp_web_search_upgrade.sh check    # 버전 확인
#   bash setup/mcp_web_search_upgrade.sh upgrade  # git pull + 빌드
# =========================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WEB_SEARCH_DIR="$PROJECT_DIR/.mcp/web-search"
REPO_URL="https://github.com/pskill9/web-search.git"

ensure_repo() {
    if [ ! -d "$WEB_SEARCH_DIR/.git" ]; then
        log_warn "web-search 저장소가 없습니다. 새로 클론합니다..."
        git clone "$REPO_URL" "$WEB_SEARCH_DIR"
    fi
}

check_version() {
    log_title "=========================================="
    log_title "  MCP web-search 버전 확인"
    log_title "=========================================="
    echo ""

    if [ ! -d "$WEB_SEARCH_DIR/.git" ]; then
        log_error "저장소 없음: $WEB_SEARCH_DIR"
        log_info "업그레이드(클론 포함): bash setup/mcp_web_search_upgrade.sh upgrade"
        exit 1
    fi

    cd "$WEB_SEARCH_DIR"
    LOCAL_HASH=$(git rev-parse --short HEAD 2>/dev/null)
    LOCAL_DATE=$(git log -1 --format="%ci" 2>/dev/null | cut -d' ' -f1)

    git fetch origin --quiet 2>/dev/null || true
    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')
    DEFAULT_BRANCH=${DEFAULT_BRANCH:-main}
    REMOTE_HASH=$(git rev-parse --short "origin/$DEFAULT_BRANCH" 2>/dev/null || echo "확인불가")
    REMOTE_DATE=$(git log -1 "origin/$DEFAULT_BRANCH" --format="%ci" 2>/dev/null | cut -d' ' -f1 || echo "")
    cd "$PROJECT_DIR"

    log_info "저장소: $REPO_URL"
    log_info "브랜치: $DEFAULT_BRANCH"
    log_info "로컬:   $LOCAL_HASH ($LOCAL_DATE)"
    log_info "원격:   $REMOTE_HASH ($REMOTE_DATE)"
    echo ""

    if [ -f "$WEB_SEARCH_DIR/build/index.js" ]; then
        log_info "빌드 파일 존재 (build/index.js)"
    else
        log_warn "빌드 파일 없음 — upgrade 필요"
    fi
    echo ""

    if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
        log_info "이미 최신 상태"
        return 1
    fi
    log_warn "업그레이드 가능: $LOCAL_HASH → $REMOTE_HASH"
    log_info "업그레이드 실행: bash setup/mcp_web_search_upgrade.sh upgrade"
}

do_upgrade() {
    log_title "=========================================="
    log_title "  MCP web-search 업그레이드"
    log_title "=========================================="
    echo ""
    ensure_repo
    cd "$WEB_SEARCH_DIR"

    BEFORE=$(git rev-parse --short HEAD 2>/dev/null)

    log_info "[1/3] 원격 저장소에서 최신 코드 pull..."
    git fetch origin 2>/dev/null
    DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')
    DEFAULT_BRANCH=${DEFAULT_BRANCH:-main}
    if ! git pull origin "$DEFAULT_BRANCH" 2>/dev/null; then
        log_warn "git pull 실패. 로컬 변경 가능성 있음."
        log_info "강제 리셋: cd $WEB_SEARCH_DIR && git reset --hard origin/$DEFAULT_BRANCH"
        cd "$PROJECT_DIR"
        exit 1
    fi
    AFTER=$(git rev-parse --short HEAD 2>/dev/null)

    if [ "$BEFORE" = "$AFTER" ]; then
        log_info "이미 최신 상태 ($AFTER)"
        # 빌드 파일이 없으면 강제 빌드
        if [ ! -f "$WEB_SEARCH_DIR/build/index.js" ]; then
            log_warn "빌드 파일 누락 — 빌드 진행"
        else
            cd "$PROJECT_DIR"
            return 0
        fi
    else
        log_info "갱신: $BEFORE → $AFTER"
    fi

    log_info "[2/3] npm install ..."
    npm install 2>&1 | tail -3

    log_info "[3/3] npm run build ..."
    npm run build 2>&1 | tail -3

    cd "$PROJECT_DIR"
    echo ""
    log_title "=========================================="
    log_title "  업그레이드 완료"
    log_title "=========================================="
    log_info "  $BEFORE → $AFTER"
    log_info "  빌드: $WEB_SEARCH_DIR/build/index.js"
    log_warn "VSCode 재시작 필요 (MCP 서버 재기동)"
    echo ""
}

case "${1:-check}" in
    check)   check_version ;;
    upgrade) do_upgrade ;;
    *)
        echo ""
        echo "사용법: bash $0 [check|upgrade]"
        echo "  check     git 로컬/원격 hash 비교 + 빌드 파일 존재 확인"
        echo "  upgrade   git pull + npm install + build"
        echo ""
        ;;
esac
