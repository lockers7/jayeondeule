# ══════════════════════════════════════════════════════════════════════
# 1단계 질문유형분석: LLM 기반 질문 분석 및 데이터 수집 계획 생성.
# --->
# fast_classify: 극히 명확한 인사/잡담만 규칙으로 분류
# _parse_analysis_json: LLM 응답에서 JSON을 안전하게 추출
# _validate_analysis: 분석 결과 유효성 검증
# _build_safe_fallback: LLM 분석이 완전히 실패한 경우의 안전한 기본 계획
# analyze_question: 1단계: 질문유형분석
# ══════════════════════════════════════════════════════════════════════
import json
import os
import re
import time
import traceback
from datetime import datetime

from agri_ai_core.src.utils.json_utils import safe_json_load

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.pipeline.prompts import ANALYZER_SYSTEM_PROMPT, get_analyzer_system_prompt

logger = setup_logger(__name__)

# ANALYZER LLM 파라미터 — env 로 조정 가능.
#   num_ctx: 시스템 프롬프트(도구 51개 ≈ 8.4k 토큰) + 질문 + 교훈 + 대화맥락을
#            모두 담아야 한다. 부족하면 앞부분이 잘려 JSON 지시를 잃는다.
_ANALYZER_NUM_CTX = int(os.getenv("ANALYZER_NUM_CTX", "16384"))
_ANALYZER_TIMEOUT_SEC = int(os.getenv("ANALYZER_TIMEOUT_SEC", "120"))

# ══════════════════════════════════════════
# 극히 명확한 패턴만 규칙 분류 (인사/잡담만)
# ⛔ 단독 확인응답(네/예/아니요/어/응/오케이/ok)을 여기 추가하지 말 것 —
#    "확인해 드릴까요?" → "네" 같은 업무 대화의 응답이 greeting 으로 낚여
#    LLM·MCP·직전 맥락을 전부 우회했다(2026-07-17 제거). 절대 룰
#    "LLM 대화 키워드 응답 금지 — 명확한 일상 인사만 예외" 위반.
# 일상 인사 변형 ("안녕하세요", "안녕 (1)" 등)도 LLM 호출 없이 즉시 분류해
# question_analyzer LLM 호출(2300토큰 prompt_eval ≈ 36s) 회피.
# 끝부분에 한글 허용 안 함 → "안녕하세요. 1호 온도 알려줘" 같은 복합 질의는
# 매치되지 않아 LLM 분석으로 정상 진입.
# ══════════════════════════════════════════
_GREETING_RE = re.compile(
    r'^[\s]*'
    r'(안녕(하세요|하십니까|히\s*가세요|히\s*계세요)?|'
    r'오랜만(이다|이야|이에요|이네요|입니다|이군요)?|'
    r'반가(워|워요|웠어요)?|반갑(다|네요|습니다|군요)?|'
    r'감사(합니다|해요|드립니다)?|'
    r'고마(워|워요|와요|웠어)?|'
    r'수고(하세요|많으셨|많으세요)?|'
    r'잘\s*(자|자요|있어|있어요|가|가요|지내|지내요)|'
    r'좋은\s*(아침|하루|저녁|밤|꿈|주말)|'
    r'굿\s*(모닝|나잇|애프터눈|이브닝)|'
    r'hi|hello|hey|bye|'
    r'ㅎㅎ+|ㅋㅋ+|ㅠㅠ+|ㅜㅜ+)'
    r'[\s!~.,?ㅎㅋ\-()0-9]*$',
    re.IGNORECASE
)


# 확실-잡담 고속 판정
# 업무 요소가 전혀 없고(차단어 0) + 잡담 표지가 있는 짧은 발화만 casual_chat 으로
# LLM 분석 없이 즉시 분류 — 조금이라도 애매하면 None(LLM 분석)으로 보수 처리.
# 절대 룰("명확한 일상 인사만 키워드 우회 허용")의 허용 범위 내에서만 동작.
_CASUAL_BLOCK_RE = re.compile(
    r'(재배사|농장|하우스|호기|\d\s*호|온도|습도|수온|씨오|co2|릴레이|밸브|팬|히터|포그|배수|'
    r'조명|관수|제어|센서|알림|모니터|감시|구독|스케줄|임계|프롬프트|테이블|디비|\bdb\b|서버|'
    r'시스템|쇼핑|주문|버섯|배지|수확|살균|카카오|날씨|기상|예보|설정|조회|바꿔|켜\s*줘|꺼\s*줘|'
    r'올려|내려|등록|해제|삭제|취소|분석|진단|보고|알려|확인|검색|찾아|저장|학습)',
    re.IGNORECASE)
