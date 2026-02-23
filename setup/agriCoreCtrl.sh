#!/bin/bash
# =========================================================================
# agriCoreCtrl - AgriAI Core 통합 서비스 관리 스크립트
#
# 사용법:
#   agriCoreCtrl start|stop|restart|status [서비스번호]
#
# 서비스번호 없이 실행하면 메뉴를 표시합니다.
# =========================================================================

set -o pipefail

# ─── 기본 설정 ───
BASE_DIR="/workspace/jayeondeule"
VENV_BIN="$BASE_DIR/venv/bin"
PYTHON_BIN="$VENV_BIN/python"
LOG_DIR="${LOG_PATH:-$BASE_DIR/logs}"
ENV_FILE="$BASE_DIR/.env"

# PID 파일 (/tmp는 root 소유 파일 충돌 가능 → 프로젝트 logs 디렉토리 사용)
PID_DIR="$BASE_DIR/logs"
mkdir -p "$PID_DIR"
API_PID="$PID_DIR/api.pid"
SCHEDULER_PID="$PID_DIR/scheduler.pid"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# .env 로드
if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

# ─── 유틸리티 함수 ───
log_msg() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "[$ts] $*"
}

print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}AgriAI Core 서비스 관리${NC}                                 ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

is_port_listening() {
    local port_hex
    port_hex=$(printf '%04X' "$1")
    awk -v p="$port_hex" '
        NR > 1 {
            split($2, addr, ":")
            if (toupper(addr[2]) == p && $4 == "0A") { found = 1; exit 0 }
        }
        END { if (!found) exit 1 }
    ' /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

check_status() {
    local name="$1" check_type="$2" target="$3"
    case "$check_type" in
        port)
            if is_port_listening "$target"; then
                echo -e "${GREEN}● 실행 중${NC} (port $target)"
            else
                echo -e "${RED}○ 중지${NC}"
            fi
            ;;
        pid_file)
            if [ -f "$target" ]; then
                local pid
                pid=$(cat "$target" 2>/dev/null)
                if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                    echo -e "${GREEN}● 실행 중${NC} (PID $pid)"
                else
                    echo -e "${RED}○ 중지${NC} (stale PID)"
                fi
            else
                echo -e "${RED}○ 중지${NC}"
            fi
            ;;
        systemd)
            if systemctl is-active "$target" >/dev/null 2>&1; then
                echo -e "${GREEN}● 실행 중${NC} (systemd)"
            else
                echo -e "${RED}○ 중지${NC}"
            fi
            ;;
        process)
            if pgrep -f "$target" >/dev/null 2>&1; then
                local pid
                pid=$(pgrep -f "$target" | head -1)
                echo -e "${GREEN}● 실행 중${NC} (PID $pid)"
            else
                echo -e "${RED}○ 중지${NC}"
            fi
            ;;
    esac
}

