#!/bin/bash
# =========================================================================
# [2단계] NVIDIA GPU 드라이버 + CUDA + Container Toolkit 설치
# GPU가 있는 서버에서만 실행 (GPU 없으면 건너뛰기)
# =========================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "=========================================="
echo "  [2단계] NVIDIA GPU 드라이버 설치"
echo "=========================================="
echo ""

# GPU 확인
if ! lspci | grep -i nvidia &>/dev/null; then
    log_warn "NVIDIA GPU가 감지되지 않습니다. 이 단계를 건너뜁니다."
    exit 0
fi

log_info "NVIDIA GPU 감지됨:"
lspci | grep -i nvidia
echo ""

# -----------------------------------------------------------------
# 1. NVIDIA 드라이버
# -----------------------------------------------------------------
log_info "[1/3] NVIDIA 드라이버 설치..."
if ! nvidia-smi &>/dev/null; then
    sudo apt install -y nvidia-driver-580
    log_warn "드라이버 설치 후 재부팅 필요: sudo reboot"
    log_warn "재부팅 후 이 스크립트를 다시 실행하세요."
    exit 0
else
    log_info "드라이버 이미 설치됨:"
    nvidia-smi | head -5
fi

# -----------------------------------------------------------------
# 2. NVIDIA Container Toolkit (Docker GPU 지원)
# -----------------------------------------------------------------
log_info "[2/3] NVIDIA Container Toolkit 설치..."
if ! dpkg -l | grep -q nvidia-container-toolkit; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg --yes
    echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/\$(ARCH) /" | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt update -y
    sudo apt install -y nvidia-container-toolkit
fi
log_info "NVIDIA Container Toolkit 설치 완료"

# -----------------------------------------------------------------
# 3. Ollama GPU 설정
# -----------------------------------------------------------------
log_info "[3/3] Ollama GPU 설정..."
# Ollama 서비스에 GPU 설정 추가
if [ -f /etc/systemd/system/ollama.service ]; then
    if ! grep -q "OLLAMA_MAX_LOADED_MODELS" /etc/systemd/system/ollama.service; then
        sudo sed -i '/\[Service\]/a Environment="OLLAMA_MAX_LOADED_MODELS=2"\nEnvironment="OLLAMA_FLASH_ATTENTION=1"' /etc/systemd/system/ollama.service
        sudo systemctl daemon-reload
        log_info "Ollama GPU 설정 추가 완료"
    else
        log_info "Ollama GPU 설정 이미 존재"
    fi
fi

echo ""
echo "=========================================="
log_info "[2단계] GPU 설치 완료"
echo "=========================================="
echo ""
log_info "GPU 상태: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null)"
log_info "다음 단계: bash setup/3.requirement.sh"
echo ""