_CASUAL_MARK_RE = re.compile(
    r'(안녕|반가|고마|잘\s*지내|심심|재밌|재미|웃긴|얘기|이야기|수다|농담|기분|피곤|졸려|'
    r'배고|밥\s*먹|먹었|가는\s*중|가고\s*있|버스|기차|지하철|운전|퇴근|출근|주말|휴가|여행|'
    r'하이|헬로|좋은\s*(아침|하루|저녁|밤)|ㅎㅎ|ㅋㅋ)',
    re.IGNORECASE)


# ────────────────────────────────────────────────────────────────────
# 극히 명확한 인사/잡담만 규칙으로 분류. 그 외는 None → LLM 분석.
# ────────────────────────────────────────────────────────────────────
def fast_classify(query):
    if not query or not query.strip():
        return "greeting"

    stripped = query.strip()
    oneline = " ".join(l.strip() for l in stripped.split('\n') if l.strip())

    # 다중 줄: 각 줄이 모두 인사 패턴이면 greeting (예: "안녕...\n오랜만이다.")
    if '\n' in stripped:
        lines = [l.strip() for l in stripped.split('\n') if l.strip()]
        if lines and all(len(l) < 30 and _GREETING_RE.match(l) for l in lines):
            return "greeting"
    # 짧은 인사만 (30자 미만 + 인사 패턴). 끝부분에 한글 본문이 붙으면 매치 실패.
    elif len(stripped) < 30 and _GREETING_RE.match(stripped):
        return "greeting"

    # 확실-잡담: 100자 이내 + 잡담 표지 존재 + 업무 차단어/두 자리 숫자 전무
    if (len(oneline) <= 100
            and _CASUAL_MARK_RE.search(oneline)
            and not _CASUAL_BLOCK_RE.search(oneline)
            and not re.search(r'\d{2,}', oneline)):
        return "casual_chat"

    return None  # LLM 분석 필요


# ══════════════════════
# LLM 응답에서 JSON 추출
# ══════════════════════
# ────────────────────────────────────────────────────────────────────
# LLM 응답에서 JSON을 안전하게 추출.
# 마크다운 코드블록, 앞뒤 텍스트 등을 처리.
# ────────────────────────────────────────────────────────────────────
def _parse_analysis_json(response_text):
    if not response_text:
        return None

    text = response_text.strip()

    # 마크다운 코드블록 제거
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_block:
        text = code_block.group(1).strip()

    # JSON 객체 추출 (첫 번째 { ... } 블록)
    brace_start = text.find('{')
    if brace_start == -1:
        return None

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                json_str = text[brace_start:i + 1]
                result = safe_json_load(json_str)
                if result is None:
                    logger.warning(f"[1단계] JSON 파싱 실패: {json_str[:200]}")
                return result
    return None


