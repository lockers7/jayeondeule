#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# log_view.sh — AI 코어 통합 로그를 4가지 카테고리로 필터링하여 출력
# [2026-04-28 신규]
#
# 카테고리:
#   manual : 수동제어 (UI/API 직접 토글, raw_mode=True 쓰기)
#   algo   : 알고리즘 환경제어 (control_all_manual, [N/M] 패턴, AI 미사용)
#   ai     : 인공지능 환경제어 (14단계 / [AI N/M] / ai_* 모듈)
#   llm    : LLM 대화 (음성/챗봇/툴호출/사용자 RAG — 환경제어 외)
#   all    : 모든 카테고리 + 카테고리 prefix 표시
#
# 사용법:
#   ./setup/log_view.sh ai
#   ./setup/log_view.sh algo -f                     # tail -F 로 실시간
#   ./setup/log_view.sh manual -d 2026-04-27        # 특정 날짜 로그
#   ./setup/log_view.sh ai -n 500                   # 최근 500줄에서만
#   ./setup/log_view.sh llm -F /path/to/custom.log  # 파일 직접 지정
#   ./setup/log_view.sh all -f                      # 4 카테고리 라이브 스트리밍
#
# 패턴 미세조정:
#   아래 PAT_* 변수만 수정하면 분류 기준 변경 가능. (호출 룰: 본 스크립트는
#   읽기 전용 — 코드/설정을 수정하지 않음.)
# ══════════════════════════════════════════════════════════════════════════════
set -u

LOG_DIR="/workspace/jayeondeule/logs"
DEFAULT_LINES=200

# ── 카테고리별 정규식 (egrep) ─────────────────────────────────────────────────
# manual : "수동제어" 키워드 / [수동재배사 N/M] / API 직접 호출 흔적
PAT_MANUAL='\[수동재배사 [0-9]+/[0-9]+\]|수동제어|patchRelayStatus|/api/v1/relay/.*PATCH|raw_mode=True'

# algo   : 알고리즘 모드 — [ALGO N/5] 단계 로그 + [ALGO재배사 N/M] 순회 헤더
#          + 명시적 키워드(알고리즘 수동제어, 환경제어 대상 순서 등)
PAT_ALGO='\[ALGO [0-9]+/[0-9]+\]|\[ALGO재배사 [0-9]+/[0-9]+\]|\[휴지재배사 [0-9]+/[0-9]+\]|\[재배사 [0-9]+/[0-9]+\]|알고리즘 수동제어|환경제어 대상 순서|외부정상\+내부비정상'
PAT_ALGO_EXCLUDE='\[AI |\[LLM |\[AI재배사 |\[AI비상 |\[AI수온비상 |\[수동재배사 '

# ai     : 14단계 / AI 비상 / AI 수온비상 / AI 재배사 순회 / AI 전용 모듈
PAT_AI='\[AI [0-9]+/[0-9]+\]|\[AI재배사 [0-9]+/[0-9]+\]|\[AI비상 [0-9]+/[0-9]+\]|\[AI수온비상 [0-9]+/[0-9]+\]|\[AI순환루프\]|\[AI[가-힣]+\]|agri_ai_core\.src\.control\.ai_(history_context|rag_context|step_logger|algorithm_reference|decision_log|peer_compare|harvest_context|anomaly_history|weather_forecast|camera_vision|doc_rag|yield_correlation|forecast|seasonality|power_usage|feedback|control)'

# llm    : LLM 대화/툴호출/사용자 RAG (환경제어 외) — [LLM N/M] 단계 로그 포함
PAT_LLM='\[LLM [0-9]+/[0-9]+\]|voice_router|conversation_(context|store)|tools_(search|data|control|registration|auth)|src\.ai\.rag\.(chunker|document_processor|document_enricher)|src\.ai\.embedder|query_handler_simple|llm_client|llm_response_processing'

# ── 인자 파싱 ────────────────────────────────────────────────────────────────
usage() {
    sed -n '2,30p' "$0"
    exit 1
}

[ $# -lt 1 ] && usage
case "$1" in -h|--help) usage ;; esac
MODE="$1"; shift

