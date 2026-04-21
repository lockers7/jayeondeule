#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# PostgreSQL 버전 확인 및 업그레이드 (Ubuntu apt 기반)
# -----------------------------------------
# 동일 메이저 버전(예: 16.x → 16.y) 패치 업그레이드만 자동 수행.
# 메이저 업그레이드(16 → 17)는 클러스터 마이그레이션이 필요해 자동 스킵하고
# 수동 안내만 출력. 데이터(/var/lib/postgresql/<ver>/main) 는 절대 변경 안 함.
#
# 사용법:
#   bash setup/postgresql_upgrade.sh          # 버전 확인만
#   bash setup/postgresql_upgrade.sh check    # 버전 확인만
#   bash setup/postgresql_upgrade.sh upgrade  # 패치 업그레이드 실행
# =========================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

SERVICE="postgresql"

check_installed() {
    if ! command -v psql >/dev/null 2>&1; then
        log_error "postgresql 클라이언트 미설치"
        exit 1
    fi
}

get_major() {
    psql --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 | cut -d. -f1
}

get_current_full() {
    psql --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1
}

get_apt_pkg() {
    local major="$1"
    echo "postgresql-${major}"
}

get_apt_candidate() {
    local pkg="$1"
    apt-cache policy "$pkg" 2>/dev/null | awk '/Candidate:/{print $2}'
}

get_installed_dpkg() {
    local pkg="$1"
    dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || echo ""
}

check_version() {
    log_title "=========================================="
    log_title "  PostgreSQL 버전 확인"
    log_title "=========================================="
    echo ""
    check_installed

    MAJOR=$(get_major)
    CURRENT=$(get_current_full)
    PKG=$(get_apt_pkg "$MAJOR")

    log_info "현재 버전: $CURRENT (메이저 $MAJOR)"

    log_info "apt 캐시 갱신 중..."
    sudo apt-get update -qq 2>&1 | tail -3 || true

    INSTALLED_DPKG=$(get_installed_dpkg "$PKG")
    CANDIDATE=$(get_apt_candidate "$PKG")
    log_info "apt 패키지: $PKG"
    log_info "  설치됨: ${INSTALLED_DPKG:-확인불가}"
    log_info "  후보:   ${CANDIDATE:-확인불가}"
    echo ""

    if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
        log_info "$SERVICE 서비스: 실행 중"
    else
        log_warn "$SERVICE 서비스: 중지 상태"
    fi

    DATA_DIR="/var/lib/postgresql/$MAJOR/main"
    if [ -d "$DATA_DIR" ]; then
        SIZE=$(sudo du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}')
        log_info "데이터 디렉토리: $DATA_DIR (${SIZE:-?})"
    fi
    echo ""

    if [ -n "$INSTALLED_DPKG" ] && [ -n "$CANDIDATE" ] && [ "$INSTALLED_DPKG" = "$CANDIDATE" ]; then
        log_info "이미 최신 패치 버전입니다."
        return 1
    fi
    log_warn "패치 업그레이드 가능: ${INSTALLED_DPKG:-?} → ${CANDIDATE:-?}"
    log_info "업그레이드 실행: bash setup/postgresql_upgrade.sh upgrade"
    echo ""
    log_warn "⚠ 메이저 버전(예: $MAJOR → $((MAJOR + 1))) 업그레이드는 본 스크립트로 처리하지 않습니다."
    log_warn "   메이저 업그레이드는 pg_upgradecluster 또는 pg_dumpall 로 수동 진행."
}

do_upgrade() {
    log_title "=========================================="
    log_title "  PostgreSQL 패치 업그레이드"
    log_title "=========================================="
    echo ""
    check_installed

    MAJOR=$(get_major)
    CURRENT=$(get_current_full)
    PKG=$(get_apt_pkg "$MAJOR")
    INSTALLED_DPKG=$(get_installed_dpkg "$PKG")
    CANDIDATE=$(get_apt_candidate "$PKG")

    if [ -z "$CANDIDATE" ]; then
        log_error "apt 후보 버전 조회 실패"
        exit 1
    fi
    if [ "$INSTALLED_DPKG" = "$CANDIDATE" ]; then
        log_info "이미 최신 패치 버전입니다. ($INSTALLED_DPKG)"
        exit 0
    fi

    log_info "패치 업그레이드: $INSTALLED_DPKG → $CANDIDATE"
    echo ""

    # 1단계: 데이터 백업 안내 (자동 백업 안 함 — 용량이 큼)
    DATA_DIR="/var/lib/postgresql/$MAJOR/main"
    log_info "[1/4] 데이터 디렉토리 안내..."
    if [ -d "$DATA_DIR" ]; then
        SIZE=$(sudo du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}')
        log_info "  $DATA_DIR (${SIZE:-?})"
        log_info "  → 패치 업그레이드는 데이터 디렉토리 변경 없음 (in-place)"
        log_warn "  → 안전 백업이 필요하면 미리 pg_dumpall 권장:"
        log_warn "      sudo -u postgres pg_dumpall > /backup/pg_\$(date +%Y%m%d_%H%M%S).sql"
    fi

    # 2단계: 서비스 중지
    log_info "[2/4] $SERVICE 서비스 중지..."
    if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
        sudo systemctl stop "$SERVICE"
        sleep 2
        log_info "서비스 중지 완료"
    else
        log_warn "서비스가 실행 중이 아님"
    fi

    # 3단계: apt 패치 적용
    log_info "[3/4] apt 패치 업그레이드..."
    sudo DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade -y \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        "$PKG" "postgresql-client-${MAJOR}" "postgresql-client-common" "postgresql-common" 2>&1 | tail -10

    NEW=$(get_current_full)
    log_info "업그레이드된 버전: $NEW"

    # 4단계: 서비스 시작 + 헬스체크
    log_info "[4/4] $SERVICE 시작 + 헬스체크..."
    sudo systemctl start "$SERVICE"
    sleep 3

    RETRY=0
    while [ $RETRY -lt 12 ]; do
        if sudo -u postgres psql -c "SELECT 1" >/dev/null 2>&1; then
            log_info "PostgreSQL 정상 동작 확인 (psql SELECT 1 OK)"
            break
        fi
        RETRY=$((RETRY + 1))
        log_warn "응답 대기... ($RETRY/12)"
        sleep 5
    done
    if [ $RETRY -ge 12 ]; then
        log_error "PostgreSQL 가 응답하지 않습니다 — sudo journalctl -u $SERVICE -n 50"
        exit 1
    fi

    echo ""
    log_title "=========================================="
    log_title "  업그레이드 완료"
    log_title "=========================================="
    log_info "  $CURRENT → $NEW"
    echo ""
}

case "${1:-check}" in
    check)   check_version ;;
    upgrade) do_upgrade ;;
    *)
        echo ""
        echo "사용법: bash $0 [check|upgrade]"
        echo "  check     동일 메이저 패치 업그레이드 후보 표시"
        echo "  upgrade   apt 패치 업그레이드 + 서비스 재시작"
        echo ""
        echo "주의: 메이저 업그레이드(예: 16→17)는 본 스크립트 미지원"
        echo "      pg_upgradecluster 로 수동 진행 필요"
        echo ""
        ;;
esac
