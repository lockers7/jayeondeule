#!/bin/bash
# =========================================================================
# AgriAI Core 전체 시스템 백업 스크립트
# -----------------------------------------
# 시스템 설정, 데이터베이스, 벡터DB, Python 패키지 목록, 업로드 파일 등
# 신규 서버 포팅에 필요한 모든 항목을 백업합니다.
#
# 사용법:
#   bash setup/system-configs/backup.sh          # 전체 백업
#   bash setup/system-configs/backup.sh configs   # 설정 파일만
#   bash setup/system-configs/backup.sh data      # 데이터만 (DB + ChromaDB)
#   bash setup/system-configs/backup.sh list      # 백업 파일 목록 확인
#
# 백업 위치: setup/system-configs/ 하위
# 복원: bash setup/system-configs/restore.sh
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
log_ok()    { echo -e "${GREEN}  ✓${NC} $1"; }
log_fail()  { echo -e "${RED}  ✗${NC} $1"; }

# 경로
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 백업 하위 디렉토리
NGINX_DIR="$SCRIPT_DIR/nginx"
SYSTEMD_DIR="$SCRIPT_DIR/systemd"
PG_DIR="$SCRIPT_DIR/postgresql"
DATA_DIR="$SCRIPT_DIR/data"

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
# [1] 시스템 설정 파일 백업
# =========================================================================
backup_configs() {
    log_title "=========================================="
    log_title "  [1/5] 시스템 설정 파일 백업"
    log_title "=========================================="
    echo ""

    mkdir -p "$NGINX_DIR" "$SYSTEMD_DIR" "$PG_DIR"

    # --- Nginx ---
    log_info "Nginx 설정"
    for src in /etc/nginx/sites-available/jayeondeule_web /etc/nginx/sites-available/fastapi; do
        fname=$(basename "$src")
        if [ -f "$src" ]; then
            sudo cp "$src" "$NGINX_DIR/$fname"
            log_ok "$src"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "$src: 없음"
            FAIL=$((FAIL + 1))
        fi
    done

    # --- Systemd ---
    log_info "Systemd 서비스"
    for svc in agriAiCore ollama chromadb jayeondeule_web; do
        src="/etc/systemd/system/${svc}.service"
        if [ -f "$src" ]; then
            sudo cp "$src" "$SYSTEMD_DIR/"
            log_ok "$src"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "$src: 없음"
            FAIL=$((FAIL + 1))
        fi
    done

    # --- PostgreSQL 설정 ---
    log_info "PostgreSQL 설정"
    for conf in postgresql.conf pg_hba.conf; do
        src="/etc/postgresql/16/main/$conf"
        if [ -f "$src" ]; then
            sudo cp "$src" "$PG_DIR/$conf"
            log_ok "$src"
            SUCCESS=$((SUCCESS + 1))
        else
            log_fail "$src: 없음"
            FAIL=$((FAIL + 1))
        fi
    done

    echo ""
}

# =========================================================================
# [2] PostgreSQL 데이터베이스 백업
# =========================================================================
backup_postgresql_data() {
    log_title "=========================================="
    log_title "  [2/5] PostgreSQL 데이터베이스 백업"
    log_title "=========================================="
    echo ""

    mkdir -p "$DATA_DIR"

    if ! command -v pg_dump &>/dev/null; then
        log_fail "pg_dump 명령 없음. PostgreSQL 클라이언트 설치 필요."
        FAIL=$((FAIL + 1))
        return
    fi

    local DUMP_FILE="$DATA_DIR/postgresql_dump.sql"
    log_info "데이터베이스: ${PGDB_DATABASE:-jayeondeule}"
    log_info "덤프 중... (시간이 소요될 수 있습니다)"

    if PGPASSWORD="${PGDB_PASSWORD}" pg_dump \
        -h "${PGDB_HOST:-127.0.0.1}" \
        -p "${PGDB_PORT:-5432}" \
        -U "${PGDB_USER:-postgres}" \
        -d "${PGDB_DATABASE:-jayeondeule}" \
        --no-owner \
        --no-privileges \
        -F c \
        -f "$DUMP_FILE" 2>/dev/null; then

        local DUMP_SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
        log_ok "postgresql_dump.sql ($DUMP_SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "pg_dump 실패. DB 접속정보(.env) 확인 필요."
        FAIL=$((FAIL + 1))
    fi

    echo ""
}

# =========================================================================
# [3] ChromaDB 벡터 데이터베이스 백업
# =========================================================================
backup_chromadb_data() {
    log_title "=========================================="
    log_title "  [3/5] ChromaDB 벡터DB 백업"
    log_title "=========================================="
    echo ""

    local CHROMA_SRC="$PROJECT_DIR/chromadb/database"
    local CHROMA_BACKUP="$DATA_DIR/chromadb_backup.tar.gz"

    if [ ! -d "$CHROMA_SRC" ]; then
        log_fail "ChromaDB 데이터 디렉토리 없음: $CHROMA_SRC"
        FAIL=$((FAIL + 1))
        return
    fi

    local SRC_SIZE=$(du -sh "$CHROMA_SRC" | awk '{print $1}')
    log_info "원본 크기: $SRC_SIZE"
    log_info "압축 중... (시간이 소요될 수 있습니다)"

    if tar -czf "$CHROMA_BACKUP" -C "$PROJECT_DIR/chromadb" database 2>/dev/null; then
        local BACKUP_SIZE=$(ls -lh "$CHROMA_BACKUP" | awk '{print $5}')
        log_ok "chromadb_backup.tar.gz ($BACKUP_SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "ChromaDB 압축 실패"
        FAIL=$((FAIL + 1))
    fi

    echo ""
}

