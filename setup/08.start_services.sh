#!/bin/bash
# =========================================================================
# [8단계] 서비스 활성화 + Ollama 모델 다운로드 + 전체 시작
# 모든 설치/빌드 완료 후 최종 서비스 시작
# =========================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$PROJECT_DIR/setup/system-configs/data"

echo "=========================================="
echo "  [8단계] 서비스 활성화 + 시작"
echo "=========================================="
echo ""

# -----------------------------------------------------------------
# 1. Systemd 서비스 활성화
# -----------------------------------------------------------------
log_info "[1/4] 서비스 활성화..."
for svc in nginx postgresql ollama chromadb; do
    sudo systemctl enable "$svc" 2>/dev/null && log_info "  $svc: enabled" || true
done

# -----------------------------------------------------------------
# 2. Ollama 모델 다운로드
# -----------------------------------------------------------------
log_info "[2/4] Ollama 모델 다운로드..."
sudo systemctl start ollama 2>/dev/null || true
sleep 3

MODEL_LIST="$DATA_DIR/ollama_models.txt"
if [ -f "$MODEL_LIST" ]; then
    tail -n +2 "$MODEL_LIST" | awk '{print $1}' | while read model; do
        [ -z "$model" ] && continue
        if ollama list 2>/dev/null | grep -q "^${model}"; then
            log_info "  $model: 이미 설치됨"
        else
            log_info "  $model 다운로드 중..."
            ollama pull "$model" 2>&1 | tail -1
        fi
    done
else
    log_warn "  모델 목록 없음. 기본 모델 다운로드:"
    for model in "mistral-small3.2:latest" "bge-m3:latest"; do
        ollama pull "$model" 2>&1 | tail -1 || true
    done
fi

# -----------------------------------------------------------------
# 3. 전체 서비스 시작
# -----------------------------------------------------------------
log_info "[3/4] 전체 서비스 시작..."
sudo systemctl start nginx
sudo systemctl start postgresql
sudo systemctl start ollama
sudo systemctl start chromadb
sleep 3

# agriAiCore로 나머지 서비스 시작
if [ -x "$PROJECT_DIR/agriAiCore" ]; then
    sudo "$PROJECT_DIR/agriAiCore" start 0
fi

# -----------------------------------------------------------------
# 4. 상태 확인
# -----------------------------------------------------------------
log_info "[4/4] 서비스 상태 확인..."
echo ""
for svc in nginx postgresql ollama chromadb; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
    if [ "$status" = "active" ]; then
        echo -e "  ${GREEN}●${NC} $svc: $status"
    else
        echo -e "  ${YELLOW}○${NC} $svc: $status"
    fi
done

echo ""
echo "=========================================="
log_info "[8단계] 서비스 시작 완료"
echo "=========================================="
echo ""
log_info "시스템 복원이 완료되었습니다!"
echo ""
log_info "접속 URL:"
echo "  - 모니터링: https://lockers7.iptime.org/farm/1/monitor"
echo "  - AI 채팅:  https://lockers7.iptime.org/ai-chat"
echo "  - 쇼핑몰:   https://lockers7.iptime.org:5100"
echo "  - API:      http://localhost:8002/docs"
echo ""
log_warn "확인 필요:"
echo "  1. .env 파일 비밀번호/API 키 확인"
echo "  2. Nginx server_name 변경 (새 도메인/IP)"
echo "  3. 공유기 포트포워드 설정 (80, 443, 3389, 5432 등)"
echo ""
