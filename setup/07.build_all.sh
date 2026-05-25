#!/bin/bash
# =========================================================================
# [7단계] 전체 프로젝트 빌드
# Python venv + Spring Boot + React 프론트엔드(web + shop) + MCP
# =========================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OWNER=$(stat -c '%U' "$PROJECT_DIR")

echo "=========================================="
echo "  [7단계] 전체 프로젝트 빌드"
echo "=========================================="
echo ""

# -----------------------------------------------------------------
# 1. Python venv + 패키지
# -----------------------------------------------------------------
log_info "[1/5] Python venv + 패키지 설치..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
fi
"$PROJECT_DIR/venv/bin/pip" install -q --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"
log_info "  Python 패키지 $(pip list --format=columns 2>/dev/null | tail -n +3 | wc -l)개 설치 완료"

# -----------------------------------------------------------------
# 2. Spring Boot 빌드
# -----------------------------------------------------------------
log_info "[2/5] Spring Boot 빌드..."
BACKEND_DIR="$PROJECT_DIR/web/backend"
if [ -f "$BACKEND_DIR/mvnw" ]; then
    cd "$BACKEND_DIR"
    chmod +x mvnw
    ./mvnw package -DskipTests -q 2>&1 | tail -3
    cd "$PROJECT_DIR"
    if [ -f "$BACKEND_DIR/target/smartfarm-0.0.1-SNAPSHOT.jar" ]; then
        log_info "  Spring Boot JAR 빌드 완료"
    else
        log_error "  Spring Boot 빌드 실패"
    fi
else
    log_warn "  mvnw 없음 (건너뜀)"
fi

# -----------------------------------------------------------------
# 3. Web 프론트엔드 빌드
# -----------------------------------------------------------------
log_info "[3/5] Web 프론트엔드 빌드..."
WEB_FRONTEND="$PROJECT_DIR/web/frontend"
if [ -f "$WEB_FRONTEND/package.json" ]; then
    cd "$WEB_FRONTEND"
    npm install --silent 2>&1 | tail -3
    npm run build 2>&1 | tail -3
    cd "$PROJECT_DIR"
    log_info "  Web 프론트엔드 빌드 완료"
else
    log_warn "  web/frontend/package.json 없음"
fi

# -----------------------------------------------------------------
# 4. Shop 프론트엔드 빌드
# -----------------------------------------------------------------
log_info "[4/5] Shop 프론트엔드 빌드..."
SHOP_FRONTEND="$PROJECT_DIR/shop/frontend"
if [ -f "$SHOP_FRONTEND/package.json" ]; then
    cd "$SHOP_FRONTEND"
    npm install --silent 2>&1 | tail -3
    npm run build 2>&1 | tail -3
    cd "$PROJECT_DIR"
    log_info "  Shop 프론트엔드 빌드 완료"
else
    log_warn "  shop/frontend/package.json 없음"
fi

# -----------------------------------------------------------------
# 5. MCP web-search 빌드
# -----------------------------------------------------------------
log_info "[5/5] MCP web-search 빌드..."
MCP_DIR="$PROJECT_DIR/.mcp/web-search"
if [ -f "$MCP_DIR/package.json" ]; then
    cd "$MCP_DIR"
    npm install --silent 2>&1 | tail -3
    npm run build 2>&1 | tail -3
    cd "$PROJECT_DIR"
    log_info "  MCP web-search 빌드 완료"
else
    log_info "  MCP web-search 없음 (건너뜀)"
fi

echo ""
echo "=========================================="
log_info "[7단계] 빌드 완료"
echo "=========================================="
echo ""
log_info "다음 단계: bash setup/8.start_services.sh"
echo ""
