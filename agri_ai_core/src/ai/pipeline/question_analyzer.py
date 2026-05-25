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
import re
import time
import traceback
from datetime import datetime

from agri_ai_core.src.utils.json_utils import safe_json_load

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.pipeline.prompts import ANALYZER_SYSTEM_PROMPT, get_analyzer_system_prompt

logger = setup_logger(__name__)

# ══════════════════════════════════════════
# 극히 명확한 패턴만 규칙 분류 (인사/잡담만)
# 일상 인사 변형 ("안녕하세요", "안녕 (1)" 등)도 LLM 호출 없이 즉시 분류해
# question_analyzer LLM 호출(2300토큰 prompt_eval ≈ 36s) 회피.
# 끝부분에 한글 허용 안 함 → "안녕하세요. 1호 온도 알려줘" 같은 복합 질의는
# 매치되지 않아 LLM 분석으로 정상 진입.
# ══════════════════════════════════════════
_GREETING_RE = re.compile(
    r'^[\s]*'
    r'(안녕(하세요|하십니까|히\s*가세요|히\s*계세요)?|'
    r'반갑(다|네요|습니다|군요)?|'
    r'감사(합니다|해요|드립니다)?|'
    r'고마(워|워요|와요|웠어)?|'
    r'수고(하세요|많으셨|많으세요)?|'
    r'잘\s*(자|자요|있어|있어요|가|가요|지내|지내요)|'
    r'좋은\s*(아침|하루|저녁|밤|꿈|주말)|'
    r'굿\s*(모닝|나잇|애프터눈|이브닝)|'
    r'hi|hello|hey|bye|'
    r'네|예|아니요|아뇨|어|응|오케이|ok|'
    r'ㅎㅎ+|ㅋㅋ+|ㅠㅠ+|ㅜㅜ+)'
    r'[\s!~.,?ㅎㅋ\-()0-9]*$',
    re.IGNORECASE
)


# ────────────────────────────────────────────────────────────────────
# 극히 명확한 인사/잡담만 규칙으로 분류. 그 외는 None → LLM 분석.
# ────────────────────────────────────────────────────────────────────
def fast_classify(query):
    if not query or not query.strip():
        return "greeting"

    stripped = query.strip()

    # 짧은 인사만 (30자 미만 + 인사 패턴). 끝부분에 한글 본문이 붙으면 매치 실패.
    if len(stripped) < 30 and _GREETING_RE.match(stripped):
        return "greeting"

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
    "weather", "web_search", "gas_price", "greeting", "conversation_ref",
    "general", "complex",
    # [Phase 4 Agent 모니터링] list/cancel/schedule_monitor 조회·취소·등록 질의 전용 유형
    "agent_monitor",
}
_VALID_TOOLS = {
    "search_web", "fetch_url_content", "get_farm_realtime_data",
    "search_farm_knowledge", "control_relay", "delete_farm_knowledge", "search_gas_price",
    # [Phase 1] 관리 도구
    "set_house_control_mode", "set_growth_stage", "set_circulation_mode",
    "set_schedule", "override_ai_thresholds", "get_system_status",
    # [Phase 4] Agent 모니터링 도구
    "schedule_monitor", "list_monitors", "cancel_monitor",
    # [2026-05-01] 사용자 채팅 → 도메인 RAG 영속 저장 도구
    "save_domain_knowledge",
}


# ────────────────────────────────────────────────────────────────────
# 분석 결과 유효성 검증. 필수 필드와 도구명 확인.
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

    for item in required_data:
        if not isinstance(item, dict):
            return False
        tool = item.get("tool")
        if tool and tool not in _VALID_TOOLS:
            logger.warning(f"[1단계] 알 수 없는 도구명: {tool}")
            return False

    return True


# ══════════════════════════════════
# LLM 분석 실패 시 최소한의 fallback
# ══════════════════════════════════
def _build_safe_fallback(query, farm_id, house_id):
    now = datetime.now()
    return {
        "question_type": "web_search",
        "intent": query[:100] if query else "",
        "required_data": [
            {"tool": "search_web", "args": {"query": f"{query} {now.year}년 {now.month}월"}, "priority": 1, "reason": "일반 검색"},
        ],
        "data_freshness": "recent",
        "answer_format": "text",
        "multi_house": False,
        "house_ids": [],
    }


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

    # Step 2: LLM 호출하여 분석 (핵심)
    try:
        from agri_ai_core.src.ai.llm_client import _ollama_chat, _get_model_name, _extract_message_content

        model_name = _get_model_name()

        # [프롬프트 자동화 · Phase 3-(6)-4] DB 우선 / module 폴백 (placeholder 동적 치환)
        messages = [{"role": "system", "content": get_analyzer_system_prompt()}]

        # 직전 대화 컨텍스트 — 1단계는 질문유형 분류만 하므로 직전 1턴(user+assistant)만 포함
        # prompt_eval 토큰 최소화로 LLM 응답 속도 향상
        if conversation_context:
            ctx_text = ""
            if isinstance(conversation_context, list):
                for turn in conversation_context[-2:]:  # 4턴 → 최근 1턴(2개 메시지)
                    role = turn.get("role", "")
                    content = turn.get("content", "")[:150]  # 200자 → 150자
                    if role in ("user", "assistant"):
                        ctx_text += f"{role}: {content}\n"
            elif isinstance(conversation_context, str):
                ctx_text = conversation_context[:300]  # 400자 → 300자

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
                "num_ctx": 4096,
                "think": False,
            },
            keep_alive='1h',
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

    # Step 3: LLM 실패 시 안전한 fallback
    plan = _build_safe_fallback(user_query, farm_id, house_id)
    total_ms = (time.time() - t0) * 1000
    logger.info(f"[1단계] fallback=web_search ({total_ms:.0f}ms) query=\"{user_query[:60]}\"")
    return plan