wait_port() {
    local port="$1" timeout="${2:-30}" waited=0
    while [ "$waited" -lt "$timeout" ]; do
        if is_port_listening "$port"; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

# ─── 개별 서비스 관리 함수 ───

# --- Ollama ---
ollama_start() {
    log_msg "${BLUE}[Ollama]${NC} 시작 중..."
    sudo systemctl start ollama.service
    if wait_port 11434 15; then
        log_msg "${GREEN}[Ollama]${NC} 시작 완료 (port 11434)"
    else
        log_msg "${RED}[Ollama]${NC} 시작 실패"
        return 1
    fi
}

ollama_stop() {
    log_msg "${BLUE}[Ollama]${NC} 종료 중..."
    sudo systemctl stop ollama.service
    # run_services.sh가 시작한 ollama 프로세스도 정리
    pkill -x "ollama" 2>/dev/null || true
    sleep 1
    log_msg "${GREEN}[Ollama]${NC} 종료 완료"
}

ollama_restart() {
    ollama_stop
    sleep 2
    ollama_start
}

# --- PostgreSQL ---
postgresql_start() {
    log_msg "${BLUE}[PostgreSQL]${NC} 시작 중..."
    sudo systemctl start postgresql.service
    if wait_port 5432 15; then
        log_msg "${GREEN}[PostgreSQL]${NC} 시작 완료 (port 5432)"
    else
        log_msg "${RED}[PostgreSQL]${NC} 시작 실패"
        return 1
    fi
}

postgresql_stop() {
    log_msg "${BLUE}[PostgreSQL]${NC} 종료 중..."
    sudo systemctl stop postgresql.service
    log_msg "${GREEN}[PostgreSQL]${NC} 종료 완료"
}

postgresql_restart() {
    log_msg "${BLUE}[PostgreSQL]${NC} 재시작 중..."
    sudo systemctl restart postgresql.service
    if wait_port 5432 15; then
        log_msg "${GREEN}[PostgreSQL]${NC} 재시작 완료"
    else
        log_msg "${RED}[PostgreSQL]${NC} 재시작 실패"
        return 1
    fi
}

# --- ChromaDB ---
chromadb_start() {
    log_msg "${BLUE}[ChromaDB]${NC} 시작 중..."
    sudo systemctl start chromadb.service
    if wait_port 8000 20; then
        log_msg "${GREEN}[ChromaDB]${NC} 시작 완료 (port 8000)"
    else
        log_msg "${RED}[ChromaDB]${NC} 시작 실패"
        return 1
    fi
}

chromadb_stop() {
    log_msg "${BLUE}[ChromaDB]${NC} 종료 중..."
    sudo systemctl stop chromadb.service
    log_msg "${GREEN}[ChromaDB]${NC} 종료 완료"
}

chromadb_restart() {
    log_msg "${BLUE}[ChromaDB]${NC} 재시작 중..."
    sudo systemctl restart chromadb.service
    if wait_port 8000 20; then
        log_msg "${GREEN}[ChromaDB]${NC} 재시작 완료"
    else
        log_msg "${RED}[ChromaDB]${NC} 재시작 실패"
        return 1
    fi
}

# --- Scheduler ---
scheduler_start() {
    log_msg "${BLUE}[Scheduler]${NC} 시작 중..."
    if [ -f "$SCHEDULER_PID" ]; then
        local pid
        pid=$(cat "$SCHEDULER_PID" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_msg "${YELLOW}[Scheduler]${NC} 이미 실행 중 (PID $pid)"
            return 0
        fi
    fi
    pkill -f "agri_ai_core\.scheduler" 2>/dev/null || true
    sleep 1
    cd "$BASE_DIR"
    $PYTHON_BIN -m agri_ai_core.scheduler >> "$LOG_DIR/scheduler.log" 2>&1 &
    local pid=$!
    echo $pid > "$SCHEDULER_PID"
    log_msg "${GREEN}[Scheduler]${NC} 시작 완료 (PID $pid)"
}

scheduler_stop() {
    log_msg "${BLUE}[Scheduler]${NC} 종료 중..."
    if [ -f "$SCHEDULER_PID" ]; then
        local pid
        pid=$(cat "$SCHEDULER_PID" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 2
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
        fi
        rm -f "$SCHEDULER_PID"
    fi
    pkill -f "agri_ai_core\.scheduler" 2>/dev/null || true
    log_msg "${GREEN}[Scheduler]${NC} 종료 완료"
}

scheduler_restart() {
    scheduler_stop
    sleep 1
    scheduler_start
}

# --- FastAPI ---
fastapi_start() {
    log_msg "${BLUE}[FastAPI]${NC} 시작 중 (port ${API_PORT:-8002})..."
    if [ -f "$API_PID" ]; then
        local pid
        pid=$(cat "$API_PID" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_msg "${YELLOW}[FastAPI]${NC} 이미 실행 중 (PID $pid)"
            return 0
        fi
    fi
    # __pycache__ 정리
    find "$BASE_DIR/agri_ai_core" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    # 기존 프로세스 정리
    pkill -f "python.*agri_ai_core\.api" 2>/dev/null || true
    sleep 1
    cd "$BASE_DIR"
    $PYTHON_BIN -m agri_ai_core.api >> "$LOG_DIR/api.log" 2>&1 &
    local pid=$!
    echo $pid > "$API_PID"
    if wait_port "${API_PORT:-8002}" 15; then
        log_msg "${GREEN}[FastAPI]${NC} 시작 완료 (PID $pid, port ${API_PORT:-8002})"
    else
        log_msg "${YELLOW}[FastAPI]${NC} 시작됨 (PID $pid, 포트 대기 중)"
    fi
}

fastapi_stop() {
    log_msg "${BLUE}[FastAPI]${NC} 종료 중..."
    if [ -f "$API_PID" ]; then
        local pid
        pid=$(cat "$API_PID" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 2
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
        fi
        rm -f "$API_PID"
    fi
    pkill -f "python.*agri_ai_core\.api" 2>/dev/null || true
    log_msg "${GREEN}[FastAPI]${NC} 종료 완료"
}

fastapi_restart() {
    fastapi_stop
    sleep 1
    fastapi_start
}

# --- Spring Boot (jayeondeule_web) ---
springboot_start() {
    log_msg "${BLUE}[Spring Boot]${NC} 시작 중 (port 9090)..."
    sudo systemctl start jayeondeule_web.service
    if wait_port 9090 30; then
        log_msg "${GREEN}[Spring Boot]${NC} 시작 완료 (port 9090)"
    else
        log_msg "${RED}[Spring Boot]${NC} 시작 실패"
        return 1
    fi
}

springboot_stop() {
    log_msg "${BLUE}[Spring Boot]${NC} 종료 중..."
    sudo systemctl stop jayeondeule_web.service
    log_msg "${GREEN}[Spring Boot]${NC} 종료 완료"
}

springboot_restart() {
    log_msg "${BLUE}[Spring Boot]${NC} 재시작 중..."
    sudo systemctl restart jayeondeule_web.service
    if wait_port 9090 30; then
        log_msg "${GREEN}[Spring Boot]${NC} 재시작 완료"
    else
        log_msg "${RED}[Spring Boot]${NC} 재시작 실패"
        return 1
    fi
}

# --- Nginx ---
nginx_start() {
    log_msg "${BLUE}[Nginx]${NC} 시작 중..."
    sudo systemctl start nginx.service
    if wait_port 80 10; then
        log_msg "${GREEN}[Nginx]${NC} 시작 완료 (port 80, 8080)"
    else
        log_msg "${RED}[Nginx]${NC} 시작 실패"
        return 1
    fi
}

nginx_stop() {
    log_msg "${BLUE}[Nginx]${NC} 종료 중..."
    sudo systemctl stop nginx.service
    log_msg "${GREEN}[Nginx]${NC} 종료 완료"
}

nginx_restart() {
    log_msg "${BLUE}[Nginx]${NC} 재시작 중..."
    sudo systemctl restart nginx.service
    if wait_port 80 10; then
        log_msg "${GREEN}[Nginx]${NC} 재시작 완료"
    else
        log_msg "${RED}[Nginx]${NC} 재시작 실패"
        return 1
    fi
}

# --- SearXNG (Docker) ---
searxng_start() {
    log_msg "${BLUE}[SearXNG]${NC} 시작 중 (port 8888)..."
    if docker ps --filter "name=searxng" --format "{{.Names}}" 2>/dev/null | grep -q "searxng"; then
        log_msg "${YELLOW}[SearXNG]${NC} 이미 실행 중"
        return 0
    fi
    if docker ps -a --filter "name=searxng" --format "{{.Names}}" 2>/dev/null | grep -q "searxng"; then
        docker start searxng >/dev/null 2>&1
    else
        docker compose -f "$BASE_DIR/setup/searxng/docker-compose.yml" up -d >/dev/null 2>&1
    fi
    if wait_port 8888 15; then
        log_msg "${GREEN}[SearXNG]${NC} 시작 완료 (port 8888)"
    else
        log_msg "${RED}[SearXNG]${NC} 시작 실패"
        return 1
    fi
}

searxng_stop() {
    log_msg "${BLUE}[SearXNG]${NC} 종료 중..."
    docker stop searxng >/dev/null 2>&1 || true
    log_msg "${GREEN}[SearXNG]${NC} 종료 완료"
}

searxng_restart() {
    searxng_stop
    sleep 2
    searxng_start
}

# --- React (빌드 전용) ---
react_build() {
    log_msg "${BLUE}[React]${NC} 빌드 시작..."
    cd "$BASE_DIR/web/frontend"
    npm run build >> "$LOG_DIR/react_build.log" 2>&1
    if [ $? -eq 0 ]; then
        log_msg "${GREEN}[React]${NC} 빌드 완료"
    else
        log_msg "${RED}[React]${NC} 빌드 실패 (로그: $LOG_DIR/react_build.log)"
        return 1
    fi
}

# ─── 전체 서비스 관리 ───

# agriAiCore.service(run_services.sh)가 실행 중이면 충돌 방지를 위해 중지
_stop_legacy_service() {
    if systemctl is-active --quiet agriAiCore.service 2>/dev/null; then
        log_msg "${YELLOW}[agriAiCore.service]${NC} 충돌 방지를 위해 중지..."
        sudo systemctl stop agriAiCore.service 2>/dev/null || true
        sleep 2
    fi
}

all_start() {
    _stop_legacy_service
    log_msg "${BOLD}========== 전체 서비스 시작 ==========${NC}"
    ollama_start
    postgresql_start
    chromadb_start
    scheduler_start
    fastapi_start
    searxng_start
    springboot_start
    nginx_start
    log_msg "${BOLD}========== 전체 서비스 시작 완료 ==========${NC}"
    show_status
}

all_stop() {
    _stop_legacy_service
    log_msg "${BOLD}========== 전체 서비스 종료 ==========${NC}"
    nginx_stop
    springboot_stop
    searxng_stop
    fastapi_stop
    scheduler_stop
    chromadb_stop
    postgresql_stop
    ollama_stop
    log_msg "${BOLD}========== 전체 서비스 종료 완료 ==========${NC}"
}

all_restart() {
    log_msg "${BOLD}========== 전체 서비스 재시작 ==========${NC}"
    all_stop
    sleep 3
    all_start
}

# ─── 상태 표시 ───
show_status() {
    echo ""
    echo -e "${BOLD}  서비스 상태:${NC}"
    echo -e "  ─────────────────────────────────────────────"
    printf "  %-4s %-16s %-8s %s\n" "#" "서비스" "포트" "상태"
    echo -e "  ─────────────────────────────────────────────"
    printf "  %-4s %-16s %-8s " "1" "Ollama" "11434"
    check_status "Ollama" port 11434
    printf "  %-4s %-16s %-8s " "2" "PostgreSQL" "5432"
    check_status "PostgreSQL" port 5432
    printf "  %-4s %-16s %-8s " "3" "ChromaDB" "8000"
    check_status "ChromaDB" port 8000
    printf "  %-4s %-16s %-8s " "4" "Scheduler" "-"
    check_status "Scheduler" pid_file "$SCHEDULER_PID"
    printf "  %-4s %-16s %-8s " "5" "FastAPI" "${API_PORT:-8002}"
    check_status "FastAPI" port "${API_PORT:-8002}"
    printf "  %-4s %-16s %-8s " "6" "SearXNG" "8888"
    check_status "SearXNG" port 8888
    printf "  %-4s %-16s %-8s " "7" "Spring Boot" "9090"
    check_status "Spring Boot" port 9090
    printf "  %-4s %-16s %-8s " "8" "Nginx" "80"
    check_status "Nginx" port 80
    printf "  %-4s %-16s %-8s " "9" "React" "(빌드)"
    echo -e "${YELLOW}● 빌드 전용${NC}"
    echo -e "  ─────────────────────────────────────────────"
    echo ""
}

# ─── 메뉴 표시 ───
show_menu() {
    echo -e "  ${BOLD}서비스 선택:${NC}"
    echo ""
    echo -e "   ${CYAN}0${NC}. ALL (전체 서비스)"
    echo -e "   ${CYAN}1${NC}. Ollama          (LLM 서버,       port 11434)"
    echo -e "   ${CYAN}2${NC}. PostgreSQL       (관계형 DB,      port 5432)"
    echo -e "   ${CYAN}3${NC}. ChromaDB         (벡터 DB,        port 8000)"
    echo -e "   ${CYAN}4${NC}. Scheduler        (스케줄/환경제어)"
    echo -e "   ${CYAN}5${NC}. FastAPI          (REST API,      port ${API_PORT:-8002})"
    echo -e "   ${CYAN}6${NC}. SearXNG          (메타검색엔진,   port 8888)"
    echo -e "   ${CYAN}7${NC}. Spring Boot      (웹 백엔드,      port 9090)"
    echo -e "   ${CYAN}8${NC}. Nginx            (웹서버,         port 80)"
    echo -e "   ${CYAN}9${NC}. React Build      (프론트엔드 빌드)"
    echo ""
    echo -n -e "  번호 입력 (q=종료): "
}

# 서비스 번호에 따른 실행
execute_service() {
    local action="$1" num="$2"

    case "$num" in
        0) # ALL
            case "$action" in
                start)   all_start ;;
                stop)    all_stop ;;
                restart) all_restart ;;
                status)  show_status ;;
            esac
            ;;
        1) # Ollama
            case "$action" in
                start)   ollama_start ;;
                stop)    ollama_stop ;;
                restart) ollama_restart ;;
                status)  printf "  Ollama: "; check_status "Ollama" port 11434 ;;
            esac
            ;;
        2) # PostgreSQL
            case "$action" in
                start)   postgresql_start ;;
                stop)    postgresql_stop ;;
                restart) postgresql_restart ;;
                status)  printf "  PostgreSQL: "; check_status "PostgreSQL" port 5432 ;;
            esac
            ;;
        3) # ChromaDB
            case "$action" in
                start)   chromadb_start ;;
                stop)    chromadb_stop ;;
                restart) chromadb_restart ;;
                status)  printf "  ChromaDB: "; check_status "ChromaDB" port 8000 ;;
            esac
            ;;
        4) # Scheduler
            case "$action" in
                start)   scheduler_start ;;
                stop)    scheduler_stop ;;
                restart) scheduler_restart ;;
                status)  printf "  Scheduler: "; check_status "Scheduler" pid_file "$SCHEDULER_PID" ;;
            esac
            ;;
        5) # FastAPI
            case "$action" in
                start)   fastapi_start ;;
                stop)    fastapi_stop ;;
                restart) fastapi_restart ;;
                status)  printf "  FastAPI: "; check_status "FastAPI" port "${API_PORT:-8002}" ;;
            esac
            ;;
        6) # SearXNG
            case "$action" in
                start)   searxng_start ;;
                stop)    searxng_stop ;;
                restart) searxng_restart ;;
                status)  printf "  SearXNG: "; check_status "SearXNG" port 8888 ;;
            esac
            ;;
        7) # Spring Boot
            case "$action" in
                start)   springboot_start ;;
                stop)    springboot_stop ;;
                restart) springboot_restart ;;
                status)  printf "  Spring Boot: "; check_status "Spring Boot" port 9090 ;;
            esac
            ;;
        8) # Nginx
            case "$action" in
                start)   nginx_start ;;
                stop)    nginx_stop ;;
                restart) nginx_restart ;;
                status)  printf "  Nginx: "; check_status "Nginx" port 80 ;;
            esac
            ;;
        9) # React Build
            case "$action" in
                start|restart) react_build ;;
                stop) log_msg "${YELLOW}[React]${NC} 빌드 전용 서비스입니다 (stop 불필요)" ;;
                status) echo -e "  React: ${YELLOW}● 빌드 전용${NC}" ;;
            esac
            ;;
        *)
            echo -e "  ${RED}잘못된 번호입니다.${NC}"
            return 1
            ;;
    esac
}

