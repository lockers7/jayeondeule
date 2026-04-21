#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Nginx 버전 확인 및 업그레이드 스크립트 (Ubuntu apt 기반)
# -----------------------------------------
# /usr/sbin/nginx + systemd nginx.service 를 apt 패키지 매니저로 갱신.
# 설정 파일(/etc/nginx/) 은 변경하지 않음. dpkg conffile prompt 는 유지.
#
# 사용법:
#   bash setup/nginx_upgrade.sh          # 버전 확인만
#   bash setup/nginx_upgrade.sh check    # 버전 확인만
#   bash setup/nginx_upgrade.sh upgrade  # apt 업그레이드 실행
# =========================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}$1${NC}"; }

PKG="nginx"
SERVICE="nginx"

check_installed() {
    if ! command -v nginx >/dev/null 2>&1; then
        log_error "nginx 가 설치되어 있지 않습니다."
        log_info "설치: sudo apt-get install nginx"
        exit 1
    fi
}

get_current() {
    nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}

get_apt_candidate() {
    apt-cache policy "$PKG" 2>/dev/null | awk '/Candidate:/{print $2}'
}

check_version() {
    log_title "=========================================="
    log_title "  Nginx 버전 확인"
    log_title "=========================================="
    echo ""
    check_installed

    CURRENT=$(get_current)
    log_info "현재 버전: $CURRENT"

    log_info "apt 캐시 갱신 중..."
    sudo apt-get update -qq 2>&1 | tail -3 || true

    CANDIDATE=$(get_apt_candidate)
    log_info "apt 후보 버전: ${CANDIDATE:-확인불가}"
    echo ""

    if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
        log_info "$SERVICE 서비스: 실행 중"
    else
        log_warn "$SERVICE 서비스: 중지 상태"
    fi

    if [ -d /etc/nginx ]; then
        SITES_ENABLED=$(ls /etc/nginx/sites-enabled 2>/dev/null | wc -l)
        log_info "설정 파일: /etc/nginx/  (sites-enabled: $SITES_ENABLED 개)"
    fi
    echo ""

    INSTALLED_FULL=$(dpkg-query -W -f='${Version}' "$PKG" 2>/dev/null || echo "")
    if [ -n "$INSTALLED_FULL" ] && [ -n "$CANDIDATE" ] && [ "$INSTALLED_FULL" = "$CANDIDATE" ]; then
        log_info "이미 최신 버전입니다."
        return 1
    fi
    log_warn "업그레이드 가능: ${INSTALLED_FULL:-?} → ${CANDIDATE:-?}"
    log_info "업그레이드 실행: bash setup/nginx_upgrade.sh upgrade"
}

do_upgrade() {
    log_title "=========================================="
    log_title "  Nginx 업그레이드"
    log_title "=========================================="
    echo ""
    check_installed

    CURRENT=$(get_current)
    log_info "[1/4] 설정 검증 (nginx -t)..."
    if ! sudo nginx -t 2>&1 | tail -3; then
        log_error "현재 설정에 오류 — 업그레이드 중단"
        exit 1
    fi

    log_info "[2/4] apt 캐시 갱신..."
    sudo apt-get update -qq 2>&1 | tail -3 || true

    log_info "[3/4] nginx 패키지 업그레이드..."
    # conffile prompt 는 기본값(N) — 사용자 설정 보존
    sudo DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade -y \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        "$PKG" 2>&1 | tail -10

    NEW=$(get_current)
    log_info "업그레이드된 버전: $NEW"

    log_info "[4/4] 서비스 재시작 + 검증..."
    sudo nginx -t 2>&1 | tail -3 || {
        log_error "새 설정 검증 실패 — 서비스 미재시작"
        exit 1
    }
    sudo systemctl restart "$SERVICE"
    sleep 2

    if systemctl is-active --quiet "$SERVICE"; then
        log_info "nginx 정상 동작 확인"
    else
        log_error "nginx 재시작 실패 — sudo journalctl -u nginx -n 50 확인"
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
        echo "  check     현재/apt 후보 버전 비교 + 서비스 상태"
        echo "  upgrade   apt 패키지 갱신 + 서비스 재시작 (설정 파일 보존)"
        echo ""
        ;;
esac
