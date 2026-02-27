#!/bin/bash
# =========================================================================
# AgriAI Core 전체 시스템 복원 스크립트
# -----------------------------------------
# backup.sh로 백업한 모든 항목을 신규 Linux 서버에 복원합니다.
# git clone 후 실행하면 현재 시스템과 동일하게 구성됩니다.
#
# 사용법:
#   bash setup/system-configs/restore.sh              # 설정 + 데이터 복원
#   bash setup/system-configs/restore.sh check        # 사전 요구사항 확인
#   bash setup/system-configs/restore.sh install-deps  # 패키지 설치
#   bash setup/system-configs/restore.sh deploy        # 설정 파일 배치
#   bash setup/system-configs/restore.sh data          # 데이터 복원 (DB + ChromaDB)
#   bash setup/system-configs/restore.sh build         # Python/Java/React 빌드
#   bash setup/system-configs/restore.sh services      # 서비스 활성화 + Ollama 모델
#   bash setup/system-configs/restore.sh all           # 전체 실행
#
# =========================================================================

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_title() { echo -e "${CYAN}${BOLD}$1${NC}"; }
log_step()  { echo -e "${BOLD}$1${NC}"; }
log_ok()    { echo -e "${GREEN}  ✓${NC} $1"; }
log_fail()  { echo -e "${RED}  ✗${NC} $1"; }

# 경로
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
OWNER="jayeondeule"