# ─── 메인 ───

# 인자 확인
ACTION="${1:-}"
SERVICE_NUM="${2:-}"

# 사용법 출력
usage() {
    echo ""
    echo -e "  ${BOLD}사용법:${NC}"
    echo -e "    agriCoreCtrl ${CYAN}<명령>${NC} [서비스번호]"
    echo ""
    echo -e "  ${BOLD}명령:${NC}"
    echo -e "    ${CYAN}start${NC}     서비스 시작"
    echo -e "    ${CYAN}stop${NC}      서비스 종료"
    echo -e "    ${CYAN}restart${NC}   서비스 재시작"
    echo -e "    ${CYAN}status${NC}    서비스 상태 확인"
    echo ""
    echo -e "  ${BOLD}예시:${NC}"
    echo -e "    agriCoreCtrl restart        # 메뉴에서 서비스 선택"
    echo -e "    agriCoreCtrl restart 0      # 전체 재시작"
    echo -e "    agriCoreCtrl restart 5      # FastAPI만 재시작"
    echo -e "    agriCoreCtrl status         # 전체 상태 확인"
    echo ""
}

# 명령 유효성 검사
case "$ACTION" in
    start|stop|restart|status) ;;
    "")
        print_header
        usage
        exit 0
        ;;
    *)
        echo -e "${RED}알 수 없는 명령: $ACTION${NC}"
        usage
        exit 1
        ;;
esac

# status는 번호 없이 전체 표시
if [ "$ACTION" = "status" ] && [ -z "$SERVICE_NUM" ]; then
    print_header
    show_status
    exit 0
fi

# 서비스 번호가 지정된 경우 바로 실행
if [ -n "$SERVICE_NUM" ]; then
    print_header
    execute_service "$ACTION" "$SERVICE_NUM"
    exit $?
fi

# 서비스 번호 미지정: 대화형 메뉴
print_header
show_status
show_menu

read -r choice

if [ "$choice" = "q" ] || [ "$choice" = "Q" ]; then
    echo "  종료합니다."
    exit 0
fi

# 숫자 유효성 검사
if ! [[ "$choice" =~ ^[0-9]$ ]]; then
    echo -e "  ${RED}잘못된 입력입니다.${NC}"
    exit 1
fi

echo ""
execute_service "$ACTION" "$choice"
echo ""
