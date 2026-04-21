#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# MCP 서버 업그레이드 — 4개 개별 스크립트 wrapper
# -----------------------------------------
# 개별 패키지별 스크립트:
#   setup/mcp_postgres_upgrade.sh
#   setup/mcp_filesystem_upgrade.sh
#   setup/mcp_fetch_upgrade.sh
#   setup/mcp_web_search_upgrade.sh
#
# 본 스크립트는 4개를 일괄 호출하는 편의 wrapper.
#
# 사용법:
#   bash setup/mcp_upgrade.sh           # 4개 모두 check
#   bash setup/mcp_upgrade.sh check     # 4개 모두 check
#   bash setup/mcp_upgrade.sh upgrade   # 4개 모두 upgrade
# =========================================================================

set -e

CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_title() { echo -e "${CYAN}$1${NC}"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

SETUP_DIR="$(cd "$(dirname "$0")" && pwd)"

SCRIPTS=(
    "mcp_postgres_upgrade.sh"
    "mcp_filesystem_upgrade.sh"
    "mcp_fetch_upgrade.sh"
    "mcp_web_search_upgrade.sh"
)

run_all() {
    local cmd="$1"
    for s in "${SCRIPTS[@]}"; do
        echo ""
        log_title "▶ $s $cmd"
        bash "$SETUP_DIR/$s" "$cmd" || log_warn "$s 실패 — 다음 패키지 계속"
    done
    echo ""
    log_title "=========================================="
    log_title "  MCP 일괄 $cmd 완료"
    log_title "=========================================="
    if [ "$cmd" = "upgrade" ]; then
        log_warn "VSCode 재시작 필요 (MCP 서버 모두 재기동)"
    fi
    echo ""
}

case "${1:-check}" in
    check)   run_all check ;;
    upgrade) run_all upgrade ;;
    *)
        echo ""
        echo "사용법: bash $0 [check|upgrade]"
        echo ""
        echo "본 wrapper 가 호출하는 개별 스크립트:"
        for s in "${SCRIPTS[@]}"; do
            echo "  - setup/$s"
        done
        echo ""
        echo "특정 패키지만 작업하려면 개별 스크립트 직접 실행:"
        echo "  bash setup/mcp_postgres_upgrade.sh check"
        echo ""
        ;;
esac
