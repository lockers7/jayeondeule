#!/bin/bash
# -*- coding: utf-8 -*-
# =========================================================================
# Reflex 실행 상태 확인 스크립트
# 기본 운영 기준: agriAiCore.service (single-port: 3000)
# =========================================================================

set -e

echo "=========================================="
echo "  Reflex 실행 상태 확인"
echo "=========================================="
echo ""

echo "[1] 서비스 상태:"
systemctl status agriAiCore --no-pager | head -20 || true
echo ""
systemctl status reflex --no-pager | head -12 || true
echo ""

echo "[2] Reflex 프로세스:"
ps aux | grep -E "(reflex run|gunicorn.*main.main:app)" | grep -v grep || echo "  - Reflex 프로세스 없음"
echo ""

echo "[3] 포트 사용 상태:"
echo "  - Port 3000 (Reflex Frontend/API):"
ss -tuln | grep ":3000" || echo "    포트 열려있지 않음"
echo "  - Port 8001 (Reflex Backend, dev 모드에서만 사용):"
ss -tuln | grep ":8001" || echo "    포트 열려있지 않음"
echo ""

echo "[4] PID 파일:"
for pid_file in /tmp/reflex.pid /tmp/scheduler.pid; do
    if [ -f "$pid_file" ]; then
        pid="$(cat "$pid_file")"
        echo "  - $(basename "$pid_file" .pid) PID: $pid"
        if kill -0 "$pid" 2>/dev/null; then
            echo "    ✓ 프로세스 실행 중"
        else
            echo "    ✗ PID 파일만 존재"
        fi
    else
        echo "  - $(basename "$pid_file" .pid) PID 파일 없음"
    fi
done
echo ""

echo "[5] Reflex 로그 (최근 20줄):"
if [ -f "/workspace/jayeondeule/logs/reflex.log" ]; then
    tail -20 /workspace/jayeondeule/logs/reflex.log
else
    echo "  - 로그 파일 없음"
fi
echo ""

echo "[6] HTTP 응답 테스트:"
echo "  - Frontend/API (3000):"
curl -I http://127.0.0.1:3000/ 2>/dev/null | head -5 || echo "    연결 실패"
echo "  - Backend (8001, dev 모드 전용):"
curl -I http://127.0.0.1:8001/ 2>/dev/null | head -5 || echo "    연결 실패"
echo ""

echo "=========================================="
echo "  확인 완료"
echo "=========================================="
