#!/bin/bash
# =========================================================================
# [5단계] 설정 파일 배치 + SSL 인증서 + SearXNG + 심볼릭 링크
# Nginx, Systemd, PostgreSQL, SSL, SearXNG, agriAiCore 링크
# =========================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$PROJECT_DIR/setup/system-configs"

echo "=========================================="
echo "  [5단계] 설정 파일 배치"
echo "=========================================="
echo ""

# -----------------------------------------------------------------
# 1. Nginx 설정
# -----------------------------------------------------------------
log_info "[1/6] Nginx 설정 배치..."
for conf in jayeondeule_web fastapi; do
    if [ -f "$CONFIG_DIR/nginx/$conf" ]; then
        sudo cp "$CONFIG_DIR/nginx/$conf" "/etc/nginx/sites-available/$conf"
        sudo ln -sf "/etc/nginx/sites-available/$conf" "/etc/nginx/sites-enabled/$conf"
        log_info "  $conf 배치 완료"
    fi
done
sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# -----------------------------------------------------------------
# 2. SSL 자체 서명 인증서 생성
# -----------------------------------------------------------------
log_info "[2/6] SSL 인증서 생성..."
SSL_DIR="/etc/nginx/ssl"
if [ ! -f "$SSL_DIR/selfsigned.crt" ]; then
    sudo mkdir -p "$SSL_DIR"
    sudo openssl req -x509 -nodes -days 3650 \
        -newkey rsa:2048 \
        -keyout "$SSL_DIR/selfsigned.key" \
        -out "$SSL_DIR/selfsigned.crt" \
        -subj "/CN=lockers7.iptime.org" 2>/dev/null
    log_info "  SSL 인증서 생성 완료 (10년)"
else
    log_info "  SSL 인증서 이미 존재"
fi

sudo nginx -t 2>/dev/null && log_info "  Nginx 설정 검증 OK"

# -----------------------------------------------------------------
# 3. Systemd 서비스 배치
# -----------------------------------------------------------------
log_info "[3/6] Systemd 서비스 배치..."
for svc in agriAiCore ollama chromadb jayeondeule_web; do
    if [ -f "$CONFIG_DIR/systemd/${svc}.service" ]; then
        sudo cp "$CONFIG_DIR/systemd/${svc}.service" "/etc/systemd/system/"
        log_info "  ${svc}.service 배치 완료"
    fi
done
sudo systemctl daemon-reload

# -----------------------------------------------------------------
# 4. PostgreSQL 설정
# -----------------------------------------------------------------
log_info "[4/6] PostgreSQL 설정 배치..."
PG_DIR="/etc/postgresql/16/main"
if [ -d "$PG_DIR" ]; then
    for conf in postgresql.conf pg_hba.conf; do
        if [ -f "$CONFIG_DIR/postgresql/$conf" ]; then
            sudo cp "$PG_DIR/$conf" "$PG_DIR/${conf}.bak" 2>/dev/null || true
            sudo cp "$CONFIG_DIR/postgresql/$conf" "$PG_DIR/$conf"
            sudo chown postgres:postgres "$PG_DIR/$conf"
            log_info "  $conf 배치 완료"
        fi
    done
    sudo systemctl restart postgresql
fi

# -----------------------------------------------------------------
# 5. SearXNG Docker 시작
# -----------------------------------------------------------------
log_info "[5/6] SearXNG Docker 시작..."
SEARXNG_DIR="$PROJECT_DIR/setup/searxng"
if [ -f "$SEARXNG_DIR/docker-compose.yml" ]; then
    cd "$SEARXNG_DIR"
    sudo docker compose up -d 2>&1 | tail -3
    cd "$PROJECT_DIR"
    log_info "  SearXNG 시작 완료"
else
    log_warn "  SearXNG docker-compose.yml 없음"
fi

# -----------------------------------------------------------------
# 6. agriAiCore 심볼릭 링크 + 실행 권한
# -----------------------------------------------------------------
log_info "[6/6] agriAiCore 링크 설정..."
CTRL_SCRIPT="$PROJECT_DIR/setup/agriCoreCtrl.sh"
LINK_PATH="$PROJECT_DIR/agriAiCore"

if [ -f "$CTRL_SCRIPT" ]; then
    chmod +x "$CTRL_SCRIPT"
    ln -sf "$CTRL_SCRIPT" "$LINK_PATH" 2>/dev/null || true
    log_info "  agriAiCore → agriCoreCtrl.sh 링크 완료"
fi

# 필수 디렉터리 생성
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/upload" "$PROJECT_DIR/download"
log_info "  logs/, upload/, download/ 디렉터리 확인"

echo ""
echo "=========================================="
log_info "[5단계] 설정 배치 완료"
echo "=========================================="
echo ""
log_info "다음 단계: bash setup/system-configs/restore.sh data"
echo ""
