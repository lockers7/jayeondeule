#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# agriAiCore 필수 패키지 관리 스크립트
# -----------------------------------------
# requirements.txt 기반으로 전체 설치 또는 일괄 업그레이드를 수행합니다.
#
# 사용법:
#   ./setup/requirement.sh              # 전체 설치 (신규 환경)
#   ./setup/requirement.sh install      # 전체 설치
#   ./setup/requirement.sh upgrade      # 설치된 모든 패키지 일괄 업그레이드
#   ./setup/requirement.sh freeze       # 현재 설치된 패키지로 requirements.txt 갱신
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
REQUIREMENTS_FILE="$PROJECT_DIR/setup/system-configs/data/requirements.txt"

# 실행 모드 (install / upgrade / freeze)
MODE="${1:-install}"

echo "=========================================="
echo "  agriAiCore 패키지 관리 [$MODE]"
echo "=========================================="
echo ""
log_info "프로젝트 경로: $PROJECT_DIR"
log_info "requirements: $REQUIREMENTS_FILE"
echo ""

if [ ! -f "$REQUIREMENTS_FILE" ]; then
    log_error "requirements.txt를 찾을 수 없습니다: $REQUIREMENTS_FILE"
    exit 1
fi

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
# 4단계: [InVenv] Python 패키지 관리
# =================================================================

# venv 활성화
source "$VENV_DIR/bin/activate"

# pip 업그레이드
pip install --upgrade pip -q

case "$MODE" in
    install)
        log_info "[4/5] requirements.txt 기반 전체 설치..."
        pip install -r "$REQUIREMENTS_FILE"
        log_info "패키지 설치 완료"
        ;;
    upgrade)
        log_info "[4/5] requirements.txt 기반 일괄 업그레이드..."
        pip install --upgrade -r "$REQUIREMENTS_FILE"
        log_info "패키지 업그레이드 완료"

        # 업그레이드 후 requirements.txt 자동 갱신
        log_info "requirements.txt 갱신 중..."
        pip freeze > "$REQUIREMENTS_FILE"
        cp "$REQUIREMENTS_FILE" "$PROJECT_DIR/.backup/data/requirements.txt" 2>/dev/null || true
        log_info "requirements.txt 갱신 완료"
        ;;
    freeze)
        log_info "[4/5] 현재 설치된 패키지로 requirements.txt 갱신..."
        pip freeze > "$REQUIREMENTS_FILE"
        cp "$REQUIREMENTS_FILE" "$PROJECT_DIR/.backup/data/requirements.txt" 2>/dev/null || true
        log_info "requirements.txt 갱신 완료 ($(wc -l < "$REQUIREMENTS_FILE")개 패키지)"
        ;;
    *)
        log_error "알 수 없는 모드: $MODE"
        log_error "사용법: $0 [install|upgrade|freeze]"
        exit 1
        ;;
esac

# =================================================================
# 5단계: 핵심 패키지 검증
# =================================================================
log_info "[5/5] 핵심 패키지 검증..."

FAILED=0
for pkg in pydantic fastapi psycopg2 numpy pandas ollama chromadb uvicorn dotenv requests apscheduler faster_whisper edge_tts av fitz PyPDF2; do
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
    log_info "모든 핵심 패키지 검증 완료"
fi

# =================================================================
# 완료
# =================================================================
echo ""
echo "=========================================="
log_info "$MODE 완료! (총 $(pip list --format=columns 2>/dev/null | tail -n +3 | wc -l)개 패키지)"
echo "=========================================="
echo ""
log_info "사용법:"
log_info "  ./setup/requirement.sh install   — 전체 설치"
log_info "  ./setup/requirement.sh upgrade   — 일괄 업그레이드"
log_info "  ./setup/requirement.sh freeze    — requirements.txt 갱신"
echo ""