# ═════════════════════
# 분석 결과 유효성 검증
# ═════════════════════
_VALID_TYPES = {
    "farm_sensor", "farm_control", "farm_knowledge", "farm_knowledge_delete",
    "weather", "web_search", "greeting", "casual_chat", "conversation_ref",
    "general", "complex",
    # Agent 모니터링 — list/cancel/schedule_monitor 조회·취소·등록 질의 전용 유형
    "agent_monitor",
}
_VALID_TOOLS = {
    "search_web", "fetch_url_content", "get_farm_realtime_data",
    "search_farm_knowledge", "control_relay", "delete_farm_knowledge",
    # 관리 도구
    "set_house_control_mode", "set_growth_stage", "set_circulation_mode",
    "set_schedule", "override_ai_thresholds", "get_system_status",
    "get_camera_view",
    # Agent 모니터링 도구
    "schedule_monitor", "list_monitors", "cancel_monitor",
    # Agent 즉시 1회 분석
    "agent_one_shot",
    # 반복 Agent 구독 + 알림 조회
    "agent_subscribe", "list_agent_subscriptions",
    "cancel_agent_subscription", "get_pending_alerts", "set_alert_interval",
    "set_alert_level",
    # 운영 로그 자율 조회·분석 (읽기 전용)
    "search_logs", "list_log_files",
    # MCP 게이트웨이 — 등록된 모든 MCP 서버/도구 직접 호출
    "mcp_call", "mcp_list_tools",
    # MCP 서버 자체 등록부 — 요청받은 MCP 서버를 스스로 추가/제거
    "manage_mcp_server",
    # 원격 서버 조사 — SSH 키 인증으로 원격 서버 상태·명령(조회 자유·변경성 승인)
    "remote_status", "remote_run", "manage_remote_host", "approve_remote_command",
    "compare_remote_sources",
    # 스크립트 자율 작성·실행 (scripts/llm/ 한정)
    "write_script", "run_script", "list_scripts", "read_script",
    # 서비스 관리 (restart/status 한정 — stop 미구현)
    "restart_service", "service_status", "list_services",
    # 서버 리소스 실측 (CPU/메모리/디스크/GPU) — search_web 오라우팅 방지
    "get_server_resources",
    # 운영 소스 자율 변경 (자동 원복 · 안전장치 deny-list)
    "edit_source", "revert_source", "list_source_edits",
    # 사용자 채팅 → 도메인 RAG 영속 저장 도구
    "save_domain_knowledge",
    # 관리자지시·DB자율조회·프롬프트 자가관리
    "set_admin_directive", "release_admin_directive",
    "db_list_tables", "db_describe_table", "db_read_query",
    "manage_control_prompt",
    # 농장 날씨 + 범용 외부 API
    "get_weather_forecast", "call_external_api", "manage_external_api",
    # 소스코드 자율 분석 (읽기 전용)
    "source_list", "source_search", "source_read",
    # DB 데이터 쓰기 (관리자 전용, UPDATE/INSERT)
    "db_write_query",
    # 분석 자가학습 — 질문 처리 교훈 등록/조회/삭제
    "manage_analysis_lesson",
    # 시스템 자기지식 자가학습 — 서버 구조/도구 사실 등록/조회/삭제
    "manage_system_knowledge",
    "set_trading_strategy",
}


# ────────────────────────────────────────────────────────────────────
# 분석 결과 유효성 검증 — 부분 필터링.
# 모르는 도구 항목만 제거하고 나머지 LLM 계획은 살린다. 전체 폐기하면
# 도구명 하나만 환각해도 정상 계획까지 버려지고 키워드 fallback 으로 강등돼
# "LLM 대화 키워드 응답 금지" 절대 룰을 어기게 된다(2026-07-17 변경).
# 살릴 항목이 하나도 없을 때만 False → fallback.
# analysis 는 in-place 로 정리된다.
# ────────────────────────────────────────────────────────────────────
def _validate_analysis(analysis):
    if not isinstance(analysis, dict):
        return False

    qtype = analysis.get("question_type")
    if qtype not in _VALID_TYPES:
        logger.warning(f"[1단계] 알 수 없는 질문유형: {qtype}")
        return False

    required_data = analysis.get("required_data")
    if not isinstance(required_data, list):
        return False

    kept, dropped = [], []
    for item in required_data:
        if not isinstance(item, dict):
            dropped.append(repr(item)[:40])
            continue
        tool = item.get("tool")
        if tool and tool not in _VALID_TOOLS:
            dropped.append(str(tool))
            continue
        kept.append(item)

    if dropped:
        logger.warning(f"[1단계] 알 수 없는 도구 {dropped} 제외 — "
                       f"나머지 {len(kept)}개 계획 유지")

    # 원래 도구가 있었는데 전부 걸러졌으면 LLM 계획이 통째로 무의미 → fallback
    if required_data and not kept:
        return False

    analysis["required_data"] = kept
    return True


