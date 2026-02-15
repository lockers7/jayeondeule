#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# agriAiCore 필수 패키지 일괄 설치 스크립트
# -----------------------------------------
# 다른 PC에 소스만 복사한 뒤, 이 스크립트 하나로
# agriAiCore 실행에 필요한 모든 패키지를 설치합니다.
#
# 사용법:
#   chmod +x scripts/requirement.sh
#   ./scripts/requirement.sh
#
# 참조: docs/.requirement.md
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

# 프로젝트 루트 (이 스크립트의 상위 디렉토리)
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/venv"

echo "=========================================="
echo "  agriAiCore 필수 패키지 설치"
echo "=========================================="
echo ""
log_info "프로젝트 경로: $PROJECT_DIR"
echo ""

# =================================================================
# 1단계: Python 버전 확인
# =================================================================
log_info "[1/5] Python 버전 확인..."

if ! command -v python3 &> /dev/null; then
    log_error "python3이 설치되어 있지 않습니다."
    log_error "먼저 Python 3.9 이상을 설치하세요: sudo apt install python3 python3-venv"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    log_error "Python 3.9 이상이 필요합니다. 현재: $PYTHON_VERSION"
    exit 1
fi
log_info "Python $PYTHON_VERSION 확인 완료"

# =================================================================
# 2단계: [OutVenv] 시스템 패키지 설치
# =================================================================
log_info "[2/5] 시스템 패키지 설치 (sudo 권한 필요)..."

sudo apt update -qq
sudo apt install -y \
    python3-dev \
    python3-venv \
    build-essential \
    libpq-dev \
    libffi-dev

log_info "시스템 패키지 설치 완료"

# =================================================================
# 3단계: venv 가상환경 생성
# =================================================================
log_info "[3/5] 가상환경 확인..."

if [ -d "$VENV_DIR" ]; then
    log_info "기존 venv 발견: $VENV_DIR"
else
    log_info "venv 생성 중..."
    python3 -m venv "$VENV_DIR"
    log_info "venv 생성 완료"
fi

# =================================================================
# 4단계: [InVenv] Python 패키지 설치
# =================================================================
log_info "[4/5] Python 패키지 설치 (venv 내부)..."

# venv 활성화
source "$VENV_DIR/bin/activate"

# pip 업그레이드
pip install --upgrade pip -q

# --- 핵심 프레임워크 ---
pip install \
    pydantic \
    reflex \
    fastapi

# --- 데이터베이스 / 데이터 ---
pip install \
    psycopg2-binary \
    numpy \
    pandas

# --- LLM / AI ---
pip install \
    ollama \
    chromadb \
    'uvicorn[standard]>=0.18.3'

# --- 유틸리티 ---
pip install \
    python-dotenv \
    requests \
    apscheduler

log_info "Python 패키지 설치 완료"

# =================================================================
# 5단계: 설치 검증
# =================================================================
log_info "[5/5] 설치 검증..."

FAILED=0
for pkg in pydantic reflex fastapi psycopg2 numpy pandas ollama chromadb uvicorn dotenv requests apscheduler; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "  [OK] $pkg"
    else
        echo "  [FAIL] $pkg"
        FAILED=1
    fi
done

if [ $FAILED -eq 1 ]; then
    log_warn "일부 패키지 import 실패. 위 로그를 확인하세요."
else
    log_info "모든 패키지 검증 완료"
fi

# =================================================================
# 완료
# =================================================================
echo ""
echo "=========================================="
log_info "설치 완료!"
echo "=========================================="
echo ""
log_info "다음 단계:"
log_info "  1. .env 파일 확인/편집 (DB 접속 정보 등)"
log_info "  2. venv 활성화:  source $VENV_DIR/bin/activate"
log_info "  3. 서비스 실행:  ./run_services.sh"
echo ""
log_info "설치된 패키지 확인:  pip list"
echo ""
