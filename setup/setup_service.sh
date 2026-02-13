#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core + Reflex + ChromaDB systemd 서비스 설치 스크립트
# =========================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "  AgriAI 서비스 설치"
echo "=========================================="
echo ""

# -----------------------------------------------------------------
# 1. 기존 fastapi.service 중지 및 제거
# -----------------------------------------------------------------
if systemctl is-active --quiet fastapi.service 2>/dev/null; then
    echo -e "${YELLOW}기존 fastapi.service 중지 중...${NC}"
    sudo systemctl stop fastapi.service
fi

# 기존 agriAiCore-reflex.service 정리
if systemctl is-active --quiet agriAiCore-reflex.service 2>/dev/null; then
    echo -e "${YELLOW}기존 agriAiCore-reflex.service 중지 중...${NC}"
    sudo systemctl stop agriAiCore-reflex.service
fi

if systemctl is-enabled --quiet agriAiCore-reflex.service 2>/dev/null; then
    echo -e "${YELLOW}기존 agriAiCore-reflex.service 비활성화 중...${NC}"
    sudo systemctl disable agriAiCore-reflex.service
fi

if [ -f /etc/systemd/system/agriAiCore-reflex.service ]; then
    echo -e "${YELLOW}기존 agriAiCore-reflex.service 제거 중...${NC}"
    sudo rm /etc/systemd/system/agriAiCore-reflex.service
fi

if systemctl is-enabled --quiet fastapi.service 2>/dev/null; then
    echo -e "${YELLOW}기존 fastapi.service 비활성화 중...${NC}"
    sudo systemctl disable fastapi.service
fi

if [ -f /etc/systemd/system/fastapi.service ]; then
    echo -e "${YELLOW}기존 fastapi.service 제거 중...${NC}"
    sudo rm /etc/systemd/system/fastapi.service
fi

# -----------------------------------------------------------------
# 2. chromadb.service 설치
# -----------------------------------------------------------------
echo -e "${GREEN}chromadb.service 설치 중...${NC}"
sudo cp "$PROJECT_DIR/setup/chromadb.service" /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/chromadb.service

# -----------------------------------------------------------------
# 3. agriAiCore.service 설치
# -----------------------------------------------------------------
echo -e "${GREEN}agriAiCore.service 설치 중...${NC}"
sudo cp "$PROJECT_DIR/setup/agriAiCore.service" /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/agriAiCore.service

# -----------------------------------------------------------------
# 4. reflex.service 설치
# -----------------------------------------------------------------
echo -e "${GREEN}reflex.service 설치 중...${NC}"
sudo cp "$PROJECT_DIR/setup/reflex.service" /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/reflex.service

# -----------------------------------------------------------------
# 5. systemd 데몬 리로드 및 서비스 활성화
# -----------------------------------------------------------------
echo -e "${GREEN}systemd 데몬 리로드 중...${NC}"
sudo systemctl daemon-reload

echo -e "${GREEN}서비스 활성화 중...${NC}"
sudo systemctl enable chromadb.service
sudo systemctl enable agriAiCore.service
sudo systemctl enable reflex.service

echo ""
echo -e "${GREEN}=========================================="
echo "  설치 완료!"
echo "==========================================${NC}"
echo ""
echo "사용 방법:"
echo "  - ChromaDB 시작:    sudo systemctl start chromadb"
echo "  - agriAiCore 시작:  sudo systemctl start agriAiCore reflex"
echo "  - 전체 시작:        sudo systemctl start chromadb agriAiCore reflex"
echo "  - 전체 중지:        sudo systemctl stop agriAiCore reflex chromadb"
echo "  - 상태 확인:        sudo systemctl status chromadb agriAiCore reflex"
echo "  - 로그 확인:        sudo journalctl -u chromadb -u agriAiCore -u reflex -f"
echo ""
echo "서비스를 시작하시겠습니까? (y/n)"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}서비스 시작 중...${NC}"
    sudo systemctl start chromadb
    sleep 3
    sudo systemctl start agriAiCore
    sudo systemctl start reflex
    sleep 3
    sudo systemctl status chromadb agriAiCore reflex --no-pager
    echo ""
    echo -e "${GREEN}서비스가 시작되었습니다!${NC}"
    echo "  - ChromaDB:  http://localhost:8000"
    echo "  - Streamlit: http://localhost:8501"
    echo "  - Reflex:    http://localhost:3000"
else
    echo "서비스를 나중에 시작하려면: sudo systemctl start chromadb agriAiCore reflex"
fi