# ══════════════════════════════════
# LLM 분석 실패 시 최소한의 fallback
# ══════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# fallback 키워드 패턴 — Ollama 503 등 LLM 분류 실패 시 합리적 분기
# 농장 키워드 매칭 시 farm_sensor / agent_monitor 로 분기하고,
# 등록/조회/취소 의도를 세분화한다.
# ────────────────────────────────────────────────────────────────────
_MONITOR_TIME_RE = re.compile(
    # 모니터링 키워드 ↔ 시간/주기 키워드 양방향 매칭.
    # "10분단위로 ... 센서값, 판단 근거, 릴레이 제어값 ... 보고"처럼
    # 사이에 설명이 긴 운영 지시도 놓치지 않도록 120자까지 허용한다.
    # "모[니티]터링" 으로 오타 "모티터링" 도 매칭
    r'(감시|지켜|모[니티]터링|관찰|보고|분석|진단).{0,120}(시간|분|초|단위|마다|주기|동안|밤|하루|이번주)|'
    r'(시간|분|초|단위|마다|주기|동안|밤|하루|이번주|\d+\s*(시간|분|초)|매\s*시|매\s*분).{0,120}(감시|지켜|모[니티]터링|관찰|보고|분석|진단|판단\s*근거|릴레이\s*제어값)',
    re.IGNORECASE
)
# 긴 문장 fallback 보조: 시간 주기와 보고/분석 의도가 문장 어디든 함께 있으면 반복 Agent 등록으로 본다.
_INTERVAL_ANY_RE = re.compile(r'(\d+\s*(분|시간|초)\s*(단위|마다|주기)?|매\s*(분|시간|시))', re.IGNORECASE)
_MONITOR_REPORT_ANY_RE = re.compile(
    r'(감시|지켜|모[니티]터링|관찰|보고|분석|진단|판단\s*근거|릴레이\s*제어값)',
    re.IGNORECASE,
)
# 구독 조회 — "내가 등록한", "구독", "목록", "뭐 있어"
_SUB_LIST_RE = re.compile(
    r'(등록|구독|예약).{0,15}(모[니티]터링|감시|있|뭐|목록|조회)|'
    r'(모[니티]터링|감시|구독).{0,15}(목록|있어|있나|뭐|어떤|조회|보여)',
    re.IGNORECASE
)
# 구독 취소 — "취소", "해제", "중지" + id 또는 모니터링
_SUB_CANCEL_RE = re.compile(
    r'(취소|해제|중지|중단|끊).{0,10}(모[니티]터링|감시|구독|id\s*\d+|\d+\s*번)|'
    r'(모[니티]터링|감시|구독|id\s*\d+).{0,10}(취소|해제|중지|중단|끊)',
    re.IGNORECASE
)
# 알림 조회 — "알림 있어", "알림 뭐"
_ALERT_QUERY_RE = re.compile(
    r'(알림|소식|결과|보고).{0,10}(있|뭐|어떤|받았|왔어|확인|보여)',
    re.IGNORECASE
)
_FARM_SENSOR_RE = re.compile(
    r'(릴레이|센서값?|재배사|호기|호\s*재배사|\d+호\s*재배|'
    r'내부온도|외부온도|수온|발이?기온도|습도|CO2|이산화탄소|이슬점|VPD)',
    re.IGNORECASE
)
_FARM_CONTROL_RE = re.compile(
    r'(켜|꺼|on|off|작동|가동|중지|중단|돌려|멈춰).{0,5}'
    r'(팬|밸브|히터|조명|관수|배수|포그|fog|램프)|'
    r'(팬|밸브|히터|조명|관수|배수|포그|fog|램프).{0,5}'
    r'(켜|꺼|on|off|작동|가동|중지|중단|돌려|멈춰)',
    re.IGNORECASE
)
# Ollama 503 fallback 전용 인사 감지 — fast_classify 미매칭 + LLM 실패 케이스 구제
_GREETING_FALLBACK_RE = re.compile(
    r'(안녕|오랜만|반가|감사|고마|수고|잘\s*자|잘\s*지내|'
    r'좋은\s*(아침|하루|저녁|밤)|hi\b|hello\b|hey\b|bye\b)',
    re.IGNORECASE
)


