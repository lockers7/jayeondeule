#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core systemd 서비스 설치 스크립트
# =========================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "  AgriAI Core 서비스 설치"
echo "=========================================="
echo ""

# 기존 fastapi.service 중지 및 제거
if systemctl is-active --quiet fastapi.service 2>/dev/null; then
    echo -e "${YELLOW}기존 fastapi.service 중지 중...${NC}"
    sudo systemctl stop fastapi.service
fi

if systemctl is-enabled --quiet fastapi.service 2>/dev/null; then
    echo -e "${YELLOW}기존 fastapi.service 비활성화 중...${NC}"
    sudo systemctl disable fastapi.service
fi

if [ -f /etc/systemd/system/fastapi.service ]; then
    echo -e "${YELLOW}기존 fastapi.service 제거 중...${NC}"
    sudo rm /etc/systemd/system/fastapi.service
fi

# 새로운 agriAiCore.service 설치
echo -e "${GREEN}agriAiCore.service 설치 중...${NC}"
sudo cp /workspace/jayeondeule/agriAiCore.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/agriAiCore.service

# systemd 데몬 리로드
echo -e "${GREEN}systemd 데몬 리로드 중...${NC}"
sudo systemctl daemon-reload

# 서비스 활성화
echo -e "${GREEN}agriAiCore.service 활성화 중...${NC}"
sudo systemctl enable agriAiCore.service

echo ""
echo -e "${GREEN}=========================================="
echo "  설치 완료!"
echo "==========================================${NC}"
echo ""
echo "사용 방법:"
echo "  - 서비스 시작: sudo systemctl start agriAiCore"
echo "  - 서비스 중지: sudo systemctl stop agriAiCore"
echo "  - 서비스 재시작: sudo systemctl restart agriAiCore"
echo "  - 서비스 상태: sudo systemctl status agriAiCore"
echo "  - 로그 확인: sudo journalctl -u agriAiCore -f"
echo ""
echo "서비스 시작하시겠습니까? (y/n)"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}서비스 시작 중...${NC}"
    sudo systemctl start agriAiCore
    sleep 3
    sudo systemctl status agriAiCore --no-pager
    echo ""
    echo -e "${GREEN}서비스가 시작되었습니다!${NC}"
    echo "  - FastAPI: http://localhost:8088"
    echo "  - Streamlit: http://localhost:8501"
else
    echo "서비스를 나중에 시작하려면: sudo systemctl start agriAiCore"
fi
