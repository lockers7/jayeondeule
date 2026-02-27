#!/bin/bash
# =========================================================================
# AgriAI Core 전체 시스템 로컬 백업 스크립트
# =========================================================================
# 현 시스템의 agriAiCore 구동에 필요한 모든 파일을 .backup/ 에 백업합니다.
# 신규 서버에 .backup/ 폴더만 복사 후 restore_local.sh 실행으로 즉시 복원됩니다.
#
# 백업 위치: /workspace/jayeondeule/.backup/
#
# .backup/
# ├── restore_local.sh          ← 복원 스크립트 (자체 포함)
# ├── source/                   ← 프로젝트 소스코드 전체
# ├── configs/
# │   ├── nginx/                ← Nginx 설정
# │   ├── systemd/              ← Systemd 서비스
# │   └── postgresql/           ← PostgreSQL 설정
# ├── data/
# │   ├── postgresql_dump.sql   ← PostgreSQL DB 덤프
# │   └── chromadb/             ← ChromaDB 데이터 (디렉토리 복사)
# ├── python/
# │   └── requirements.txt      ← Python 패키지 목록
# ├── upload/                   ← 업로드 파일 (디렉토리 복사)
# └── ollama/
#     └── models.txt            ← Ollama 모델 목록
#
# 사용법:
#   sudo bash setup/system-configs/backup_local.sh          # 전체 백업
#   sudo bash setup/system-configs/backup_local.sh configs   # 설정 파일만
#   sudo bash setup/system-configs/backup_local.sh data      # 데이터만
#   sudo bash setup/system-configs/backup_local.sh list      # 백업 파일 목록
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
log_ok()    { echo -e "${GREEN}  ✓${NC} $1"; }
log_fail()  { echo -e "${RED}  ✗${NC} $1"; }

# =========================================================================
# 경로 설정
# =========================================================================
PROJECT_DIR="/workspace/jayeondeule"
BACKUP_ROOT="$PROJECT_DIR/.backup"

CONFIGS_DIR="$BACKUP_ROOT/configs"
NGINX_DIR="$CONFIGS_DIR/nginx"
SYSTEMD_DIR="$CONFIGS_DIR/systemd"
PG_CONF_DIR="$CONFIGS_DIR/postgresql"
DATA_DIR="$BACKUP_ROOT/data"
SOURCE_DIR="$BACKUP_ROOT/source"
PYTHON_DIR="$BACKUP_ROOT/python"
UPLOAD_DIR="$BACKUP_ROOT/upload"
OLLAMA_DIR="$BACKUP_ROOT/ollama"

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
# sudo 확인
# =========================================================================
ensure_sudo() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "이 스크립트는 sudo 권한이 필요합니다."
        echo "  사용법: sudo bash $0"
        exit 1
    fi
}

# =========================================================================
# [1/7] 시스템 설정 파일 백업
# =========================================================================
backup_configs() {
    log_title "=========================================="
    log_title "  [1/7] 시스템 설정 파일 백업"
    log_title "=========================================="

    mkdir -p "$NGINX_DIR" "$SYSTEMD_DIR" "$PG_CONF_DIR"

    # --- Nginx ---
    log_info "Nginx 설정"
    for src in /etc/nginx/sites-available/jayeondeule_web /etc/nginx/sites-available/fastapi; do
        fname=$(basename "$src")
        if [ -f "$src" ]; then
            cp "$src" "$NGINX_DIR/$fname"
            log_ok "$fname"
            SUCCESS=$((SUCCESS + 1))
        else
            log_warn "$src: 없음 (건너뜀)"
        fi
    done

    # --- Systemd ---
    log_info "Systemd 서비스"
    for svc in agriAiCore ollama chromadb jayeondeule_web; do
        src="/etc/systemd/system/${svc}.service"
        if [ -f "$src" ]; then
            cp "$src" "$SYSTEMD_DIR/"
            log_ok "${svc}.service"
            SUCCESS=$((SUCCESS + 1))
        else
            log_warn "$src: 없음 (건너뜀)"
        fi
    done

    # --- PostgreSQL 설정 ---
    log_info "PostgreSQL 설정"
    for conf in postgresql.conf pg_hba.conf; do
        src="/etc/postgresql/16/main/$conf"
        if [ -f "$src" ]; then
            cp "$src" "$PG_CONF_DIR/$conf"
            log_ok "$conf"
            SUCCESS=$((SUCCESS + 1))
        else
            log_warn "$src: 없음 (건너뜀)"
        fi
    done
}