def _build_safe_fallback(query, farm_id, house_id):
    """Ollama 503 등 LLM 분석 실패 시 키워드 기반 합리적 fallback.

    분기 우선순위:
    1. 모니터링 + 시간 키워드 → agent_monitor (list_monitors)
    2. 농장 센서/제어 키워드 → farm_sensor (get_farm_realtime_data)
    3. 그 외 → web_search (기존)
    """
    now = datetime.now()
    q = (query or "").strip()

    # 1-a) 구독 취소 → cancel_agent_subscription (id 명시되어야 의미. 없으면 list 부터)
    if q and _SUB_CANCEL_RE.search(q):
        # id N 형태 추출
        import re as _re
        m_id = _re.search(r'(?:id\s*|구독\s*|모[니티]터링\s*)(\d+)', q, _re.IGNORECASE)
        if m_id:
            return {
                "question_type": "agent_monitor",
                "intent": q[:100],
                "required_data": [
                    {"tool": "cancel_agent_subscription",
                     "args": {"subscription_id": int(m_id.group(1))},
                     "priority": 1,
                     "reason": "LLM 503 fallback — 취소 키워드 + id 추출"},
                ],
                "data_freshness": "any",
                "answer_format": "text",
                "multi_house": False, "house_ids": [],
            }
        # id 없으면 목록부터 보여줘서 사용자 지목 유도
        return {
            "question_type": "agent_monitor",
            "intent": q[:100],
            "required_data": [
                {"tool": "list_agent_subscriptions", "args": {},
                 "priority": 1, "reason": "LLM 503 fallback — 취소 의도 but id 미명시"},
            ],
            "data_freshness": "realtime",
            "answer_format": "text",
            "multi_house": False, "house_ids": [],
        }

    # 1-b) 알림 조회 → get_pending_alerts
    if q and _ALERT_QUERY_RE.search(q):
        return {
            "question_type": "agent_monitor",
            "intent": q[:100],
            "required_data": [
                {"tool": "get_pending_alerts",
                 "args": {"limit": 10, "mark_read": True},
                 "priority": 1, "reason": "LLM 503 fallback — 알림 조회 키워드"},
            ],
            "data_freshness": "realtime",
            "answer_format": "text",
            "multi_house": False, "house_ids": [],
        }

    # 1-c) 구독 목록 조회 → list_agent_subscriptions
    if q and _SUB_LIST_RE.search(q):
        return {
            "question_type": "agent_monitor",
            "intent": q[:100],
            "required_data": [
                {"tool": "list_agent_subscriptions", "args": {},
                 "priority": 1, "reason": "LLM 503 fallback — 구독 조회 키워드"},
            ],
            "data_freshness": "realtime",
            "answer_format": "text",
            "multi_house": False, "house_ids": [],
        }

    # 1-d) 등록 — 시간 + 모니터링/보고 키워드 → agent_subscribe (간격 추출)
    if q and (_MONITOR_TIME_RE.search(q) or (_INTERVAL_ANY_RE.search(q) and _MONITOR_REPORT_ANY_RE.search(q))):
        import re as _re
        m_interval = _re.search(r'(\d+)\s*(시간|분)', q)
        interval_min = 60
        if m_interval:
            n = int(m_interval.group(1))
            interval_min = n * 60 if m_interval.group(2) == '시간' else n
            interval_min = max(5, min(interval_min, 1440))
        fid = int(farm_id) if farm_id else 1
        return {
            "question_type": "agent_monitor",
            "intent": q[:100],
            "required_data": [
                {"tool": "agent_subscribe",
                 "args": {"task": q[:200], "interval_min": interval_min, "farm_id": fid},
                 "priority": 1,
                 "reason": "LLM 503 fallback — 모니터링 등록 (시간 키워드 매칭)"},
            ],
            "data_freshness": "realtime",
            "answer_format": "text",
            "multi_house": False, "house_ids": [],
        }

    # 2) 농장 센서/릴레이/제어 키워드 → farm_sensor
    if q and (_FARM_SENSOR_RE.search(q) or _FARM_CONTROL_RE.search(q)):
        fid = str(farm_id) if farm_id else "1"
        hid = str(house_id) if house_id else "all"
        return {
            "question_type": "farm_sensor",
            "intent": q[:100],
            "required_data": [
                {"tool": "get_farm_realtime_data",
                 "args": {"data_type": "all", "farm_id": fid, "house_id": hid},
                 "priority": 1,
                 "reason": "LLM 503 fallback — 농장 키워드 매칭, 실시간 데이터 조회"},
            ],
            "data_freshness": "realtime",
            "answer_format": "text",
            "multi_house": (hid == "all"),
            "house_ids": (["all"] if hid == "all" else []),
        }

    # 3) 인사/잡담 키워드 → greeting (Ollama 다운 중에도 인사가 web_search로 오분류되지 않게)
    if q and _GREETING_FALLBACK_RE.search(q):
        return {
            "question_type": "greeting",
            "intent": q[:100],
            "required_data": [],
            "data_freshness": "any",
            "answer_format": "text",
            "multi_house": False,
            "house_ids": [],
        }

    # 4) 그 외 → 기존 web_search
    return {
        "question_type": "web_search",
        "intent": q[:100] if q else "",
        "required_data": [
            {"tool": "search_web", "args": {"query": f"{q} {now.year}년 {now.month}월"},
             "priority": 1, "reason": "LLM 503 fallback — 일반 검색 (농장·인사 미해당)"},
        ],
        "data_freshness": "recent",
        "answer_format": "text",
        "multi_house": False,
        "house_ids": [],
    }