# =========================================================================
# [4] Python 패키지 목록 + 업로드 파일 백업
# =========================================================================
backup_extras() {
    log_title "=========================================="
    log_title "  [4/5] Python 패키지 및 업로드 파일 백업"
    log_title "=========================================="
    echo ""

    mkdir -p "$DATA_DIR"

    # --- Python 패키지 목록 (requirements.txt) ---
    local PIP="$PROJECT_DIR/venv/bin/pip"
    local REQ_FILE="$DATA_DIR/requirements.txt"

    if [ -f "$PIP" ]; then
        "$PIP" freeze > "$REQ_FILE" 2>/dev/null
        local PKG_COUNT=$(wc -l < "$REQ_FILE")
        log_ok "requirements.txt (${PKG_COUNT}개 패키지)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_fail "Python venv 없음: $PIP"
        FAIL=$((FAIL + 1))
    fi

    # --- 업로드 파일 ---
    local UPLOAD_SRC="$PROJECT_DIR/upload"
    local UPLOAD_BACKUP="$DATA_DIR/upload_backup.tar.gz"

    if [ -d "$UPLOAD_SRC" ] && [ "$(ls -A "$UPLOAD_SRC" 2>/dev/null)" ]; then
        tar -czf "$UPLOAD_BACKUP" -C "$PROJECT_DIR" upload 2>/dev/null
        local UPLOAD_SIZE=$(ls -lh "$UPLOAD_BACKUP" | awk '{print $5}')
        log_ok "upload_backup.tar.gz ($UPLOAD_SIZE)"
        SUCCESS=$((SUCCESS + 1))
    else
        log_info "업로드 디렉토리 비어있음 (건너뜀)"
    fi

    echo ""
}

# =========================================================================
# [5] Ollama 모델 목록 기록
# =========================================================================
backup_ollama_info() {
    log_title "=========================================="
    log_title "  [5/5] Ollama 모델 정보 기록"
    log_title "=========================================="
    echo ""

    mkdir -p "$DATA_DIR"
    local MODEL_FILE="$DATA_DIR/ollama_models.txt"

    if command -v ollama &>/dev/null; then
        ollama list > "$MODEL_FILE" 2>/dev/null
        local MODEL_COUNT=$(tail -n +2 "$MODEL_FILE" | wc -l)
        log_ok "ollama_models.txt (${MODEL_COUNT}개 모델)"
        SUCCESS=$((SUCCESS + 1))

        log_info "등록된 모델:"
        tail -n +2 "$MODEL_FILE" | while read line; do
            echo "  $line"
        done

        local MODELS_SIZE=$(du -sh "$PROJECT_DIR/.ollama/models/" 2>/dev/null | awk '{print $1}')
        echo ""
        log_warn "Ollama 모델 파일($MODELS_SIZE)은 용량이 커서 별도 백업하지 않습니다."
        log_info "복원 시 restore.sh가 자동으로 다운로드합니다."
    else
        log_fail "ollama 명령 없음"
        FAIL=$((FAIL + 1))
    fi

    echo ""
}

# =========================================================================
# 백업 파일 목록 표시
# =========================================================================
show_list() {
    log_title "=========================================="
    log_title "  백업 파일 목록"
    log_title "=========================================="
    echo ""

    if [ ! -d "$SCRIPT_DIR" ]; then
        log_error "백업 디렉토리 없음"
        exit 1
    fi

    find "$SCRIPT_DIR" -type f ! -name "*.sh" | sort | while read f; do
        REL=$(echo "$f" | sed "s|$SCRIPT_DIR/||")
        SIZE=$(ls -lh "$f" | awk '{print $5}')
        echo "  $REL ($SIZE)"
    done

    echo ""
    local TOTAL=$(du -sh "$SCRIPT_DIR" | awk '{print $1}')
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
    echo ""

    show_list

    log_info "복원 명령:"
    echo "  bash setup/system-configs/restore.sh all"
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
    echo "  (없음)    전체 백업 실행"
    echo "  configs   시스템 설정 파일만 백업"
    echo "  data      데이터만 백업 (PostgreSQL + ChromaDB)"
    echo "  list      현재 백업 파일 목록 확인"
    echo ""
}

# =========================================================================
# 메인
# =========================================================================
case "${1:-all}" in
    configs)
        log_title "=========================================="
        log_title "  AgriAI Core 시스템 백업 (설정 파일)"
        log_title "=========================================="
        echo ""
        ensure_sudo
        backup_configs
        show_summary
        ;;
    data)
        log_title "=========================================="
        log_title "  AgriAI Core 시스템 백업 (데이터)"
        log_title "=========================================="
        echo ""
        ensure_sudo
        backup_postgresql_data
        backup_chromadb_data
        show_summary
        ;;
    list)
        show_list
        ;;
    all|"")
        log_title "=========================================="
        log_title "  AgriAI Core 전체 시스템 백업"
        log_title "=========================================="
        echo ""
        ensure_sudo
        backup_configs
        backup_postgresql_data
        backup_chromadb_data
        backup_extras
        backup_ollama_info
        show_summary
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        usage
        ;;
esac
