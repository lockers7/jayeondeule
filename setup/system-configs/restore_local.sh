#!/bin/bash
# =========================================================================
# AgriAI Core 전체 시스템 로컬 복원 스크립트
# =========================================================================
# backup_local.sh로 생성된 .backup/ 폴더를 이용하여
# 신규 Linux 서버에서 agriAiCore를 즉시 실행 가능하도록 복원합니다.
#
# 이 스크립트는 .backup/ 폴더 내에 포함되어 있으므로
# 신규 서버에서 .backup/ 만 복사하면 바로 실행 가능합니다.
#
# 복원 원본: /workspace/jayeondeule/.backup/
#
# 사용법:
#   sudo bash /workspace/jayeondeule/.backup/restore_local.sh all
#
# 단계별 실행:
#   sudo bash restore_local.sh check          # 1단계: 사전 확인
#   sudo bash restore_local.sh install-deps    # 2단계: 패키지 설치
#   sudo bash restore_local.sh deploy-source   # 3단계: 소스코드 배치
#   sudo bash restore_local.sh deploy-configs  # 4단계: 설정 파일 배치
#   sudo bash restore_local.sh restore-data    # 5단계: 데이터 복원
#   sudo bash restore_local.sh build           # 6단계: 빌드
#   sudo bash restore_local.sh services        # 7단계: 서비스 활성화
# =========================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }
log_step()  { echo -e "\n${BOLD}$1${NC}"; }
log_ok()    { echo -e "${GREEN}  ✓${NC} $1"; }
log_fail()  { echo -e "${RED}  ✗${NC} $1"; }

# =========================================================================
# 경로 설정 — 이 스크립트 위치 기준으로 백업 루트 결정
# =========================================================================
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)"

# restore_local.sh가 .backup/ 안에 있으면 그 디렉토리가 BACKUP_ROOT
# setup/system-configs/ 안에 있으면 PROJECT_DIR/.backup
if [ -d "$SCRIPT_PATH/source" ] && [ -d "$SCRIPT_PATH/configs" ]; then
    BACKUP_ROOT="$SCRIPT_PATH"
else
    BACKUP_ROOT="/workspace/jayeondeule/.backup"
fi

PROJECT_DIR="/workspace/jayeondeule"
OWNER="jayeondeule"

CONFIGS_DIR="$BACKUP_ROOT/configs"
NGINX_DIR="$CONFIGS_DIR/nginx"
SYSTEMD_DIR="$CONFIGS_DIR/systemd"
PG_CONF_DIR="$CONFIGS_DIR/postgresql"
DATA_DIR="$BACKUP_ROOT/data"
SOURCE_DIR="$BACKUP_ROOT/source"
PYTHON_DIR="$BACKUP_ROOT/python"
UPLOAD_DIR="$BACKUP_ROOT/upload"
OLLAMA_DIR="$BACKUP_ROOT/ollama"

SUCCESS=0
FAIL=0

# =========================================================================
# sudo 확인
# =========================================================================
ensure_sudo() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "이 스크립트는 sudo 권한이 필요합니다."
        echo "  사용법: sudo bash $0 [명령어]"
        exit 1
    fi
}