# ────────────────────────────────────────────────────────────────────
# 대화 컨텍스트에서 직전 사용자 질문 추출 (정정 자가학습용)
# ────────────────────────────────────────────────────────────────────
def _prev_user_question(conversation_context):
    try:
        if isinstance(conversation_context, list):
            for turn in reversed(conversation_context):
                if turn.get("role") == "user" and (turn.get("content") or "").strip():
                    return turn["content"].strip()
    except Exception:
        pass
    return None


# ══════════════════
# 메인: 질문유형분석
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 1단계: 질문유형분석
# 
# 1) 극히 명확한 인사만 규칙 분류 (LLM 절약)
# 2) 그 외 모든 질문 → LLM 호출하여 분석
# 3) LLM 실패 시 안전한 fallback
# 
# Args:
#     user_query: 사용자 질문
#     conversation_context: 직전 대화 컨텍스트
#     farm_id: 농장 ID
#     house_id: 재배사 ID
# 
# Returns:
#     dict: 분석 결과 (question_type, intent, required_data, ...)
# ────────────────────────────────────────────────────────────────────
def analyze_question(user_query, conversation_context=None, farm_id=None, house_id=None):
    t0 = time.time()
    now = datetime.now()
    current_dt = now.strftime("%Y년 %m월 %d일 %A %H시 %M분")

    # Step 1: 인사만 규칙 분류
    fast_result = fast_classify(user_query)
    if fast_result:
        elapsed = (time.time() - t0) * 1000
        logger.info(f"[1단계] 규칙분류={fast_result} ({elapsed:.0f}ms) query=\"{user_query[:60]}\"")
        return {
            "question_type": fast_result,
            "intent": user_query[:100],
            "required_data": [],
            "data_freshness": "any",
            "answer_format": "text",
            "multi_house": False,
            "house_ids": [],
        }

    # [분석 자가학습] 정정 발화 감지 → 직전 질문과 함께 교훈 자동 저장.
    # 농장주가 "그게 아니라/내 질문은/다른 대답" 등으로 직전 답변을 정정하면
    # (원질문 → 정정 의도) 를 교훈으로 축적해 다음 유사 질문에서 재발을 막는다.
    try:
        from agri_ai_core.src.ai import chat_lessons as _lessons
        if _lessons.detect_correction(user_query):
            _prev_q = _prev_user_question(conversation_context)
            if _prev_q:
                _lessons.learn_correction_async(_prev_q, user_query, farm_id)
    except Exception:
        pass

    # Step 2: LLM 호출하여 분석 (핵심)
    try:
        from agri_ai_core.src.ai.llm_client import _ollama_chat, _get_model_name, _extract_message_content

        model_name = _get_model_name()

        # DB 우선 / module 폴백 (placeholder 동적 치환)
        messages = [{"role": "system", "content": get_analyzer_system_prompt()}]

        # [분석 자가학습] 축적 교훈 회상 → 시스템 메시지 주입.
        # 농장주가 가르친 질문 처리 규칙이 코드 변경 없이 즉시 분석에 반영된다.
        try:
            from agri_ai_core.src.ai.chat_lessons import recall_lessons as _recall_lessons
            _lessons_block = _recall_lessons(user_query)
            if _lessons_block:
                messages.append({"role": "system", "content": _lessons_block})
                logger.info(f"[1단계] 분석 교훈 {_lessons_block.count(chr(10)) - 1}건 주입")
        except Exception:
            pass

        # [시스템 자기지식] 서버 구조/테이블/로그/소스/도구 사용법 회상 → 주입.
        # 도구 오라우팅·SQL 컬럼 환각을 근본 차단(대화 모드 전용, 제어 사이클 미개입).
        try:
            from agri_ai_core.src.ai.system_knowledge import recall_system_knowledge as _recall_sys
            _sys_block = _recall_sys(user_query)
            if _sys_block:
                messages.append({"role": "system", "content": _sys_block})
                logger.info(f"[1단계] 시스템지식 {max(0, _sys_block.count(chr(10)) - 2)}건 주입")
        except Exception:
            pass

        # 직전 대화 컨텍스트 — 1단계는 질문유형 분류만 하므로 직전 1턴(user+assistant)만 포함
        # prompt_eval 토큰 최소화로 LLM 응답 속도 향상
        if conversation_context:
            ctx_text = ""
            if isinstance(conversation_context, list):
                for turn in conversation_context[-2:]:  # 최근 1턴(user+assistant 2개 메시지)
                    role = turn.get("role", "")
                    content = turn.get("content", "")[:150]
                    if role in ("user", "assistant"):
                        ctx_text += f"{role}: {content}\n"
            elif isinstance(conversation_context, str):
                ctx_text = conversation_context[:300]

            if ctx_text.strip():
                messages.append({"role": "system", "content": f"[직전 대화 맥락]\n{ctx_text}"})

        user_content = (
            f"현재 시각: {current_dt}\n"
            f"농장ID: {farm_id or '0'} (도구 args의 farm_id에 이 값을 사용하세요. 시스템 농장 '0'은 제어 대상 아님)\n"
            f"재배사ID: {house_id or '0'} (도구 args의 house_id에 이 값을 사용하세요)\n\n"
            f"질문: {user_query}"
        )
        messages.append({"role": "user", "content": user_content})

        t_llm = time.time()
        response = _ollama_chat(
            model=model_name,
            messages=messages,
            tools=None,
            options={
                "temperature": 0.1,
                "num_predict": 1024,
                # ⛔ num_ctx 를 프롬프트보다 작게 두지 말 것 (2026-07-17 실측 사고).
                #   도구가 늘어 시스템 프롬프트가 8,401 토큰이 됐는데 num_ctx 가
                #   8,192 라 앞부분이 잘렸고, LLM 이 JSON 형식 지시를 못 봐서
                #   빈 코드블록(```)만 반환 → 유효성 실패 → 키워드 fallback(web_search)
                #   으로 강등됐다. "서버 리소스" 질문에 웹검색 기사를 답한 사고의 진범.
                #   여기에 질문·교훈·대화맥락이 더해지므로 여유가 필요하다.
                #   gemma3:27b 최대 131,072 · 제어 사이클은 16,384 사용.
                "num_ctx": _ANALYZER_NUM_CTX,
                "think": False,
            },
            keep_alive='1h',
            timeout_sec=_ANALYZER_TIMEOUT_SEC,
        )
        llm_ms = (time.time() - t_llm) * 1000

        response_text = _extract_message_content(response)
        analysis = _parse_analysis_json(response_text)

        if analysis and _validate_analysis(analysis):
            # 필수 필드 기본값 보충
            analysis.setdefault("intent", user_query[:100])
            analysis.setdefault("data_freshness", "any")
            analysis.setdefault("answer_format", "text")
            analysis.setdefault("multi_house", False)
            analysis.setdefault("house_ids", [])
            analysis.setdefault("required_data", [])

            total_ms = (time.time() - t0) * 1000
            logger.info(
                f"[1단계] LLM분석={analysis['question_type']} "
                f"도구={len(analysis['required_data'])}개 "
                f"(LLM={llm_ms:.0f}ms, 전체={total_ms:.0f}ms) "
                f"query=\"{user_query[:60]}\""
            )
            return analysis
        else:
            logger.warning(f"[1단계] LLM 분석 결과 유효성 실패, fallback 사용. response={response_text[:300]}")

    except Exception as e:
        logger.error(f"[1단계] LLM 분석 예외, fallback 사용: {e}")
        logger.error(traceback.format_exc())

    # Step 3: LLM 실패 시 안전한 fallback (키워드 기반 분기)
    plan = _build_safe_fallback(user_query, farm_id, house_id)
    total_ms = (time.time() - t0) * 1000
    logger.info(
        f"[1단계] fallback={plan['question_type']} 도구={len(plan['required_data'])}개 "
        f"({total_ms:.0f}ms) query=\"{user_query[:60]}\""
    )
    return plan
