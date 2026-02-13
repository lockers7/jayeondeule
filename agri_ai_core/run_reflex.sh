#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Reflex UI 실행 스크립트
# -----------------------------------------
# Reflex 기반 웹 UI를 실행합니다.
#
# 모드:
#   STANDALONE=true  → startup.py 초기화 포함 (독립 실행)
#   STANDALONE=false → 초기화 없이 UI만 실행 (agriAiCore와 함께)
#
# 사용법:
#   chmod +x agri_ai_core/run_reflex.sh
#   ./agri_ai_core/run_reflex.sh                  # 독립 실행 (기본)
#   STANDALONE=false ./agri_ai_core/run_reflex.sh # UI만 실행
# =========================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 프로젝트 경로
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/agri_ai_core"
VENV_DIR="$ROOT_DIR/venv"

# 실행 모드 (기본값: standalone)
STANDALONE="${STANDALONE:-true}"
# Reflex 실행 환경 (dev/prod, 기본값: prod)
REFLEX_ENV="${REFLEX_ENV:-prod}"
# Granian 미설치 환경 대응: 기본적으로 Uvicorn 백엔드 사용
REFLEX_USE_GRANIAN="${REFLEX_USE_GRANIAN:-false}"

echo "=========================================="
echo "  Reflex UI 실행"
if [ "$STANDALONE" = "true" ]; then
    echo "  모드: Standalone (백그라운드 서비스 포함)"
else
    echo "  모드: UI Only (백그라운드 서비스 제외)"
fi
echo "=========================================="
echo ""
log_info "프로젝트 경로: $ROOT_DIR"
echo ""

# venv 확인
if [ ! -d "$VENV_DIR" ]; then
    log_error "가상환경이 없습니다. 먼저 setup/requirement.sh를 실행하세요."
    exit 1
fi

# venv 활성화
log_info "가상환경 활성화 중..."
source "$VENV_DIR/bin/activate"

# agri_ai_core 절대 import가 가능하도록 루트 경로 추가
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export REFLEX_USE_GRANIAN

# Reflex 초기화 (최초 1회만 필요)
if [ ! -d "$APP_DIR/.web" ]; then
    log_info "Reflex 초기화 중..."
    cd "$APP_DIR"
    reflex init --template blank
fi

# Standalone 모드: 백그라운드 서비스 시작
if [ "$STANDALONE" = "true" ]; then
    log_info "백그라운드 서비스 초기화 중 (ChromaDB, 스케줄러)..."

    # Python으로 startup 초기화 실행
    $VENV_DIR/bin/python -c "
from agri_ai_core.startup import initialize_app
import sys

try:
    initialize_app()
    print('[INFO] 백그라운드 서비스 초기화 완료')
except Exception as e:
    print(f'[WARN] 백그라운드 서비스 초기화 실패: {e}', file=sys.stderr)
    print('[INFO] UI만 실행합니다...', file=sys.stderr)
" 2>&1 | while IFS= read -r line; do
        if [[ "$line" == *"[INFO]"* ]]; then
            echo -e "${GREEN}${line}${NC}"
        elif [[ "$line" == *"[WARN]"* ]] || [[ "$line" == *"[ERROR]"* ]]; then
            echo -e "${YELLOW}${line}${NC}"
        else
            echo "$line"
        fi
    done

    echo ""
fi

# Reflex 실행
log_info "Reflex UI 시작 중..."
log_info "접속 주소:"
log_info "  - Frontend: http://localhost:3000"
if [ "$REFLEX_ENV" = "prod" ]; then
    log_info "  - API/Backend: Frontend와 동일 포트(3000) 사용"
else
    log_info "  - Backend:  http://localhost:8001 (API 전용)"
fi
echo ""

cd "$APP_DIR"
if [ "$REFLEX_ENV" = "prod" ]; then
    reflex run --env prod --single-port --frontend-port 3000
else
    reflex run --env "$REFLEX_ENV" --frontend-port 3000 --backend-port 8001
fi
