#!/bin/bash
# Reflex 빠른 상태 확인

# .env에서 공개 호스트/포트 읽기 (없으면 기본값)
ENV_FILE="/workspace/jayeondeule/.env"
PUBLIC_HOST="lockers7.iptime.org"
PUBLIC_PORT="3000"
if [ -f "$ENV_FILE" ]; then
    PUBLIC_HOST="$(grep '^REFLEX_PUBLIC_HOST=' "$ENV_FILE" | tail -1 | cut -d'=' -f2- | tr -d '\"' | tr -d ' ' || echo "$PUBLIC_HOST")"
    PUBLIC_PORT="$(grep '^REFLEX_PUBLIC_PORT=' "$ENV_FILE" | tail -1 | cut -d'=' -f2- | tr -d '\"' | tr -d ' ' || echo "$PUBLIC_PORT")"
fi

REFLEX_PROC_CMD="$(ps aux | grep -E 'reflex run' | grep -v grep || true)"
IS_SINGLE_PORT=false
if echo "$REFLEX_PROC_CMD" | grep -q -- '--single-port'; then
    IS_SINGLE_PORT=true
fi

echo "=== Reflex 상태 확인 ==="
echo ""

echo "[1] 프로세스:"
ps aux | grep -E "(reflex)" | grep -v grep || echo "  없음"
echo ""

echo "[2] 포트:"
if ss -tuln 2>/dev/null | grep -E ":(3000|8001)" >/tmp/quick_check_ports.txt 2>/dev/null; then
    cat /tmp/quick_check_ports.txt
else
    proc_ports="$(awk '
        NR > 1 {
            split($2, addr, ":")
            if ($4 == "0A") {
                port = toupper(addr[2])
                if (port == "0BB8") print "  3000 LISTEN (/proc/net/tcp 기준)"
                if (port == "1F41") print "  8001 LISTEN (/proc/net/tcp 기준)"
            }
        }
    ' /proc/net/tcp /proc/net/tcp6 2>/dev/null)"
    if [ -n "$proc_ports" ]; then
        echo "$proc_ports"
    else
        echo "  열려있지 않음"
    fi
fi
rm -f /tmp/quick_check_ports.txt 2>/dev/null || true
echo ""

echo "[3] 로그 (최근 10줄):"
if [ -f /workspace/jayeondeule/logs/reflex.log ]; then
    tail -10 /workspace/jayeondeule/logs/reflex.log
else
    echo "  로그 없음"
fi
echo ""

echo "[4] HTTP 테스트:"
# localhost(IPv6 우선) 환경 이슈를 피하기 위해 127.0.0.1 우선 사용
frontend_code="$(curl -s -o /dev/null -m 3 -w "%{http_code}" http://127.0.0.1:3000/ || true)"
if [ "$frontend_code" = "000" ]; then
    # Reflex 빌드/기동 지연을 고려해 짧게 재시도
    sleep 2
    frontend_code="$(curl -s -o /dev/null -m 3 -w "%{http_code}" http://127.0.0.1:3000/ || true)"
fi
echo "  Frontend (3000): $frontend_code"
if [ "$frontend_code" = "000" ]; then
    echo "  Frontend: 연결 실패"
fi
if [ "$IS_SINGLE_PORT" = "true" ]; then
    echo "  Backend (8001): N/A (prod single-port 모드)"
else
    backend_code="$(curl -s -o /dev/null -m 3 -w "%{http_code}" http://127.0.0.1:8001/ || true)"
    echo "  Backend (8001): $backend_code"
    if [ "$backend_code" = "000" ]; then
        echo "  Backend: 연결 실패"
    fi
fi
echo ""

echo "[5] 외부 도메인 테스트:"
echo "  Domain: $PUBLIC_HOST:$PUBLIC_PORT"
if getent hosts "$PUBLIC_HOST" >/dev/null 2>&1; then
    echo "  DNS: OK"
else
    echo "  DNS: FAIL (도메인 해석 불가)"
fi
curl -s -o /dev/null -m 5 -w "  Public URL: %{http_code}\n" "http://$PUBLIC_HOST:$PUBLIC_PORT/" || \
    echo "  Public URL: 연결 실패 (포트포워딩/방화벽/NAT loopback 확인 필요)"
