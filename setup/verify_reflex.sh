#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Reflex 실행 상태 확인 스크립트
# =========================================================================

echo "=========================================="
echo "  Reflex 실행 상태 확인"
echo "=========================================="
echo ""

# 1. 서비스 상태 확인
echo "[1] agriAiCore 서비스 상태:"
sudo systemctl status agriAiCore --no-pager | head -20
echo ""

# 2. UI_MODE 환경 변수 확인
echo "[2] UI_MODE 설정:"
cat /workspace/jayeondeule/.env | grep "UI_MODE"
echo ""

# 3. Reflex 프로세스 확인
echo "[3] Reflex 프로세스:"
ps aux | grep -E "(reflex|python.*reflex)" | grep -v grep || echo "  - Reflex 프로세스 없음"
echo ""

# 4. 포트 확인
echo "[4] 포트 사용 상태:"
echo "  - Port 3000 (Reflex Frontend):"
ss -tuln | grep ":3000" || echo "    포트 열려있지 않음"
echo "  - Port 8001 (Reflex Backend):"
ss -tuln | grep ":8001" || echo "    포트 열려있지 않음"
echo "  - Port 8501 (Streamlit):"
ss -tuln | grep ":8501" || echo "    포트 열려있지 않음"
echo ""

# 5. PID 파일 확인
echo "[5] PID 파일:"
if [ -f "/tmp/reflex.pid" ]; then
    REFLEX_PID=$(cat /tmp/reflex.pid)
    echo "  - Reflex PID: $REFLEX_PID"
    if kill -0 "$REFLEX_PID" 2>/dev/null; then
        echo "    ✓ 프로세스 실행 중"
    else
        echo "    ✗ 프로세스 종료됨"
    fi
else
    echo "  - Reflex PID 파일 없음"
fi
echo ""

# 6. 로그 확인
echo "[6] Reflex 로그 (최근 20줄):"
if [ -f "/workspace/jayeondeule/logs/reflex.log" ]; then
    tail -20 /workspace/jayeondeule/logs/reflex.log
else
    echo "  - 로그 파일 없음"
fi
echo ""

# 7. HTTP 응답 확인
echo "[7] HTTP 응답 테스트:"
echo "  - Frontend (3000):"
curl -I http://localhost:3000 2>/dev/null | head -5 || echo "    연결 실패"
echo "  - Backend (8001):"
curl -I http://localhost:8001 2>/dev/null | head -5 || echo "    연결 실패"
echo ""

echo "=========================================="
echo "  확인 완료"
echo "=========================================="