# .env에서 DB 접속정보 로드 (소스 배치 후 사용 가능)
load_env() {
    local ENV_FILE=""
    if [ -f "$PROJECT_DIR/.env" ]; then
        ENV_FILE="$PROJECT_DIR/.env"
    elif [ -f "$SOURCE_DIR/.env" ]; then
        ENV_FILE="$SOURCE_DIR/.env"
    fi
    if [ -n "$ENV_FILE" ]; then
        PGDB_HOST=$(grep "^PGDB_HOST=" "$ENV_FILE" | cut -d'=' -f2)
        PGDB_PORT=$(grep "^PGDB_PORT=" "$ENV_FILE" | cut -d'=' -f2)
        PGDB_DATABASE=$(grep "^PGDB_DATABASE=" "$ENV_FILE" | cut -d'=' -f2)
        PGDB_USER=$(grep "^PGDB_USER=" "$ENV_FILE" | cut -d'=' -f2)
        PGDB_PASSWORD=$(grep "^PGDB_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2)
    fi
}

# =========================================================================
# [1/7] 사전 확인
# =========================================================================
check_prerequisites() {
    log_title "=========================================="
    log_title "  [1/7] 사전 요구사항 확인"
    log_title "=========================================="

    # OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        log_info "OS: $PRETTY_NAME"
    fi

    # 사용자
    if id "$OWNER" &>/dev/null; then
        log_ok "사용자 '$OWNER': 존재함"
    else
        log_warn "사용자 '$OWNER': 없음 — install-deps 단계에서 자동 생성됩니다."
    fi

    # 백업 디렉토리
    if [ -d "$BACKUP_ROOT" ]; then
        log_ok "백업 디렉토리: $BACKUP_ROOT"
    else
        log_fail "백업 디렉토리 없음: $BACKUP_ROOT"
        return
    fi

    # 백업 항목 확인
    log_step "[ 백업 파일 상태 ]"

    local CHECK_DIRS=(
        "$SOURCE_DIR:소스코드"
        "$NGINX_DIR:Nginx 설정"
        "$SYSTEMD_DIR:Systemd 서비스"
        "$PG_CONF_DIR:PostgreSQL 설정"
        "$DATA_DIR:데이터 (DB+ChromaDB)"
        "$PYTHON_DIR:Python 패키지 목록"
    )

    for item in "${CHECK_DIRS[@]}"; do
        local fpath="${item%%:*}"
        local label="${item##*:}"
        if [ -d "$fpath" ]; then
            local size=$(du -sh "$fpath" | awk '{print $1}')
            log_ok "$label ($size)"
        else
            log_fail "$label: 없음"
        fi
    done

    local CHECK_FILES=(
        "$DATA_DIR/postgresql_dump.sql:PostgreSQL DB 덤프"
        "$PYTHON_DIR/requirements.txt:Python 패키지 목록"
        "$OLLAMA_DIR/models.txt:Ollama 모델 목록"
    )

    for item in "${CHECK_FILES[@]}"; do
        local fpath="${item%%:*}"
        local label="${item##*:}"
        if [ -f "$fpath" ]; then
            local size=$(ls -lh "$fpath" | awk '{print $5}')
            log_ok "$label ($size)"
        else
            log_warn "$label: 없음"
        fi
    done

    # 패키지 확인
    log_step "[ 설치된 패키지 ]"

    local COMMANDS=("nginx" "psql" "java" "python3" "node" "npm" "docker" "ollama" "rsync")
    local LABELS=("Nginx" "PostgreSQL" "Java" "Python 3" "Node.js" "npm" "Docker" "Ollama" "rsync")

    for i in "${!COMMANDS[@]}"; do
        if command -v "${COMMANDS[$i]}" &>/dev/null; then
            log_ok "${LABELS[$i]}: 설치됨"
        else
            log_warn "${LABELS[$i]}: 미설치"
        fi
    done
}

# =========================================================================
# [2/7] 필수 패키지 설치
# =========================================================================
install_dependencies() {
    log_title "=========================================="
    log_title "  [2/7] 필수 패키지 설치"
    log_title "=========================================="

    # --- 사용자 생성 ---
    if ! id "$OWNER" &>/dev/null; then
        log_info "사용자 '$OWNER' 생성 중..."
        adduser --disabled-password --gecos "" "$OWNER" 2>/dev/null || useradd -m "$OWNER" 2>/dev/null
        log_ok "사용자 '$OWNER' 생성"
    else
        log_ok "사용자 '$OWNER': 이미 존재"
    fi

    # --- 프로젝트 디렉토리 생성 ---
    if [ ! -d "$PROJECT_DIR" ]; then
        mkdir -p "$PROJECT_DIR"
        chown "$OWNER:$OWNER" "$PROJECT_DIR"
        log_ok "프로젝트 디렉토리 생성: $PROJECT_DIR"
    fi

    # --- apt 업데이트 ---
    log_info "apt 패키지 업데이트 중..."
    apt-get update -qq 2>/dev/null

    # --- 기본 도구 ---
    log_info "기본 도구 설치 중..."
    apt-get install -y -qq rsync curl wget git > /dev/null 2>&1
    log_ok "rsync, curl, wget, git"

    # --- Nginx ---
    log_info "Nginx 설치 중..."
    apt-get install -y -qq nginx > /dev/null 2>&1
    if command -v nginx &>/dev/null; then
        log_ok "Nginx: $(nginx -v 2>&1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "Nginx 설치 실패"
        FAIL=$((FAIL + 1))
    fi

    # --- PostgreSQL 16 ---
    log_info "PostgreSQL 설치 중..."
    if ! command -v psql &>/dev/null; then
        # PostgreSQL 공식 저장소 추가 시도
        if ! apt-get install -y -qq postgresql-16 postgresql-client-16 > /dev/null 2>&1; then
            log_info "PostgreSQL 공식 저장소 추가 중..."
            sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' 2>/dev/null
            wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - 2>/dev/null
            apt-get update -qq 2>/dev/null
            apt-get install -y -qq postgresql-16 postgresql-client-16 > /dev/null 2>&1
        fi
    fi
    if command -v psql &>/dev/null; then
        log_ok "PostgreSQL: $(psql --version 2>&1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "PostgreSQL 설치 실패"
        FAIL=$((FAIL + 1))
    fi

    # --- Java 21 ---
    log_info "Java 21 설치 중..."
    if ! command -v java &>/dev/null; then
        apt-get install -y -qq openjdk-21-jdk-headless > /dev/null 2>&1
    fi
    if command -v java &>/dev/null; then
        log_ok "Java: $(java -version 2>&1 | head -1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "Java 설치 실패"
        FAIL=$((FAIL + 1))
    fi

    # --- Python 3 + venv ---
    log_info "Python 3 설치 중..."
    apt-get install -y -qq python3 python3-venv python3-pip python3-dev build-essential > /dev/null 2>&1
    if command -v python3 &>/dev/null; then
        log_ok "Python: $(python3 --version 2>&1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "Python 설치 실패"
        FAIL=$((FAIL + 1))
    fi

    # --- Node.js 20 ---
    log_info "Node.js 설치 중..."
    if ! command -v node &>/dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
        apt-get install -y -qq nodejs > /dev/null 2>&1
    fi
    if command -v node &>/dev/null; then
        log_ok "Node.js: $(node --version 2>&1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "Node.js 설치 실패"
        FAIL=$((FAIL + 1))
    fi

    # --- Docker ---
    log_info "Docker 설치 중..."
    if ! command -v docker &>/dev/null; then
        apt-get install -y -qq docker.io docker-compose-plugin > /dev/null 2>&1
    fi
    if command -v docker &>/dev/null; then
        log_ok "Docker: $(docker --version 2>&1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_warn "Docker 설치 실패 (SearXNG 사용 불가)"
    fi

    # --- Ollama ---
    log_info "Ollama 설치 중..."
    if ! command -v ollama &>/dev/null; then
        curl -fsSL https://ollama.com/install.sh | sh > /dev/null 2>&1
    fi
    if command -v ollama &>/dev/null; then
        log_ok "Ollama: $(ollama --version 2>&1)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_warn "Ollama 자동 설치 실패. 수동 설치:"
        echo "    curl -fsSL https://ollama.com/install.sh | sh"
    fi
}

# =========================================================================
# [3/7] 소스코드 배치
# =========================================================================
deploy_source() {
    log_title "=========================================="
    log_title "  [3/7] 소스코드 배치"
    log_title "=========================================="

    if [ ! -d "$SOURCE_DIR" ]; then
        log_fail "소스 백업 없음: $SOURCE_DIR"
        FAIL=$((FAIL + 1))
        return
    fi

    mkdir -p "$PROJECT_DIR"

    log_info "소스코드 복사 중..."
    rsync -a \
        --exclude='.backup' \
        "$SOURCE_DIR/" "$PROJECT_DIR/"

    if [ $? -eq 0 ]; then
        local SIZE=$(du -sh "$PROJECT_DIR" --exclude='.backup' | awk '{print $1}')
        log_ok "소스코드 배치 완료 ($SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "소스코드 복사 실패"
        FAIL=$((FAIL + 1))
    fi

    # .env 확인
    if [ -f "$PROJECT_DIR/.env" ]; then
        log_ok ".env 파일 존재"
    else
        log_warn ".env 파일 없음 — 수동 생성 필요"
    fi

    # 소유권 설정
    chown -R "$OWNER:$OWNER" "$PROJECT_DIR"
    log_ok "소유권 설정: $OWNER:$OWNER"

    # 실행 권한
    chmod +x "$PROJECT_DIR/agriAiCore" 2>/dev/null
    chmod +x "$PROJECT_DIR/setup/run_services.sh" 2>/dev/null

    # 필수 디렉토리 생성
    mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/upload" "$PROJECT_DIR/download"
    mkdir -p "$PROJECT_DIR/.ollama/models"
    mkdir -p "$PROJECT_DIR/chromadb"
    chown -R "$OWNER:$OWNER" "$PROJECT_DIR/logs" "$PROJECT_DIR/upload" "$PROJECT_DIR/download"
    chown -R "$OWNER:$OWNER" "$PROJECT_DIR/.ollama" "$PROJECT_DIR/chromadb"
    log_ok "필수 디렉토리 생성 (logs, upload, download, .ollama, chromadb)"
}

# =========================================================================
# [4/7] 시스템 설정 파일 배치
# =========================================================================
deploy_configs() {
    log_title "=========================================="
    log_title "  [4/7] 시스템 설정 파일 배치"
    log_title "=========================================="

    # --- Nginx ---
    log_step "[ Nginx 설정 ]"
    for conf in jayeondeule_web fastapi; do
        if [ -f "$NGINX_DIR/$conf" ]; then
            cp "$NGINX_DIR/$conf" "/etc/nginx/sites-available/$conf"
            ln -sf "/etc/nginx/sites-available/$conf" "/etc/nginx/sites-enabled/$conf"
            log_ok "$conf → /etc/nginx/sites-available/"
            SUCCESS=$((SUCCESS + 1))
        else
            log_warn "$conf: 백업 없음 (건너뜀)"
        fi
    done
    rm -f /etc/nginx/sites-enabled/default 2>/dev/null
    if nginx -t 2>/dev/null; then
        log_ok "Nginx 설정 검증: OK"
    else
        log_warn "Nginx 설정 검증 실패 (server_name 확인 필요)"
    fi

    # --- Systemd ---
    log_step "[ Systemd 서비스 ]"
    for svc in agriAiCore ollama chromadb jayeondeule_web; do
        if [ -f "$SYSTEMD_DIR/${svc}.service" ]; then
            cp "$SYSTEMD_DIR/${svc}.service" "/etc/systemd/system/${svc}.service"
            log_ok "${svc}.service → /etc/systemd/system/"
            SUCCESS=$((SUCCESS + 1))
        else
            log_warn "${svc}.service: 백업 없음 (건너뜀)"
        fi
    done
    systemctl daemon-reload
    log_ok "systemctl daemon-reload 완료"

    # --- PostgreSQL 설정 ---
    log_step "[ PostgreSQL 설정 ]"
    local PG_SYS_DIR="/etc/postgresql/16/main"
    if [ -d "$PG_SYS_DIR" ]; then
        for conf in postgresql.conf pg_hba.conf; do
            if [ -f "$PG_CONF_DIR/$conf" ]; then
                cp "$PG_SYS_DIR/$conf" "$PG_SYS_DIR/${conf}.bak.$(date +%Y%m%d)" 2>/dev/null || true
                cp "$PG_CONF_DIR/$conf" "$PG_SYS_DIR/$conf"
                chown postgres:postgres "$PG_SYS_DIR/$conf"
                log_ok "$conf → $PG_SYS_DIR/"
                SUCCESS=$((SUCCESS + 1))
            else
                log_warn "$conf: 백업 없음 (건너뜀)"
            fi
        done
        systemctl restart postgresql 2>/dev/null || true
        log_ok "PostgreSQL 재시작"
    else
        log_warn "PostgreSQL 16 설정 디렉토리 없음"
    fi

    # --- PostgreSQL 사용자 비밀번호 설정 ---
    load_env
    if [ -n "$PGDB_PASSWORD" ]; then
        log_step "[ PostgreSQL 사용자 설정 ]"
        su - postgres -c "psql -c \"ALTER USER ${PGDB_USER:-postgres} WITH PASSWORD '${PGDB_PASSWORD}';\"" 2>/dev/null
        log_ok "PostgreSQL 사용자 비밀번호 설정 완료"
    fi
}

# =========================================================================
# [5/7] 데이터 복원
# =========================================================================
restore_data() {
    log_title "=========================================="
    log_title "  [5/7] 데이터 복원"
    log_title "=========================================="

    load_env

    # --- PostgreSQL DB 복원 ---
    log_step "[ PostgreSQL 데이터베이스 ]"
    local DUMP_FILE="$DATA_DIR/postgresql_dump.sql"
    if [ -f "$DUMP_FILE" ]; then
        local SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
        log_info "덤프 파일: $SIZE"

        # PostgreSQL 서비스 확인
        if ! systemctl is-active --quiet postgresql 2>/dev/null; then
            systemctl start postgresql 2>/dev/null || true
            sleep 3
        fi

        # DB 생성 (없으면)
        local DB_NAME="${PGDB_DATABASE:-jayeondeule}"
        if ! su - postgres -c "psql -lqt" 2>/dev/null | grep -qw "$DB_NAME"; then
            log_info "데이터베이스 '$DB_NAME' 생성 중..."
            su - postgres -c "createdb $DB_NAME" 2>/dev/null || true
        fi

        log_info "DB 복원 중..."
        if PGPASSWORD="${PGDB_PASSWORD}" pg_restore \
            -h "${PGDB_HOST:-127.0.0.1}" \
            -p "${PGDB_PORT:-5432}" \
            -U "${PGDB_USER:-postgres}" \
            -d "$DB_NAME" \
            --no-owner --no-privileges \
            --clean --if-exists \
            "$DUMP_FILE" 2>/dev/null; then
            log_ok "PostgreSQL DB 복원 완료"
        else
            log_warn "PostgreSQL 복원 완료 (일부 경고 가능)"
        fi
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "postgresql_dump.sql: 없음"
        FAIL=$((FAIL + 1))
    fi

    # --- ChromaDB 벡터DB 복원 ---
    log_step "[ ChromaDB 벡터DB ]"
    local CHROMA_SRC="$DATA_DIR/chromadb/database"
    local CHROMA_DEST="$PROJECT_DIR/chromadb"

    if [ -d "$CHROMA_SRC" ]; then
        local SRC_SIZE=$(du -sh "$CHROMA_SRC" | awk '{print $1}')
        log_info "백업 크기: $SRC_SIZE"

        # 기존 데이터 백업
        if [ -d "$CHROMA_DEST/database" ]; then
            mv "$CHROMA_DEST/database" "$CHROMA_DEST/database.bak.$(date +%Y%m%d)" 2>/dev/null || true
        fi

        mkdir -p "$CHROMA_DEST"
        log_info "디렉토리 복사 중..."
        cp -r "$CHROMA_SRC" "$CHROMA_DEST/"
        chown -R "$OWNER:$OWNER" "$CHROMA_DEST"
        local DEST_SIZE=$(du -sh "$CHROMA_DEST/database" | awk '{print $1}')
        log_ok "ChromaDB 복원 완료 ($DEST_SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "ChromaDB 백업 없음: $CHROMA_SRC"
        FAIL=$((FAIL + 1))
    fi

    # --- 업로드 파일 복원 ---
    log_step "[ 업로드 파일 ]"
    if [ -d "$UPLOAD_DIR" ] && [ "$(ls -A "$UPLOAD_DIR" 2>/dev/null)" ]; then
        mkdir -p "$PROJECT_DIR/upload"
        cp -r "$UPLOAD_DIR"/* "$PROJECT_DIR/upload/" 2>/dev/null
        chown -R "$OWNER:$OWNER" "$PROJECT_DIR/upload"
        log_ok "업로드 파일 복원 완료"
        SUCCESS=$((SUCCESS + 1))
    else
        log_info "업로드 백업 없음 (건너뜀)"
    fi
}

# =========================================================================
# [6/7] 프로젝트 빌드
# =========================================================================
setup_build() {
    log_title "=========================================="
    log_title "  [6/7] 프로젝트 빌드"
    log_title "=========================================="

    # --- Python venv ---
    log_step "[ Python venv + 패키지 설치 ]"
    if [ ! -d "$PROJECT_DIR/venv" ]; then
        log_info "venv 생성 중..."
        su - "$OWNER" -c "python3 -m venv $PROJECT_DIR/venv"
    fi

    local REQ_FILE=""
    if [ -f "$PYTHON_DIR/requirements.txt" ]; then
        REQ_FILE="$PYTHON_DIR/requirements.txt"
    elif [ -f "$PROJECT_DIR/requirements.txt" ]; then
        REQ_FILE="$PROJECT_DIR/requirements.txt"
    fi

    if [ -n "$REQ_FILE" ]; then
        local COUNT=$(wc -l < "$REQ_FILE")
        log_info "패키지 설치 중... (${COUNT}개)"
        su - "$OWNER" -c "$PROJECT_DIR/venv/bin/pip install --upgrade pip -q" 2>/dev/null
        su - "$OWNER" -c "$PROJECT_DIR/venv/bin/pip install -q -r $REQ_FILE" 2>&1 | tail -5
        log_ok "Python 패키지 설치 완료"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "requirements.txt 없음"
        FAIL=$((FAIL + 1))
    fi

    # --- Spring Boot ---
    log_step "[ Spring Boot 빌드 ]"
    local BACKEND_DIR="$PROJECT_DIR/web/backend"
    if [ -f "$BACKEND_DIR/mvnw" ]; then
        log_info "Maven 빌드 중..."
        chmod +x "$BACKEND_DIR/mvnw"
        cd "$BACKEND_DIR"
        su - "$OWNER" -c "cd $BACKEND_DIR && ./mvnw package -DskipTests -q" 2>&1 | tail -3
        cd /
        if [ -f "$BACKEND_DIR/target/smartfarm-0.0.1-SNAPSHOT.jar" ]; then
            log_ok "Spring Boot 빌드 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "JAR 파일 생성 실패"
            FAIL=$((FAIL + 1))
        fi
    else
        log_warn "mvnw 없음 (건너뜀)"
    fi

    # --- React 프론트엔드 ---
    log_step "[ React 프론트엔드 빌드 ]"
    local FRONTEND_DIR="$PROJECT_DIR/web/frontend"
    if [ -f "$FRONTEND_DIR/package.json" ]; then
        log_info "npm install + build 중..."
        su - "$OWNER" -c "cd $FRONTEND_DIR && npm install --silent" 2>&1 | tail -3
        su - "$OWNER" -c "cd $FRONTEND_DIR && npm run build" 2>&1 | tail -3
        if [ -d "$FRONTEND_DIR/dist" ]; then
            log_ok "React 빌드 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "dist 디렉토리 생성 실패"
            FAIL=$((FAIL + 1))
        fi
    else
        log_warn "package.json 없음 (건너뜀)"
    fi

    # --- SearXNG Docker ---
    log_step "[ SearXNG Docker ]"
    local SEARXNG_DIR="$PROJECT_DIR/setup/searxng"
    if [ -f "$SEARXNG_DIR/docker-compose.yml" ] && command -v docker &>/dev/null; then
        cd "$SEARXNG_DIR"
        docker compose up -d 2>&1 | tail -3
        cd /
        log_ok "SearXNG 컨테이너 시작"
        SUCCESS=$((SUCCESS + 1))
    else
        log_warn "SearXNG 건너뜀 (docker-compose.yml 없거나 Docker 미설치)"
    fi

    # --- MCP web-search ---
    log_step "[ MCP web-search ]"
    local MCP_DIR="$PROJECT_DIR/.mcp/web-search"
    if [ -f "$MCP_DIR/package.json" ]; then
        su - "$OWNER" -c "cd $MCP_DIR && npm install --silent" 2>&1 | tail -3
        su - "$OWNER" -c "cd $MCP_DIR && npm run build" 2>&1 | tail -3
        if [ -f "$MCP_DIR/build/index.js" ]; then
            log_ok "MCP web-search 빌드 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            log_warn "MCP web-search 빌드 실패"
        fi
    else
        log_info "MCP web-search 없음 (건너뜀)"
    fi
}

# =========================================================================
# [7/7] 서비스 활성화 + Ollama 모델
# =========================================================================
setup_services() {
    log_title "=========================================="
    log_title "  [7/7] 서비스 활성화 및 Ollama 모델"
    log_title "=========================================="

    # --- Systemd 서비스 활성화 ---
    log_step "[ 서비스 활성화 ]"
    for svc in ollama chromadb jayeondeule_web agriAiCore nginx; do
        if [ -f "/etc/systemd/system/${svc}.service" ] || systemctl list-unit-files "${svc}.service" &>/dev/null 2>&1; then
            systemctl enable "${svc}.service" 2>/dev/null || true
            log_ok "${svc}.service: 활성화"
        fi
    done

    # --- Ollama 모델 다운로드 ---
    log_step "[ Ollama 모델 다운로드 ]"
    if command -v ollama &>/dev/null; then
        # Ollama 서비스 시작
        systemctl start ollama 2>/dev/null || true
        sleep 3

        local MODEL_LIST="$OLLAMA_DIR/models.txt"
        if [ -f "$MODEL_LIST" ]; then
            log_info "백업된 모델 목록에서 다운로드합니다."

            tail -n +2 "$MODEL_LIST" | awk '{print $1}' | while read model; do
                [ -z "$model" ] && continue
                if ollama list 2>/dev/null | grep -q "^${model}"; then
                    log_ok "$model: 이미 설치됨"
                else
                    log_info "$model 다운로드 중... (대용량, 시간 소요)"
                    if ollama pull "$model" 2>&1 | tail -1; then
                        log_ok "$model: 완료"
                    else
                        log_fail "$model: 실패 (수동: ollama pull $model)"
                    fi
                fi
            done
        else
            log_warn "모델 목록 없음. 기본 모델을 다운로드합니다."
            for model in "qwen3:32b" "qwen3:latest" "bge-m3:latest"; do
                if ollama list 2>/dev/null | grep -q "^${model}"; then
                    log_ok "$model: 이미 설치됨"
                else
                    log_info "$model 다운로드 중..."
                    ollama pull "$model" 2>&1 | tail -1
                fi
            done
        fi
    else
        log_fail "Ollama 미설치"
        echo "    curl -fsSL https://ollama.com/install.sh | sh"
    fi
}

# =========================================================================
# 완료 요약
# =========================================================================
show_summary() {
    log_title "=========================================="
    log_title "  복원 완료"
    log_title "=========================================="
    echo ""
    log_info "성공: ${SUCCESS}개  /  실패: ${FAIL}개"
    echo ""

    if [ $FAIL -eq 0 ]; then
        log_info "모든 항목이 성공적으로 복원되었습니다."
    else
        log_warn "일부 항목이 실패했습니다. 위 로그를 확인해 주세요."
    fi

    echo ""
    log_info "서비스 시작:"
    echo "    sudo ./agriAiCore start"
    echo ""
    log_info "상태 확인:"
    echo "    sudo ./agriAiCore status"
    echo ""

    log_warn "수동 확인 필요:"
    echo "    1. .env 파일 내 비밀번호/API 키"
    echo "    2. Nginx server_name (새 도메인/IP)"
    echo "    3. GPU 드라이버 설치 (NVIDIA CUDA) — GPU 사용 시"
    echo ""
}

# =========================================================================
# 사용법
# =========================================================================
usage() {
    echo ""
    echo "사용법: sudo bash $0 [명령어]"
    echo ""
    echo "명령어:"
    echo "  check          사전 요구사항 확인"
    echo "  install-deps   필수 패키지 설치 (nginx, postgresql, java 등)"
    echo "  deploy-source  소스코드 배치"
    echo "  deploy-configs 설정 파일 배치 (Nginx, Systemd, PostgreSQL)"
    echo "  restore-data   데이터 복원 (PostgreSQL DB + ChromaDB + 업로드)"
    echo "  build          Python/Java/React/Docker 빌드"
    echo "  services       서비스 활성화 + Ollama 모델 다운로드"
    echo "  all            전체 실행 (1~7 순서대로)"
    echo ""
    echo "복원 원본: $BACKUP_ROOT"
    echo ""
    echo "권장 순서:"
    echo "  1. sudo bash $0 check"
    echo "  2. sudo bash $0 install-deps"
    echo "  3. sudo bash $0 deploy-source"
    echo "  4. sudo bash $0 deploy-configs"
    echo "  5. sudo bash $0 restore-data"
    echo "  6. sudo bash $0 build"
    echo "  7. sudo bash $0 services"
    echo ""
}

# =========================================================================
# 메인
# =========================================================================
case "${1:-}" in
    check)          check_prerequisites ;;
    install-deps)   ensure_sudo; install_dependencies ;;
    deploy-source)  ensure_sudo; deploy_source ;;
    deploy-configs) ensure_sudo; deploy_configs ;;
    restore-data)   ensure_sudo; restore_data ;;
    build)          ensure_sudo; setup_build ;;
    services)       ensure_sudo; setup_services ;;
    all)
        ensure_sudo
        log_title "=========================================="
        log_title "  AgriAI Core 전체 시스템 복원"
        log_title "  복원 원본: $BACKUP_ROOT"
        log_title "=========================================="
        check_prerequisites
        install_dependencies
        deploy_source
        deploy_configs
        restore_data
        setup_build
        setup_services
        show_summary
        ;;
    help|--help|-h) usage ;;
    *)              usage ;;
esac
