#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# 스마트팜 AI 어시스턴트 설치 스크립트
# =========================================================================

set -e  # 오류 발생 시 즉시 종료

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# -------------------------------------------------------------------
# 로깅 함수
# -------------------------------------------------------------------
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# -------------------------------------------------------------------
# Python 버전 확인
# -------------------------------------------------------------------
check_python() {
    log_info "Python 버전 확인 중..."

    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | awk '{print $2}')
        log_info "Python $PYTHON_VERSION 감지됨"

        # Python 3.9 이상 확인
        MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            log_info "✓ Python 버전 요구사항 충족"
        else
            log_error "Python 3.9 이상이 필요합니다. 현재: $PYTHON_VERSION"
            exit 1
        fi
    else
        log_error "python3을 찾을 수 없습니다."
        exit 1
    fi
}

# -------------------------------------------------------------------
# Docker 확인
# -------------------------------------------------------------------
check_docker() {
    log_info "Docker 설치 확인 중..."

    if command -v docker &> /dev/null; then
        DOCKER_VERSION=$(docker --version | awk '{print $3}' | tr -d ',')
        log_info "✓ Docker $DOCKER_VERSION 감지됨"
    else
        log_warn "Docker가 설치되어 있지 않습니다."
        log_warn "ChromaDB와 Ollama를 사용하려면 Docker가 필요합니다."
        read -p "계속 진행하시겠습니까? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    if command -v docker-compose &> /dev/null || docker compose version &> /dev/null; then
        log_info "✓ Docker Compose 감지됨"
    else
        log_warn "Docker Compose가 설치되어 있지 않습니다."
    fi
}

# -------------------------------------------------------------------
# 가상 환경 생성
# -------------------------------------------------------------------
create_venv() {
    log_info "가상 환경 확인 중..."

    if [ -d "venv" ]; then
        log_info "기존 가상 환경 발견"
        read -p "재생성하시겠습니까? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf venv
            python3 -m venv venv
            log_info "✓ 가상 환경 재생성 완료"
        fi
    else
        log_info "가상 환경 생성 중..."
        python3 -m venv venv
        log_info "✓ 가상 환경 생성 완료"
    fi
}

# -------------------------------------------------------------------
# 의존성 설치
# -------------------------------------------------------------------
install_dependencies() {
    log_info "의존성 패키지 설치 중..."

    # 가상 환경 활성화
    source venv/bin/activate

    # pip 업그레이드
    log_info "pip 업그레이드 중..."
    pip install --upgrade pip

    # requirements.txt 설치
    log_info "requirements.txt 패키지 설치 중..."
    pip install -r requirements.txt

    log_info "✓ 의존성 설치 완료"
}

# -------------------------------------------------------------------
# 환경 변수 파일 생성
# -------------------------------------------------------------------
setup_env() {
    log_info "환경 변수 설정 확인 중..."

    if [ -f ".env" ]; then
        log_info "기존 .env 파일 발견"
        log_warn ".env 파일을 수정하지 않습니다."
    else
        if [ -f ".env.example" ]; then
            log_info ".env.example을 .env로 복사 중..."
            cp .env.example .env
            log_warn "⚠ .env 파일을 편집하여 데이터베이스 정보를 입력하세요!"
        else
            log_error ".env.example 파일이 없습니다."
        fi
    fi
}

# -------------------------------------------------------------------
# 디렉토리 생성
# -------------------------------------------------------------------
create_directories() {
    log_info "필수 디렉토리 생성 중..."

    # 로그 디렉토리
    mkdir -p /workspace/jayeondeule/logs
    mkdir -p /workspace/llm/chromadb/database
    mkdir -p /workspace/llm/chromadb/cache

    log_info "✓ 디렉토리 생성 완료"
}

# -------------------------------------------------------------------
# Docker 컨테이너 시작
# -------------------------------------------------------------------
start_docker() {
    log_info "Docker 컨테이너 시작 확인..."

    if command -v docker &> /dev/null; then
        read -p "ChromaDB 컨테이너를 시작하시겠습니까? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "ChromaDB 컨테이너 시작 중..."
            docker compose up -d chromadb
            log_info "✓ ChromaDB 시작 완료"
        fi

        read -p "Ollama 컨테이너를 시작하시겠습니까? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Ollama 컨테이너 시작 중..."
            docker compose up -d ollama
            log_info "✓ Ollama 시작 완료"

            log_info "Ollama 모델 다운로드..."
            sleep 5  # Ollama가 완전히 시작될 때까지 대기
            docker exec ollama ollama pull exaone3.5:latest || log_warn "모델 다운로드 실패"
            docker exec ollama ollama pull mxbai-embed-large:latest || log_warn "임베딩 모델 다운로드 실패"
        fi
    fi
}

# -------------------------------------------------------------------
# 컴파일 테스트
# -------------------------------------------------------------------
test_compilation() {
    log_info "코드 컴파일 테스트 중..."

    source venv/bin/activate

    # 주요 파일 컴파일 테스트
    python3 -m py_compile run_to_fastapi.py
    python3 -m py_compile agri_ai_core/run_streamlit.py

    # 패키지 import 테스트
    python3 -c "import agri_ai_core; print('✓ agri_ai_core import successful')"

    log_info "✓ 컴파일 테스트 통과"
}

# -------------------------------------------------------------------
# 메인 실행
# -------------------------------------------------------------------
main() {
    echo "=========================================="
    echo "  스마트팜 AI 어시스턴트 설치"
    echo "=========================================="
    echo ""

    # 단계별 실행
    check_python
    check_docker
    create_venv
    install_dependencies
    setup_env
    create_directories
    start_docker
    test_compilation

    echo ""
    log_info "=========================================="
    log_info "  설치 완료!"
    log_info "=========================================="
    echo ""
    log_info "다음 단계:"
    log_info "  1. .env 파일 편집 (데이터베이스 정보 입력)"
    log_info "  2. FastAPI 서버 실행: python3 run_to_fastapi.py"
    log_info "  3. Streamlit UI 실행: python3 -m agri_ai_core.run_streamlit"
    echo ""
}

# 스크립트 실행
main
