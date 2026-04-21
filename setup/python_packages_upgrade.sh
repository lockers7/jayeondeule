#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Python venv 패키지 일괄 업그레이드 (PyPI)
# -----------------------------------------
# 프로젝트 venv 의 outdated 패키지를 일괄 또는 선택적으로 갱신.
# chromadb 는 별도 스크립트(chromadb_upgrade.sh)에서 서비스 재시작까지 처리
# 하므로 이 스크립트에서는 기본 제외.
#
# 사용법:
#   bash setup/python_packages_upgrade.sh                  # outdated 목록 + 안내
#   bash setup/python_packages_upgrade.sh check            # outdated 목록만
#   bash setup/python_packages_upgrade.sh upgrade          # 일괄 업그레이드 (chromadb 제외)
#   bash setup/python_packages_upgrade.sh upgrade-all      # chromadb 포함 전체
#   bash setup/python_packages_upgrade.sh upgrade <pkg>    # 특정 패키지만
# =========================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIP="$PROJECT_DIR/venv/bin/pip"
PYTHON="$PROJECT_DIR/venv/bin/python"

# 다른 전용 스크립트가 처리하는 패키지 — 일괄 upgrade 에서 제외
EXCLUDE_PKGS=("chromadb")

check_venv() {
    if [ ! -f "$PIP" ]; then
        log_error "venv 가 존재하지 않습니다: $PIP"
        log_info "설치: bash setup/3.requirement.sh"
        exit 1
    fi
}

get_outdated_json() {
    "$PIP" list --outdated --format=json 2>/dev/null
}

check_version() {
    log_title "=========================================="
    log_title "  Python venv 패키지 — outdated 목록"
    log_title "=========================================="
    echo ""
    check_venv

    log_info "Python: $("$PYTHON" --version 2>&1)"
    log_info "pip:    $("$PIP" --version 2>&1 | awk '{print $2}')"
    log_info "venv:   $PROJECT_DIR/venv"
    echo ""

    log_info "outdated 패키지 조회 중..."
    OUTDATED=$(get_outdated_json)
    if [ -z "$OUTDATED" ] || [ "$OUTDATED" = "[]" ]; then
        log_info "모든 패키지가 최신 버전입니다."
        return 1
    fi

    "$PYTHON" -c "
import json,sys
data = json.loads('''$OUTDATED''')
exclude = set([${EXCLUDE_PKGS[@]@Q}])
print(f'  {len(data)}개 패키지가 outdated:')
print()
print(f'  {\"NAME\":<35} {\"CURRENT\":<15} → {\"LATEST\"}')
print(f'  {\"-\"*35} {\"-\"*15} {\"-\"*15}')
for p in sorted(data, key=lambda x: x['name'].lower()):
    mark = '  (별도 스크립트)' if p['name'].lower() in {e.lower() for e in exclude} else ''
    print(f'  {p[\"name\"]:<35} {p[\"version\"]:<15} → {p[\"latest_version\"]}{mark}')
" 2>/dev/null || echo "$OUTDATED"

    echo ""
    log_warn "일괄 업그레이드: bash setup/python_packages_upgrade.sh upgrade"
    log_warn "전체 (chromadb 포함): bash setup/python_packages_upgrade.sh upgrade-all"
    log_warn "특정 패키지: bash setup/python_packages_upgrade.sh upgrade <pkg-name>"
}

do_upgrade_single() {
    local pkg="$1"
    log_title "=========================================="
    log_title "  $pkg 단일 업그레이드"
    log_title "=========================================="
    echo ""
    check_venv

    log_info "[1/2] 업그레이드 실행..."
    "$PIP" install --upgrade "$pkg" 2>&1 | tail -5

    NEW=$("$PIP" show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    log_info "[2/2] 새 버전: $NEW"
    echo ""
    log_warn "운영 서비스 영향이 있는 패키지는 별도 재시작 필요"
    log_warn "  예: sudo ./agriAiCore restart 4   (Scheduler)"
    log_warn "      sudo ./agriAiCore restart 5   (FastAPI)"
}

do_upgrade_bulk() {
    local include_excluded="${1:-no}"

    log_title "=========================================="
    log_title "  Python venv 일괄 업그레이드"
    log_title "=========================================="
    echo ""
    check_venv

    OUTDATED=$(get_outdated_json)
    if [ -z "$OUTDATED" ] || [ "$OUTDATED" = "[]" ]; then
        log_info "모든 패키지가 최신 버전입니다."
        exit 0
    fi

    # 제외 패키지 처리
    PKG_LIST=$("$PYTHON" -c "
import json
data = json.loads('''$OUTDATED''')
exclude = set([${EXCLUDE_PKGS[@]@Q}]) if '$include_excluded' != 'yes' else set()
names = [p['name'] for p in data if p['name'].lower() not in {e.lower() for e in exclude}]
print(' '.join(names))
")

    if [ -z "$PKG_LIST" ]; then
        log_info "업그레이드할 패키지 없음 (모두 별도 스크립트 관리)"
        exit 0
    fi

    log_info "대상 패키지: $PKG_LIST"
    echo ""
    log_info "[1/2] pip install --upgrade ..."
    # shellcheck disable=SC2086
    "$PIP" install --upgrade $PKG_LIST 2>&1 | tail -20

    log_info "[2/2] 결과 검증..."
    NEW_OUTDATED=$(get_outdated_json | "$PYTHON" -c "
import json,sys
data = json.load(sys.stdin)
exclude = set([${EXCLUDE_PKGS[@]@Q}]) if '$include_excluded' != 'yes' else set()
remain = [p for p in data if p['name'].lower() not in {e.lower() for e in exclude}]
print(len(remain))
" 2>/dev/null)
    log_info "남은 outdated: ${NEW_OUTDATED:-0} 개"

    echo ""
    log_title "=========================================="
    log_title "  일괄 업그레이드 완료"
    log_title "=========================================="
    if [ "$include_excluded" != "yes" ]; then
        log_warn "chromadb 는 별도 스크립트로: bash setup/chromadb_upgrade.sh upgrade"
    fi
    log_warn "운영 서비스 재시작 필요:"
    log_warn "  sudo ./agriAiCore restart 4   (Scheduler)"
    log_warn "  sudo ./agriAiCore restart 5   (FastAPI)"
    echo ""
}

case "${1:-check}" in
    check)
        check_version
        ;;
    upgrade)
        if [ -n "$2" ]; then
            do_upgrade_single "$2"
        else
            do_upgrade_bulk no
        fi
        ;;
    upgrade-all)
        do_upgrade_bulk yes
        ;;
    *)
        echo ""
        echo "사용법: bash $0 [명령어] [패키지]"
        echo ""
        echo "명령어:"
        echo "  check                 outdated 목록 표시 (기본)"
        echo "  upgrade               일괄 업그레이드 (chromadb 제외)"
        echo "  upgrade <pkg>         특정 패키지만 업그레이드"
        echo "  upgrade-all           전체 업그레이드 (chromadb 포함)"
        echo ""
        echo "예시:"
        echo "  bash $0"
        echo "  bash $0 upgrade"
        echo "  bash $0 upgrade fastapi"
        echo ""
        ;;
esac