FOLLOW=0
DATE=$(date +%Y-%m-%d)
LINES="$DEFAULT_LINES"
LOGFILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        -f|--follow) FOLLOW=1; shift ;;
        -d|--date)   DATE="$2"; shift 2 ;;
        -n|--lines)  LINES="$2"; shift 2 ;;
        -F|--file)   LOGFILE="$2"; shift 2 ;;
        -h|--help)   usage ;;
        *) echo "[log_view] 알 수 없는 옵션: $1" >&2; usage ;;
    esac
done

[ -z "$LOGFILE" ] && LOGFILE="${LOG_DIR}/ai_${DATE}.log"

if [ ! -r "$LOGFILE" ]; then
    echo "[log_view] 로그 파일 없음 또는 읽을 수 없음: $LOGFILE" >&2
    exit 2
fi

# ── 카테고리별 필터 함수 ──────────────────────────────────────────────────────
filter_manual() { grep --line-buffered -E "$PAT_MANUAL"; }
filter_algo()   { grep --line-buffered -E "$PAT_ALGO" | grep --line-buffered -vE "$PAT_ALGO_EXCLUDE"; }
filter_ai()     { grep --line-buffered -E "$PAT_AI"; }
filter_llm()    { grep --line-buffered -E "$PAT_LLM"; }

# all 모드 — 라인에 카테고리 prefix 를 awk 로 부착.
# [2026-04-28] 단계 prefix([ALGO N/M] / [LLM N/M] / [AI N/M]) 가 같은 ai_step_logger
# 모듈에서 모두 출력되므로, 단계 prefix 매칭을 모듈명 매칭보다 우선하여 정확히 분류.
PAT_STEP_AI='\[AI [0-9]+/[0-9]+\]'
PAT_STEP_ALGO='\[ALGO [0-9]+/[0-9]+\]'
PAT_STEP_LLM='\[LLM [0-9]+/[0-9]+\]'

filter_all() {
    awk -v M="$PAT_MANUAL" -v A="$PAT_ALGO" -v X="$PAT_ALGO_EXCLUDE" \
        -v I="$PAT_AI" -v L="$PAT_LLM" \
        -v SAI="$PAT_STEP_AI" -v SAL="$PAT_STEP_ALGO" -v SLL="$PAT_STEP_LLM" '
    BEGIN { last = "" }
    {
        out=""
        cat=""
        # 1순위: 명시적 단계 prefix (AI/ALGO/LLM) — 가장 정확, 다음 detail 라인은 이걸 이어받음
        if      ($0 ~ SAL) { cat="ALG" }
        else if ($0 ~ SLL) { cat="LLM" }
        else if ($0 ~ SAI) { cat="AI " }
        # 2순위: detail/연속 라인 (└) — 직전 카테고리 유지
        else if ($0 ~ /└ / && last != "") { cat = last }
        # 3순위: 키워드/모듈 패턴
        else if ($0 ~ A && $0 !~ X) { cat="ALG" }
        else if ($0 ~ L)            { cat="LLM" }
        else if ($0 ~ I)            { cat="AI " }
        else if ($0 ~ M)            { cat="MAN" }

        if (cat != "") {
            out = "[" cat "] " $0
            last = cat
            print out
            fflush()
        }
    }'
}

run_filter() {
    case "$1" in
        manual) filter_manual ;;
        algo)   filter_algo ;;
        ai)     filter_ai ;;
        llm)    filter_llm ;;
        all)    filter_all ;;
        *)
            echo "[log_view] 알 수 없는 카테고리: $1" >&2
            echo "사용 가능: manual / algo / ai / llm / all" >&2
            exit 3 ;;
    esac
}

# ── 헤더 출력 ────────────────────────────────────────────────────────────────
{
    echo "════════════════════════════════════════════════════════════════════"
    echo "  log_view.sh  category=$MODE  file=$LOGFILE  follow=$FOLLOW"
    echo "  필터 패턴 (PAT_${MODE^^}) 은 setup/log_view.sh 상단에서 수정 가능"
    echo "════════════════════════════════════════════════════════════════════"
} >&2

# ── 실행 ────────────────────────────────────────────────────────────────────
if [ "$FOLLOW" = "1" ]; then
    # 라이브 스트리밍 — tail -F 로 회전 추종
    tail -n "$LINES" -F "$LOGFILE" | run_filter "$MODE"
else
    tail -n "$LINES" "$LOGFILE" | run_filter "$MODE"
fi