# .env에서 DB 접속정보 로드
if [ -f "$PROJECT_DIR/.env" ]; then
    PGDB_HOST=$(grep "^PGDB_HOST=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    PGDB_PORT=$(grep "^PGDB_PORT=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    PGDB_DATABASE=$(grep "^PGDB_DATABASE=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    PGDB_USER=$(grep "^PGDB_USER=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    PGDB_PASSWORD=$(grep "^PGDB_PASSWORD=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
fi

SUCCESS=0
FAIL=0

# =========================================================================
# sudo 인증
# =========================================================================
ensure_sudo() {
    log_info "sudo 권한이 필요합니다. 비밀번호를 입력해 주세요."
    echo ""
    if ! sudo -v; then
        log_error "sudo 인증 실패. 스크립트를 종료합니다."
        exit 1
    fi
    echo ""
}

# =========================================================================
# [1] 사전 요구사항 확인
# =========================================================================
check_prerequisites() {
    log_title "=========================================="
    log_title "  [1/6] 사전 요구사항 확인"
    log_title "=========================================="
    echo ""

    # OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        log_info "OS: $PRETTY_NAME"
    fi

    # 사용자
    if id "$OWNER" &>/dev/null; then
        log_ok "사용자 '$OWNER': 존재함"
    else
        log_fail "사용자 '$OWNER': 존재하지 않음 (생성 필요)"
    fi

    # git 저장소
    if [ -d "$PROJECT_DIR/.git" ]; then
        log_ok "프로젝트: $PROJECT_DIR (git 저장소)"
    else
        log_fail "프로젝트: $PROJECT_DIR (git 저장소 아님)"
    fi

    # 백업 파일 확인
    echo ""
    log_step "[ 백업 파일 상태 ]"
    echo ""

    local CHECK_FILES=(
        "$SCRIPT_DIR/nginx/jayeondeule_web:Nginx 메인 설정"
        "$SCRIPT_DIR/systemd/agriAiCore.service:Systemd agriAiCore"
        "$SCRIPT_DIR/systemd/ollama.service:Systemd Ollama"
        "$SCRIPT_DIR/systemd/chromadb.service:Systemd ChromaDB"
        "$SCRIPT_DIR/systemd/jayeondeule_web.service:Systemd Spring Boot"
        "$SCRIPT_DIR/postgresql/postgresql.conf:PostgreSQL 설정"
        "$SCRIPT_DIR/postgresql/pg_hba.conf:PostgreSQL 접근제어"
        "$DATA_DIR/postgresql_dump.sql:PostgreSQL DB 덤프"
        "$DATA_DIR/chromadb_backup.tar.gz:ChromaDB 벡터DB"
        "$DATA_DIR/requirements.txt:Python 패키지 목록"
        "$DATA_DIR/ollama_models.txt:Ollama 모델 목록"
    )

    for item in "${CHECK_FILES[@]}"; do
        local fpath="${item%%:*}"
        local label="${item##*:}"
        if [ -f "$fpath" ]; then
            local fsize=$(ls -lh "$fpath" | awk '{print $5}')
            log_ok "$label ($fsize)"
        else
            log_fail "$label: 백업 없음"
        fi
    done

    # 패키지 확인
    echo ""
    log_step "[ 필수 패키지 상태 ]"
    echo ""

    local COMMANDS=("nginx" "psql" "java" "python3" "node" "npm" "docker" "ollama")
    local LABELS=("Nginx" "PostgreSQL" "Java 21" "Python 3" "Node.js" "npm" "Docker" "Ollama")

    for i in "${!COMMANDS[@]}"; do
        if command -v "${COMMANDS[$i]}" &>/dev/null; then
            local VER=$(${COMMANDS[$i]} --version 2>&1 | head -1)
            log_ok "${LABELS[$i]}: $VER"
        else
            log_fail "${LABELS[$i]}: 미설치"
        fi
    done
    echo ""
}

# =========================================================================
# [2] 필수 패키지 설치
# =========================================================================
install_dependencies() {
    log_title "=========================================="
    log_title "  [2/6] 필수 패키지 설치"
    log_title "=========================================="
    echo ""

    sudo apt-get update -qq

    # Nginx
    log_info "Nginx 설치 중..."
    sudo apt-get install -y -qq nginx > /dev/null 2>&1
    log_ok "Nginx: $(nginx -v 2>&1)"

    # PostgreSQL 16
    log_info "PostgreSQL 16 설치 중..."
    if ! command -v psql &>/dev/null; then
        sudo apt-get install -y -qq postgresql-16 postgresql-client-16 > /dev/null 2>&1
    fi
    log_ok "PostgreSQL: $(psql --version 2>&1)"

    # Java 21
    log_info "Java 21 설치 중..."
    if ! command -v java &>/dev/null; then
        sudo apt-get install -y -qq openjdk-21-jdk-headless > /dev/null 2>&1
    fi
    log_ok "Java: $(java -version 2>&1 | head -1)"

    # Python 3 + venv
    log_info "Python 3 + venv 설치 중..."
    sudo apt-get install -y -qq python3 python3-venv python3-pip > /dev/null 2>&1
    log_ok "Python: $(python3 --version 2>&1)"

    # Node.js 20
    log_info "Node.js 설치 중..."
    if ! command -v node &>/dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - > /dev/null 2>&1
        sudo apt-get install -y -qq nodejs > /dev/null 2>&1
    fi
    log_ok "Node.js: $(node --version 2>&1)"

    # Docker
    log_info "Docker 설치 중..."
    if ! command -v docker &>/dev/null; then
        sudo apt-get install -y -qq docker.io docker-compose-plugin > /dev/null 2>&1
    fi
    log_ok "Docker: $(docker --version 2>&1)"

    # Ollama
    log_info "Ollama 확인..."
    if ! command -v ollama &>/dev/null; then
        log_warn "  Ollama 수동 설치 필요: curl -fsSL https://ollama.com/install.sh | sh"
    else
        log_ok "Ollama: $(ollama --version 2>&1)"
    fi

    echo ""
}

# =========================================================================
# [3] 설정 파일 배치
# =========================================================================
deploy_configs() {
    log_title "=========================================="
    log_title "  [3/6] 시스템 설정 파일 복원"
    log_title "=========================================="
    echo ""

    # --- Nginx ---
    log_step "[ Nginx 설정 ]"

    for conf in jayeondeule_web fastapi; do
        if [ -f "$SCRIPT_DIR/nginx/$conf" ]; then
            sudo cp "$SCRIPT_DIR/nginx/$conf" "/etc/nginx/sites-available/$conf"
            sudo ln -sf "/etc/nginx/sites-available/$conf" "/etc/nginx/sites-enabled/$conf"
            log_ok "$conf → /etc/nginx/sites-available/"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "nginx/$conf: 백업 없음"
            FAIL=$((FAIL + 1))
        fi
    done

    sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

    if sudo nginx -t 2>/dev/null; then
        log_ok "Nginx 설정 검증: OK"
    else
        log_fail "Nginx 설정 검증 실패"
    fi
    echo ""

    # --- Systemd ---
    log_step "[ Systemd 서비스 ]"

    for svc in agriAiCore ollama chromadb jayeondeule_web; do
        if [ -f "$SCRIPT_DIR/systemd/${svc}.service" ]; then
            sudo cp "$SCRIPT_DIR/systemd/${svc}.service" "/etc/systemd/system/${svc}.service"
            log_ok "${svc}.service → /etc/systemd/system/"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "${svc}.service: 백업 없음"
            FAIL=$((FAIL + 1))
        fi
    done

    sudo systemctl daemon-reload
    log_ok "systemctl daemon-reload 완료"
    echo ""

    # --- PostgreSQL 설정 ---
    log_step "[ PostgreSQL 설정 ]"

    local PG_CONF_DIR="/etc/postgresql/16/main"
    if [ -d "$PG_CONF_DIR" ]; then
        for conf in postgresql.conf pg_hba.conf; do
            if [ -f "$SCRIPT_DIR/postgresql/$conf" ]; then
                sudo cp "$PG_CONF_DIR/$conf" "$PG_CONF_DIR/${conf}.bak.$(date +%Y%m%d)" 2>/dev/null || true
                sudo cp "$SCRIPT_DIR/postgresql/$conf" "$PG_CONF_DIR/$conf"
                sudo chown postgres:postgres "$PG_CONF_DIR/$conf"
                log_ok "$conf → $PG_CONF_DIR/"
                SUCCESS=$((SUCCESS + 1))
            else
                log_fail "postgresql/$conf: 백업 없음"
                FAIL=$((FAIL + 1))
            fi
        done
    else
        log_fail "PostgreSQL 16 디렉토리 없음"
        FAIL=$((FAIL + 2))
    fi
    echo ""
}

# =========================================================================
# [4] 데이터 복원 (PostgreSQL + ChromaDB)
# =========================================================================
restore_data() {
    log_title "=========================================="
    log_title "  [4/6] 데이터 복원"
    log_title "=========================================="
    echo ""

    # --- PostgreSQL DB 복원 ---
    log_step "[ PostgreSQL 데이터베이스 ]"

    local DUMP_FILE="$DATA_DIR/postgresql_dump.sql"
    if [ -f "$DUMP_FILE" ]; then
        local DUMP_SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
        log_info "덤프 파일: $DUMP_SIZE"

        # PostgreSQL 서비스 시작 확인
        if ! sudo systemctl is-active --quiet postgresql 2>/dev/null; then
            log_info "PostgreSQL 서비스 시작 중..."
            sudo systemctl start postgresql 2>/dev/null || true
            sleep 2
        fi

        # DB 존재 여부 확인, 없으면 생성
        if ! sudo -u postgres psql -lqt 2>/dev/null | grep -qw "${PGDB_DATABASE:-jayeondeule}"; then
            log_info "데이터베이스 '${PGDB_DATABASE:-jayeondeule}' 생성 중..."
            sudo -u postgres createdb "${PGDB_DATABASE:-jayeondeule}" 2>/dev/null || true
        fi

        log_info "DB 복원 중... (시간이 소요될 수 있습니다)"
        if PGPASSWORD="${PGDB_PASSWORD}" pg_restore \
            -h "${PGDB_HOST:-127.0.0.1}" \
            -p "${PGDB_PORT:-5432}" \
            -U "${PGDB_USER:-postgres}" \
            -d "${PGDB_DATABASE:-jayeondeule}" \
            --no-owner \
            --no-privileges \
            --clean \
            --if-exists \
            "$DUMP_FILE" 2>/dev/null; then
            log_ok "PostgreSQL DB 복원 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            # pg_restore는 일부 오류가 있어도 exit code != 0일 수 있음
            log_warn "PostgreSQL 복원 완료 (경고가 있을 수 있음)"
            SUCCESS=$((SUCCESS + 1))
        fi
    else
        log_fail "postgresql_dump.sql: 백업 없음"
        log_info "수동 복원: psql -U postgres jayeondeule < dump.sql"
        FAIL=$((FAIL + 1))
    fi
    echo ""

    # --- ChromaDB 벡터DB 복원 ---
    log_step "[ ChromaDB 벡터DB ]"

    local CHROMA_BACKUP="$DATA_DIR/chromadb_backup.tar.gz"
    local CHROMA_DEST="$PROJECT_DIR/chromadb"

    if [ -f "$CHROMA_BACKUP" ]; then
        local BACKUP_SIZE=$(ls -lh "$CHROMA_BACKUP" | awk '{print $5}')
        log_info "백업 파일: $BACKUP_SIZE"

        # 기존 데이터 백업
        if [ -d "$CHROMA_DEST/database" ]; then
            log_info "기존 ChromaDB 데이터 백업..."
            mv "$CHROMA_DEST/database" "$CHROMA_DEST/database.bak.$(date +%Y%m%d)" 2>/dev/null || true
        fi

        log_info "복원 중..."
        mkdir -p "$CHROMA_DEST"
        if tar -xzf "$CHROMA_BACKUP" -C "$CHROMA_DEST" 2>/dev/null; then
            chown -R "$OWNER:$OWNER" "$CHROMA_DEST/database" 2>/dev/null || true
            local RESTORED_SIZE=$(du -sh "$CHROMA_DEST/database" | awk '{print $1}')
            log_ok "ChromaDB 복원 완료 ($RESTORED_SIZE)"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "ChromaDB 압축 해제 실패"
            FAIL=$((FAIL + 1))
        fi
    else
        log_fail "chromadb_backup.tar.gz: 백업 없음"
        FAIL=$((FAIL + 1))
    fi
    echo ""

    # --- 업로드 파일 복원 ---
    log_step "[ 업로드 파일 ]"

    local UPLOAD_BACKUP="$DATA_DIR/upload_backup.tar.gz"
    if [ -f "$UPLOAD_BACKUP" ]; then
        tar -xzf "$UPLOAD_BACKUP" -C "$PROJECT_DIR" 2>/dev/null
        chown -R "$OWNER:$OWNER" "$PROJECT_DIR/upload" 2>/dev/null || true
        log_ok "업로드 파일 복원 완료"
        SUCCESS=$((SUCCESS + 1))
    else
        log_info "업로드 백업 없음 (건너뜀)"
    fi
    echo ""
}

# =========================================================================
# [5] Python/Java/React 빌드
# =========================================================================
setup_build() {
    log_title "=========================================="
    log_title "  [5/6] 프로젝트 빌드"
    log_title "=========================================="
    echo ""

    # --- Python venv ---
    log_step "[ Python venv ]"

    if [ ! -d "$PROJECT_DIR/venv" ]; then
        log_info "venv 생성 중..."
        sudo -u "$OWNER" python3 -m venv "$PROJECT_DIR/venv"
    fi

    # 백업된 requirements.txt 우선 사용
    local REQ_FILE=""
    if [ -f "$DATA_DIR/requirements.txt" ]; then
        REQ_FILE="$DATA_DIR/requirements.txt"
    elif [ -f "$PROJECT_DIR/requirements.txt" ]; then
        REQ_FILE="$PROJECT_DIR/requirements.txt"
    fi

    if [ -n "$REQ_FILE" ]; then
        local PKG_COUNT=$(wc -l < "$REQ_FILE")
        log_info "패키지 설치 중... (${PKG_COUNT}개)"
        sudo -u "$OWNER" "$PROJECT_DIR/venv/bin/pip" install -q -r "$REQ_FILE" 2>&1 | tail -5
        log_ok "Python 의존성 설치 완료"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "requirements.txt 없음"
        FAIL=$((FAIL + 1))
    fi
    echo ""

    # --- Spring Boot ---
    log_step "[ Spring Boot 빌드 ]"
    local BACKEND_DIR="$PROJECT_DIR/web/backend"
    if [ -f "$BACKEND_DIR/mvnw" ]; then
        log_info "Maven 빌드 중..."
        cd "$BACKEND_DIR"
        chmod +x mvnw
        sudo -u "$OWNER" ./mvnw package -DskipTests -q 2>&1 | tail -3
        cd "$PROJECT_DIR"
        if [ -f "$BACKEND_DIR/target/smartfarm-0.0.1-SNAPSHOT.jar" ]; then
            log_ok "Spring Boot 빌드 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "JAR 파일 생성 실패"
            FAIL=$((FAIL + 1))
        fi
    else
        log_fail "mvnw 없음"
        FAIL=$((FAIL + 1))
    fi
    echo ""

    # --- React 프론트엔드 ---
    log_step "[ React 프론트엔드 빌드 ]"
    local FRONTEND_DIR="$PROJECT_DIR/web/frontend"
    if [ -f "$FRONTEND_DIR/package.json" ]; then
        log_info "npm install + build 중..."
        cd "$FRONTEND_DIR"
        sudo -u "$OWNER" npm install --silent 2>&1 | tail -3
        sudo -u "$OWNER" npm run build 2>&1 | tail -3
        cd "$PROJECT_DIR"
        if [ -d "$FRONTEND_DIR/dist" ]; then
            log_ok "React 빌드 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "dist 디렉토리 생성 실패"
            FAIL=$((FAIL + 1))
        fi
    else
        log_fail "package.json 없음"
        FAIL=$((FAIL + 1))
    fi
    echo ""

    # --- SearXNG Docker ---
    log_step "[ SearXNG Docker ]"
    local SEARXNG_DIR="$PROJECT_DIR/setup/searxng"
    if [ -f "$SEARXNG_DIR/docker-compose.yml" ]; then
        cd "$SEARXNG_DIR"
        sudo docker compose up -d 2>&1 | tail -3
        cd "$PROJECT_DIR"
        log_ok "SearXNG 시작 완료"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "docker-compose.yml 없음"
        FAIL=$((FAIL + 1))
    fi
    echo ""

    # --- MCP web-search ---
    log_step "[ MCP web-search 빌드 ]"
    local MCP_DIR="$PROJECT_DIR/.mcp/web-search"
    if [ -f "$MCP_DIR/package.json" ]; then
        cd "$MCP_DIR"
        sudo -u "$OWNER" npm install --silent 2>&1 | tail -3
        sudo -u "$OWNER" npm run build 2>&1 | tail -3
        cd "$PROJECT_DIR"
        if [ -f "$MCP_DIR/build/index.js" ]; then
            log_ok "MCP web-search 빌드 완료"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "build/index.js 생성 실패"
            FAIL=$((FAIL + 1))
        fi
    else
        log_info "MCP web-search 없음 (건너뜀)"
    fi
    echo ""
}

# =========================================================================
# [6] 서비스 활성화 + Ollama 모델 다운로드
# =========================================================================
setup_services() {
    log_title "=========================================="
    log_title "  [6/6] 서비스 활성화 및 Ollama 모델"
    log_title "=========================================="
    echo ""

    # --- Systemd 서비스 활성화 ---
    log_step "[ 서비스 활성화 ]"

    for svc in ollama chromadb jayeondeule_web agriAiCore nginx; do
        if [ -f "/etc/systemd/system/${svc}.service" ] || systemctl list-unit-files "${svc}.service" &>/dev/null 2>&1; then
            sudo systemctl enable "${svc}.service" 2>/dev/null || true
            log_ok "${svc}.service: 활성화"
        fi
    done
    echo ""

    # --- Ollama 모델 다운로드 ---
    log_step "[ Ollama 모델 다운로드 ]"

    if command -v ollama &>/dev/null; then
        # Ollama 서비스 시작
        sudo systemctl start ollama 2>/dev/null || true
        sleep 3

        # 백업된 모델 목록에서 모델명 추출
        local MODEL_LIST="$DATA_DIR/ollama_models.txt"
        if [ -f "$MODEL_LIST" ]; then
            log_info "백업된 모델 목록에서 복원합니다."
            echo ""

            tail -n +2 "$MODEL_LIST" | awk '{print $1}' | while read model; do
                if [ -z "$model" ]; then continue; fi

                # 이미 설치된 모델 건너뛰기
                if ollama list 2>/dev/null | grep -q "^${model}"; then
                    log_ok "$model: 이미 설치됨"
                else
                    log_info "$model 다운로드 중... (시간이 소요됩니다)"
                    if ollama pull "$model" 2>&1 | tail -1; then
                        log_ok "$model: 다운로드 완료"
                    else
                        log_fail "$model: 다운로드 실패"
                    fi
                fi
            done
        else
            # 기본 모델 다운로드
            log_warn "모델 목록 백업이 없습니다. 기본 모델을 다운로드합니다."
            echo ""

            local DEFAULT_MODELS=("qwen3:32b" "qwen3:latest" "bge-m3:latest")
            local MODEL_LABELS=("메인 LLM" "폴백 LLM" "임베딩 모델")

            for i in "${!DEFAULT_MODELS[@]}"; do
                local model="${DEFAULT_MODELS[$i]}"
                local label="${MODEL_LABELS[$i]}"

                if ollama list 2>/dev/null | grep -q "^${model}"; then
                    log_ok "$model ($label): 이미 설치됨"
                else
                    log_info "$model ($label) 다운로드 중..."
                    if ollama pull "$model" 2>&1 | tail -1; then
                        log_ok "$model: 다운로드 완료"
                    else
                        log_fail "$model: 다운로드 실패 (수동 실행: ollama pull $model)"
                    fi
                fi
            done
        fi
    else
        log_fail "Ollama 미설치. 먼저 설치하세요:"
        echo "  curl -fsSL https://ollama.com/install.sh | sh"
    fi
    echo ""

    # --- 필수 디렉토리 생성 ---
    log_step "[ 디렉토리 생성 ]"
    mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/upload" "$PROJECT_DIR/download"
    chown -R "$OWNER:$OWNER" "$PROJECT_DIR/logs" "$PROJECT_DIR/upload" "$PROJECT_DIR/download" 2>/dev/null || true
    log_ok "logs/, upload/, download/ 디렉토리 확인"
    echo ""
}

# =========================================================================
# 완료 요약
# =========================================================================
show_summary() {
    log_title "=========================================="
    log_title "  복원 완료 요약"
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
    log_info "서비스 시작:  sudo ./agriAiCore start"
    log_info "상태 확인:    sudo ./agriAiCore status"
    echo ""

    log_warn "수동 확인 필요:"
    echo "  1. .env 파일 내 비밀번호/API 키 확인"
    echo "  2. Nginx server_name 변경 (새 도메인/IP)"
    echo "  3. GPU 드라이버 설치 (NVIDIA CUDA) - GPU 사용 시"
    echo ""
}

# =========================================================================
# 사용법
# =========================================================================
usage() {
    echo ""
    echo "사용법: bash $0 [명령어]"
    echo ""
    echo "명령어:"
    echo "  check        사전 요구사항 확인"
    echo "  install-deps 필수 패키지 설치"
    echo "  deploy       설정 파일 복원 (Nginx, Systemd, PostgreSQL 설정)"
    echo "  data         데이터 복원 (PostgreSQL DB + ChromaDB)"
    echo "  build        Python/Java/React 빌드"
    echo "  services     서비스 활성화 + Ollama 모델 다운로드"
    echo "  all          전체 실행 (1~6 순서대로)"
    echo ""
    echo "권장 순서:"
    echo "  1. bash setup/system-configs/restore.sh check"
    echo "  2. bash setup/system-configs/restore.sh install-deps"
    echo "  3. bash setup/system-configs/restore.sh deploy"
    echo "  4. bash setup/system-configs/restore.sh data"
    echo "  5. bash setup/system-configs/restore.sh build"
    echo "  6. bash setup/system-configs/restore.sh services"
    echo ""
}

# =========================================================================
# 메인
# =========================================================================
case "${1:-}" in
    check)
        check_prerequisites
        ;;
    install-deps)
        ensure_sudo
        install_dependencies
        ;;
    deploy)
        ensure_sudo
        deploy_configs
        ;;
    data)
        ensure_sudo
        restore_data
        ;;
    build)
        ensure_sudo
        setup_build
        ;;
    services)
        ensure_sudo
        setup_services
        ;;
    all)
        ensure_sudo
        check_prerequisites
        install_dependencies
        deploy_configs
        restore_data
        setup_build
        setup_services
        show_summary
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        usage
        ;;
esac
