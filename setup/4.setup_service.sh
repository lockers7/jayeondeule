#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# AgriAI Core + ChromaDB systemd 서비스 설치 스크립트
# agriAiCore.service 단일 오케스트레이션으로 관리합니다.
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
# 1. 기존 불필요 서비스 정리
# -----------------------------------------------------------------
for svc in fastapi.service; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo -e "${YELLOW}기존 $svc 중지 중...${NC}"
        sudo systemctl stop "$svc"
    fi
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        echo -e "${YELLOW}기존 $svc 비활성화 중...${NC}"
        sudo systemctl disable "$svc"
    fi
    if [ -f "/etc/systemd/system/$svc" ]; then
        echo -e "${YELLOW}기존 $svc 제거 중...${NC}"
        sudo rm "/etc/systemd/system/$svc"
    fi
done

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
# 4. systemd 데몬 리로드 및 서비스 활성화
# -----------------------------------------------------------------
echo -e "${GREEN}systemd 데몬 리로드 중...${NC}"
sudo systemctl daemon-reload

echo -e "${GREEN}서비스 활성화 중...${NC}"
sudo systemctl enable chromadb.service
sudo systemctl enable agriAiCore.service

echo ""
echo -e "${GREEN}=========================================="
echo "  설치 완료!"
echo "==========================================${NC}"
echo ""
echo "사용 방법:"
echo "  - ChromaDB 시작:    sudo systemctl start chromadb"
echo "  - 기본 시작:        sudo systemctl start chromadb agriAiCore"
echo "  - 기본 중지:        sudo systemctl stop agriAiCore chromadb"
echo "  - 상태 확인:        sudo systemctl status chromadb agriAiCore"
echo "  - 로그 확인:        sudo journalctl -u chromadb -u agriAiCore -f"
echo ""
echo "서비스를 시작하시겠습니까? (y/n)"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}서비스 시작 중...${NC}"
    sudo systemctl start chromadb
    sleep 3
    sudo systemctl start agriAiCore
    sleep 3
    sudo systemctl status chromadb agriAiCore --no-pager
    echo ""
    echo -e "${GREEN}서비스가 시작되었습니다!${NC}"
    echo "  - ChromaDB:   http://localhost:8000"
    echo "  - REST API:   http://localhost:8002"
else
    echo "서비스를 나중에 시작하려면: sudo systemctl start chromadb agriAiCore"
fi