# =========================================================================
# [2/7] 프로젝트 소스코드 백업
# =========================================================================
backup_source() {
    log_title "=========================================="
    log_title "  [2/7] 프로젝트 소스코드 백업"
    log_title "=========================================="

    mkdir -p "$SOURCE_DIR"

    log_info "소스코드 복사 중... (대용량 디렉토리 제외)"

    rsync -a --delete \
        --exclude='.backup' \
        --exclude='venv' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.ollama/models' \
        --exclude='chromadb/database' \
        --exclude='logs/*.log' \
        --exclude='web/backend/target' \
        --exclude='web/frontend/dist' \
        "$PROJECT_DIR/" "$SOURCE_DIR/"

    if [ $? -eq 0 ]; then
        local SRC_SIZE=$(du -sh "$SOURCE_DIR" | awk '{print $1}')
        log_ok "소스코드 ($SRC_SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "소스코드 복사 실패"
        FAIL=$((FAIL + 1))
    fi

    # .env 파일 확인 (중요)
    if [ -f "$SOURCE_DIR/.env" ]; then
        log_ok ".env 파일 포함됨"
    else
        log_warn ".env 파일 누락 — 수동 확인 필요"
    fi
}

# =========================================================================
# [3/7] PostgreSQL 데이터베이스 백업
# =========================================================================
backup_postgresql() {
    log_title "=========================================="
    log_title "  [3/7] PostgreSQL 데이터베이스 백업"
    log_title "=========================================="

    mkdir -p "$DATA_DIR"

    if ! command -v pg_dump &>/dev/null; then
        log_fail "pg_dump 명령 없음"
        FAIL=$((FAIL + 1))
        return
    fi

    local DUMP_FILE="$DATA_DIR/postgresql_dump.sql"
    log_info "데이터베이스: ${PGDB_DATABASE:-jayeondeule}"
    log_info "덤프 중..."

    if PGPASSWORD="${PGDB_PASSWORD}" pg_dump \
        -h "${PGDB_HOST:-127.0.0.1}" \
        -p "${PGDB_PORT:-5432}" \
        -U "${PGDB_USER:-postgres}" \
        -d "${PGDB_DATABASE:-jayeondeule}" \
        --no-owner --no-privileges \
        -F c \
        -f "$DUMP_FILE" 2>/dev/null; then
        local SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
        log_ok "postgresql_dump.sql ($SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "pg_dump 실패"
        FAIL=$((FAIL + 1))
    fi
}

# =========================================================================
# [4/7] ChromaDB 벡터DB 백업 (디렉토리 복사)
# =========================================================================
backup_chromadb() {
    log_title "=========================================="
    log_title "  [4/7] ChromaDB 벡터DB 백업"
    log_title "=========================================="

    local CHROMA_SRC="$PROJECT_DIR/chromadb/database"
    local CHROMA_DEST="$DATA_DIR/chromadb"

    if [ ! -d "$CHROMA_SRC" ]; then
        log_fail "ChromaDB 데이터 없음: $CHROMA_SRC"
        FAIL=$((FAIL + 1))
        return
    fi

    local SRC_SIZE=$(du -sh "$CHROMA_SRC" | awk '{print $1}')
    log_info "원본 크기: $SRC_SIZE"
    log_info "디렉토리 복사 중..."

    mkdir -p "$CHROMA_DEST"
    if cp -r "$CHROMA_SRC" "$CHROMA_DEST/"; then
        local DEST_SIZE=$(du -sh "$CHROMA_DEST" | awk '{print $1}')
        log_ok "chromadb/ ($DEST_SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "ChromaDB 복사 실패"
        FAIL=$((FAIL + 1))
    fi
}

# =========================================================================
# [5/7] Python 패키지 목록 백업
# =========================================================================
backup_python() {
    log_title "=========================================="
    log_title "  [5/7] Python 패키지 목록 백업"
    log_title "=========================================="

    mkdir -p "$PYTHON_DIR"
    local PIP="$PROJECT_DIR/venv/bin/pip"
    local REQ_FILE="$PYTHON_DIR/requirements.txt"

    if [ -f "$PIP" ]; then
        "$PIP" freeze > "$REQ_FILE" 2>/dev/null
        local COUNT=$(wc -l < "$REQ_FILE")
        log_ok "requirements.txt (${COUNT}개 패키지)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "venv 없음: $PIP"
        FAIL=$((FAIL + 1))
    fi
}

# =========================================================================
# [6/7] 업로드 파일 백업 (디렉토리 복사)
# =========================================================================
backup_upload() {
    log_title "=========================================="
    log_title "  [6/7] 업로드 파일 백업"
    log_title "=========================================="

    local UPLOAD_SRC="$PROJECT_DIR/upload"

    if [ -d "$UPLOAD_SRC" ] && [ "$(ls -A "$UPLOAD_SRC" 2>/dev/null)" ]; then
        mkdir -p "$UPLOAD_DIR"
        cp -r "$UPLOAD_SRC"/* "$UPLOAD_DIR/" 2>/dev/null
        local SIZE=$(du -sh "$UPLOAD_DIR" | awk '{print $1}')
        log_ok "upload/ ($SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_info "업로드 디렉토리 비어있음 (건너뜀)"
    fi
}

# =========================================================================
# [7/7] Ollama 모델 목록 + 복원 스크립트 복사
# =========================================================================
backup_ollama_and_scripts() {
    log_title "=========================================="
    log_title "  [7/7] Ollama 모델 정보 + 복원 스크립트"
    log_title "=========================================="

    mkdir -p "$OLLAMA_DIR"

    # Ollama 모델 목록
    if command -v ollama &>/dev/null; then
        ollama list > "$OLLAMA_DIR/models.txt" 2>/dev/null
        local COUNT=$(tail -n +2 "$OLLAMA_DIR/models.txt" | wc -l)
        log_ok "models.txt (${COUNT}개 모델)"
        SUCCESS=$((SUCCESS + 1))

        log_info "등록된 모델:"
        tail -n +2 "$OLLAMA_DIR/models.txt" | while read line; do
            echo "    $line"
        done

        local MODELS_SIZE=$(du -sh "$PROJECT_DIR/.ollama/models/" 2>/dev/null | awk '{print $1}')
        if [ -n "$MODELS_SIZE" ]; then
            log_warn "모델 파일($MODELS_SIZE)은 크기가 커서 목록만 백업합니다."
            log_info "복원 시 restore_local.sh가 자동 다운로드합니다."
        fi
    else
        log_warn "ollama 명령 없음 (건너뜀)"
    fi

    # 복원 스크립트를 .backup/ 루트에 복사
    local SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    if [ -f "$SCRIPT_DIR/restore_local.sh" ]; then
        cp "$SCRIPT_DIR/restore_local.sh" "$BACKUP_ROOT/restore_local.sh"
        chmod +x "$BACKUP_ROOT/restore_local.sh"
        log_ok "restore_local.sh → .backup/ 에 복사됨"
    fi
}

# =========================================================================
# 백업 파일 목록 표시
# =========================================================================
show_list() {
    log_title "=========================================="
    log_title "  백업 파일 목록: $BACKUP_ROOT"
    log_title "=========================================="
    echo ""

    if [ ! -d "$BACKUP_ROOT" ]; then
        log_error "백업 없음: $BACKUP_ROOT"
        exit 1
    fi

    # 폴더별 크기 요약
    for d in "$BACKUP_ROOT"/*/; do
        if [ -d "$d" ]; then
            local name=$(basename "$d")
            local size=$(du -sh "$d" | awk '{print $1}')
            local count=$(find "$d" -type f | wc -l)
            echo -e "  ${BOLD}${name}/${NC}  ($size, ${count}개 파일)"
        fi
    done

    # 루트 파일
    for f in "$BACKUP_ROOT"/*; do
        if [ -f "$f" ]; then
            local name=$(basename "$f")
            local size=$(ls -lh "$f" | awk '{print $5}')
            echo -e "  ${name}  ($size)"
        fi
    done

    echo ""
    local TOTAL=$(du -sh "$BACKUP_ROOT" | awk '{print $1}')
    log_info "총 백업 크기: $TOTAL"
    echo ""
}

# =========================================================================
# 결과 요약
# =========================================================================
show_summary() {
    log_title "=========================================="
    log_title "  백업 완료 요약"
    log_title "=========================================="
    echo ""
    log_info "성공: ${SUCCESS}개  /  실패: ${FAIL}개"
    log_info "백업 위치: $BACKUP_ROOT"
    echo ""

    show_list

    log_info "신규 서버 복원 방법:"
    echo "  1. .backup/ 폴더를 신규 서버의 /workspace/jayeondeule/.backup/ 으로 복사"
    echo "  2. sudo bash /workspace/jayeondeule/.backup/restore_local.sh all"
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
    echo "  (없음)    전체 백업 (소스+설정+데이터 전부)"
    echo "  configs   시스템 설정 파일만 백업"
    echo "  data      데이터만 백업 (PostgreSQL + ChromaDB)"
    echo "  source    소스코드만 백업"
    echo "  list      현재 백업 파일 목록 확인"
    echo ""
    echo "백업 위치: $BACKUP_ROOT"
    echo ""
}

# =========================================================================
# 메인
# =========================================================================
case "${1:-all}" in
    configs)
        ensure_sudo
        backup_configs
        show_summary
        ;;
    data)
        ensure_sudo
        backup_postgresql
        backup_chromadb
        show_summary
        ;;
    source)
        ensure_sudo
        backup_source
        show_summary
        ;;
    list)
        show_list
        ;;
    all|"")
        ensure_sudo
        log_title "=========================================="
        log_title "  AgriAI Core 전체 시스템 로컬 백업"
        log_title "  백업 위치: $BACKUP_ROOT"
        log_title "=========================================="
        backup_configs
        backup_source
        backup_postgresql
        backup_chromadb
        backup_python
        backup_upload
        backup_ollama_and_scripts
        show_summary
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        usage
        ;;
esac
