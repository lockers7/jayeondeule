#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Node.js 버전 확인 및 업그레이드
# -----------------------------------------
# 시스템 설치된 node 의 출처(NodeSource/snap/apt) 를 자동 감지하여 적절히 갱신.
# 기본은 NodeSource LTS (현재 v20.x). 사용자 글로벌 npm 패키지는 보존.
#
# 사용법:
#   bash setup/nodejs_upgrade.sh          # 버전 확인만
#   bash setup/nodejs_upgrade.sh check    # 버전 확인만
#   bash setup/nodejs_upgrade.sh upgrade  # apt 업그레이드 (NodeSource 가정)
# =========================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

NODESOURCE_LIST="/etc/apt/sources.list.d/nodesource.list"

check_installed() {
    if ! command -v node >/dev/null 2>&1; then
        log_error "node 가 설치되어 있지 않습니다."
        log_info "설치: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - && sudo apt-get install nodejs"
        exit 1
    fi
}

get_current_node() { node --version 2>/dev/null | sed 's/^v//'; }
get_current_npm()  { npm --version 2>/dev/null; }

get_source() {
    if [ -f "$NODESOURCE_LIST" ]; then echo "NodeSource"
    elif command -v snap >/dev/null 2>&1 && snap list 2>/dev/null | grep -qE '^node\b'; then echo "snap"
    else echo "apt(distro)"; fi
}

get_apt_candidate() {
    apt-cache policy nodejs 2>/dev/null | awk '/Candidate:/{print $2}'
}

check_version() {
    log_title "=========================================="
    log_title "  Node.js 버전 확인"
    log_title "=========================================="
    echo ""
    check_installed

    NODE_CUR=$(get_current_node)
    NPM_CUR=$(get_current_npm)
    SOURCE=$(get_source)

    log_info "현재 node: v$NODE_CUR"
    log_info "현재 npm:  $NPM_CUR"
    log_info "설치 출처: $SOURCE"
    echo ""

    log_info "apt 캐시 갱신 중..."
    sudo apt-get update -qq 2>&1 | tail -3 || true
    APT_CANDIDATE=$(get_apt_candidate)
    INSTALLED_DPKG=$(dpkg-query -W -f='${Version}' nodejs 2>/dev/null || echo "")

    log_info "apt 패키지(nodejs):"
    log_info "  설치됨: ${INSTALLED_DPKG:-확인불가}"
    log_info "  후보:   ${APT_CANDIDATE:-확인불가}"
    echo ""

    # NodeSource 라면 setup_*.x 스크립트로 메이저 업그레이드 가능
    if [ "$SOURCE" = "NodeSource" ]; then
        log_info "NodeSource LTS 메이저 업그레이드는 다음 명령:"
        log_info "  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -"
        log_info "  sudo apt-get install -y nodejs"
        echo ""
    fi

    if [ -n "$INSTALLED_DPKG" ] && [ -n "$APT_CANDIDATE" ] && [ "$INSTALLED_DPKG" = "$APT_CANDIDATE" ]; then
        log_info "이미 최신 패치 버전입니다."
        return 1
    fi
    log_warn "패치 업그레이드 가능: ${INSTALLED_DPKG:-?} → ${APT_CANDIDATE:-?}"
    log_info "업그레이드 실행: bash setup/nodejs_upgrade.sh upgrade"
}

do_upgrade() {
    log_title "=========================================="
    log_title "  Node.js 패치 업그레이드"
    log_title "=========================================="
    echo ""
    check_installed

    NODE_CUR=$(get_current_node)
    SOURCE=$(get_source)

    if [ "$SOURCE" = "snap" ]; then
        log_warn "snap 으로 설치된 node — apt 업그레이드 미적용"
        log_info "snap 갱신: sudo snap refresh node"
        exit 0
    fi

    log_info "[1/3] apt 캐시 갱신..."
    sudo apt-get update -qq 2>&1 | tail -3 || true

    log_info "[2/3] nodejs 패키지 업그레이드..."
    sudo DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade -y \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        nodejs 2>&1 | tail -10

    NEW_NODE=$(get_current_node)
    NEW_NPM=$(get_current_npm)
    log_info "업그레이드된 버전: node v$NEW_NODE / npm $NEW_NPM"

    log_info "[3/3] 동작 검증..."
    if node -e "console.log('OK')" >/dev/null 2>&1; then
        log_info "node 정상 동작"
    else
        log_error "node 실행 오류"
        exit 1
    fi

    echo ""
    log_title "=========================================="
    log_title "  업그레이드 완료"
    log_title "=========================================="
    log_info "  v$NODE_CUR → v$NEW_NODE"
    echo ""
}

case "${1:-check}" in
    check)   check_version ;;
    upgrade) do_upgrade ;;
    *)
        echo ""
        echo "사용법: bash $0 [check|upgrade]"
        echo "  check     설치 출처(NodeSource/apt/snap) 자동 감지 + 패치 후보"
        echo "  upgrade   apt 패치 업그레이드 (메이저는 setup_*.x 스크립트 안내만)"
        echo ""
        ;;
esac
