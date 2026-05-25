#!/bin/bash
# =========================================================================
# [1단계] 시스템 필수 패키지 설치
# OS 기본 패키지 + NVIDIA 드라이버 + CUDA + Ollama + Docker
# 신규 Ubuntu 24.04 서버에서 최초 1회 실행
# =========================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "=========================================="
echo "  [1단계] 시스템 필수 패키지 설치"
echo "=========================================="
echo ""

# -----------------------------------------------------------------
# 1. 시스템 업데이트
# -----------------------------------------------------------------
log_info "[1/7] 시스템 업데이트..."
sudo apt update -y && sudo apt upgrade -y
log_info "시스템 업데이트 완료"

# -----------------------------------------------------------------
# 2. 기본 패키지
# -----------------------------------------------------------------
log_info "[2/7] 기본 패키지 설치..."
sudo apt install -y \
    build-essential curl wget git vim \
    python3 python3-dev python3-venv python3-pip \
    libpq-dev libffi-dev libssl-dev \
    sshpass autossh \
    tesseract-ocr tesseract-ocr-kor \
    unzip htop net-tools

log_info "기본 패키지 설치 완료"

# -----------------------------------------------------------------
# 3. Nginx
# -----------------------------------------------------------------
log_info "[3/7] Nginx 설치..."
sudo apt install -y nginx
sudo systemctl enable nginx
log_info "Nginx: $(nginx -v 2>&1)"

# -----------------------------------------------------------------
# 4. PostgreSQL 16
# -----------------------------------------------------------------
log_info "[4/7] PostgreSQL 16 설치..."
if ! command -v psql &>/dev/null; then
    sudo apt install -y postgresql-16 postgresql-client-16
fi
sudo systemctl enable postgresql
log_info "PostgreSQL: $(psql --version 2>&1)"

# -----------------------------------------------------------------
# 5. Java 21 + Node.js 20
# -----------------------------------------------------------------
log_info "[5/7] Java 21 + Node.js 20 설치..."
sudo apt install -y openjdk-21-jdk-headless
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
    sudo apt install -y nodejs
fi
log_info "Java: $(java -version 2>&1 | head -1)"
log_info "Node: $(node --version 2>&1)"

# -----------------------------------------------------------------
# 6. Docker
# -----------------------------------------------------------------
log_info "[6/7] Docker 설치..."
if ! command -v docker &>/dev/null; then
    sudo apt install -y docker.io docker-compose-plugin
    sudo usermod -aG docker $(whoami)
fi
log_info "Docker: $(docker --version 2>&1)"

# -----------------------------------------------------------------
# 7. Ollama
# -----------------------------------------------------------------
log_info "[7/7] Ollama 설치..."
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
log_info "Ollama: $(ollama --version 2>&1)"

echo ""
echo "=========================================="
log_info "[1단계] 시스템 패키지 설치 완료"
echo "=========================================="
echo ""
log_warn "NVIDIA GPU 드라이버가 필요하면 별도 설치:"
echo "  sudo apt install -y nvidia-driver-580"
echo "  sudo reboot"
echo ""
log_info "다음 단계: bash setup/2.install_nvidia_gpu.sh (GPU 사용 시)"
echo ""
