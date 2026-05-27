#!/bin/bash
# =========================================================================
# ollama_watchdog.sh — Ollama runner hang 감지 + 자동 재시작
#
# 배경 (2026-06-06):
#   Ollama 프로세스는 살아있지만 runner 가 hang 상태가 되면 systemd Restart=always
#   로도 자동 복구 불가. 모든 LLM 요청이 즉시 503 으로 거부됨.
#   6/6 00:00~15:18 사이 791건 503 발생 후 운영자 수동 재시작으로 복구된 사례 있음.
#
# 동작:
#   1) /api/tags 짧은 timeout 호출 — 빠른 살아있음 확인
#   2) LLM busy marker 가 살아 있으면 /api/generate deep-check 스킵
#      (정상 추론 중인 runner 를 watchdog 이 재시작하지 않도록 보호)
#   3) idle 상태에서만 /api/generate 짧은 프롬프트로 runner 응답 가능 여부 확인
#   4) 연속 N회 (default 3) 실패 시 → systemctl restart ollama
#
# 사용:
#   ./ollama_watchdog.sh           # 1회 점검 후 종료 (cron 권장)
#   ./ollama_watchdog.sh --loop    # 60초 주기 무한 루프 (개발용)
#
# cron 등록 권장 (분당 1회):
#   * * * * * /workspace/jayeondeule/setup/ollama_watchdog.sh \
#       >> /workspace/jayeondeule/logs/ollama_watchdog.log 2>&1
# =========================================================================
set -o pipefail

OLLAMA_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"
MODEL_NAME="${OLLAMA_HEALTH_MODEL:-gemma3:27b}"
STATE_FILE="/workspace/jayeondeule/logs/.ollama_watchdog_fails"
BUSY_FILE="${AGRI_LLM_BUSY_FILE:-/tmp/agri_ai_core_llm_busy}"
LOG_PREFIX="[ollama_watchdog]"
MAX_CONSEC_FAILS="${OLLAMA_WATCHDOG_FAILS:-3}"
PING_TIMEOUT="${OLLAMA_PING_TIMEOUT:-2}"
# 콜드 로드 시 ~8초, 추론 포함 25초 한도. 정상은 1초 이내 응답.
GEN_TIMEOUT="${OLLAMA_GEN_TIMEOUT:-25}"

mkdir -p "$(dirname "$STATE_FILE")"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

read_fails() {
    if [ -f "$STATE_FILE" ]; then cat "$STATE_FILE"; else echo 0; fi
}

write_fails() {
    echo "$1" > "$STATE_FILE"
}

is_llm_busy() {
    [ -f "$BUSY_FILE" ] || return 1

    local busy_pid busy_until busy_label now_ts
    read -r busy_pid busy_until busy_label _ < "$BUSY_FILE" || return 1
    now_ts=$(date +%s)

    if ! echo "$busy_pid" | grep -Eq '^[0-9]+$'; then
        echo "$(ts) $LOG_PREFIX BUSY_MARKER_STALE: invalid pid"
        rm -f "$BUSY_FILE"
        return 1
    fi
    if ! echo "$busy_until" | grep -Eq '^[0-9]+$'; then
        echo "$(ts) $LOG_PREFIX BUSY_MARKER_STALE: invalid expiry"
        rm -f "$BUSY_FILE"
        return 1
    fi
    if [ "$now_ts" -gt "$busy_until" ]; then
        echo "$(ts) $LOG_PREFIX BUSY_MARKER_STALE: expired pid=$busy_pid label=${busy_label:-unknown}"
        rm -f "$BUSY_FILE"
        return 1
    fi
    if kill -0 "$busy_pid" 2>/dev/null; then
        echo "$(ts) $LOG_PREFIX BUSY: active LLM request pid=$busy_pid label=${busy_label:-unknown} → /api/generate deep-check skip"
        return 0
    fi

    echo "$(ts) $LOG_PREFIX BUSY_MARKER_STALE: pid not alive pid=$busy_pid label=${busy_label:-unknown}"
    rm -f "$BUSY_FILE"
    return 1
}

# 단일 점검 — 0=정상, 1=실패
check_once() {
    # 1) /api/tags 빠른 점검
    if ! curl -sS --max-time "$PING_TIMEOUT" \
        "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        echo "$(ts) $LOG_PREFIX FAIL: /api/tags timeout/refused"
        return 1
    fi

    # 2) 정상 LLM 추론 중이면 deep-check 는 건너뛴다.
    if is_llm_busy; then
        return 0
    fi

    # 3) /api/generate 짧은 프롬프트
    local resp
    resp=$(curl -sS --max-time "$GEN_TIMEOUT" \
        -X POST "${OLLAMA_URL}/api/generate" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"${MODEL_NAME}\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":2,\"num_ctx\":16384}}" \
        -w "\n%{http_code}" 2>&1)
    local exit_code=$?
    local status_code
    status_code=$(echo "$resp" | tail -1)

    if [ $exit_code -ne 0 ]; then
        echo "$(ts) $LOG_PREFIX FAIL: /api/generate curl exit=$exit_code"
        return 1
    fi
    if [ "$status_code" != "200" ]; then
        echo "$(ts) $LOG_PREFIX FAIL: /api/generate status=$status_code"
        return 1
    fi
    return 0
}

# 실패 누적 → restart
trigger_restart_if_needed() {
    local fails="$1"
    if [ "$fails" -ge "$MAX_CONSEC_FAILS" ]; then
        echo "$(ts) $LOG_PREFIX TRIGGER: $fails 회 연속 실패 → systemctl restart ollama"
        if systemctl restart ollama 2>&1; then
            echo "$(ts) $LOG_PREFIX RESTART: 성공"
            write_fails 0
        else
            echo "$(ts) $LOG_PREFIX RESTART: 실패 (권한? sudo 필요)"
        fi
        return 0
    fi
    return 1
}

# 1회 점검 후 상태 갱신
run_once() {
    local cur_fails
    cur_fails=$(read_fails)

    if check_once; then
        if [ "$cur_fails" != "0" ]; then
            echo "$(ts) $LOG_PREFIX RECOVER: 이전 누적실패=$cur_fails → 0 으로 리셋"
        fi
        write_fails 0
    else
        cur_fails=$((cur_fails + 1))
        echo "$(ts) $LOG_PREFIX 누적 실패=$cur_fails / 임계=$MAX_CONSEC_FAILS"
        write_fails "$cur_fails"
        trigger_restart_if_needed "$cur_fails"
    fi
}

main() {
    if [ "$1" = "--loop" ]; then
        while true; do
            run_once
            sleep 60
        done
    else
        run_once
    fi
}

main "$@"
