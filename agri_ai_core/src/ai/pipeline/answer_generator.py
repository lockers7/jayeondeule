# ════════════════════════════════════════════════════════════
# 3단계 답변 작성: 수집된 데이터 기반 LLM 답변 생성 및 출처 선별.
# ════════════════════════════════════════════════════════════
import re
import time
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import NUM_PREDICT, NUM_CTX
from agri_ai_core.src.ai.pipeline.prompts import build_answer_system_prompt

logger = setup_logger(__name__)


def generate_answer(user_query, analysis_result, collected_result,
                    conversation_history=None, farm_name=None, farm_info=None,
                    speech_style=None, progress_callback=None):
    """
    3단계: 수집된 데이터 기반 정교한 답변 생성

    LLM이 답변 본문 + 사용한 출처 번호(<USED_SOURCES>)를 출력합니다.
    시스템은 출처 번호를 파싱하여 실제 사용된 출처만 반환합니다.
    """
    t0 = time.time()
    question_type = analysis_result.get("question_type", "general")

    # 도구 불필요 유형 → 간단 LLM 응답
    if question_type == "greeting":
        return _generate_simple_response(user_query, conversation_history, farm_name, speech_style, "greeting")
    if question_type == "conversation_ref":
        return _generate_simple_response(user_query, conversation_history, farm_name, speech_style, "conversation_ref")

    # 결과가 명확한 실행형 유형 → 간결 보고 (LLM 토큰 절약)
    _concise_types = ("farm_control", "farm_knowledge_delete")
    is_concise = question_type in _concise_types

    # 수집된 데이터와 출처
    all_sources = collected_result.get("sources", [])
    tools_used = collected_result.get("tools_used", [])

    # 수집 데이터를 번호 매긴 텍스트로 포맷
    data_text = _format_collected_data(collected_result)

    if progress_callback:
        progress_callback("수집된 데이터를 종합하여 답변을 작성하고 있습니다...", "llm_generating")

    try:
        from agri_ai_core.src.ai.llm_client import (
            _ollama_chat, _get_model_name, _extract_message_content,
            _finalize_user_facing_answer, _build_structured_result,
            _determine_response_type, _strip_hallucinated_urls,
            _build_conversation_context,
        )

        model_name = _get_model_name()
        now = datetime.now()
        current_dt = now.strftime("%Y년 %m월 %d일 %A %H시 %M분")

        # 3단계 프롬프트 — 1단계 분석 결과 + 출처 목록 포함
        system_prompt = build_answer_system_prompt(
            farm_name=farm_name,
            farm_info=farm_info,
            speech_style=speech_style or "male",
            analysis_result=analysis_result,
            current_datetime=current_dt,
            source_list=all_sources,  # 번호 매겨진 출처를 LLM에 전달
        )

        # 수집 데이터를 시스템 프롬프트에 포함
        system_prompt += f"\n\n[수집된 데이터]\n{data_text}"

        messages = [{"role": "system", "content": system_prompt}]

        # 대화 컨텍스트 주입
        if conversation_history:
            _build_conversation_context(messages, conversation_history, user_query)

        messages.append({"role": "user", "content": user_query})

        # LLM 호출 (도구 미제공 → 순수 답변만 생성)
        # 실행형 유형(제어/삭제)은 간결 보고로 토큰 절약
        answer_num_predict = 1024 if is_concise else NUM_PREDICT
        answer_num_ctx = 4096 if is_concise else NUM_CTX

        t_llm = time.time()
        response = _ollama_chat(
            model=model_name,
            messages=messages,
            tools=None,
            options={
                "temperature": 0.5,
                "top_p": 0.9,
                "top_k": 40,
                "num_predict": answer_num_predict,
                "num_ctx": answer_num_ctx,
                "think": False,
            },
            keep_alive='1h',
        )
        llm_ms = (time.time() - t_llm) * 1000

        raw_answer = _extract_message_content(response)

        # <USED_SOURCES> 태그에서 사용된 출처 번호 추출
        used_source_indices = _extract_used_sources(raw_answer)

        # 사용된 출처만 필터링
        if used_source_indices is not None:
            # LLM이 명시한 출처만 사용
            filtered_sources = []
            for idx in used_source_indices:
                if 0 <= idx < len(all_sources):
                    filtered_sources.append(all_sources[idx])
            logger.info(f"[3단계] LLM 선별 출처: {used_source_indices} → {len(filtered_sources)}건")
        else:
            # <USED_SOURCES> 태그 없음 → 전체 출처 사용 (fallback)
            filtered_sources = all_sources
            logger.info(f"[3단계] USED_SOURCES 태그 없음, 전체 출처 {len(all_sources)}건 사용")

        # <USED_SOURCES> 태그 제거 + 기존 후처리
        clean_answer = _remove_source_tags(raw_answer)
        finalized = _finalize_user_facing_answer(model_name, user_query, farm_name, clean_answer)

        # URL 검증
        verified_urls = {s.get("url", "") for s in filtered_sources if s.get("url")}
        finalized = _strip_hallucinated_urls(finalized, verified_urls)

        response_type = _determine_response_type(tools_used)

        total_ms = (time.time() - t0) * 1000
        logger.info(
            f"[3단계] 답변 생성 완료: {len(finalized)}자, 출처 {len(filtered_sources)}건 "
            f"(LLM={llm_ms:.0f}ms, 전체={total_ms:.0f}ms) type={response_type}"
        )

        return _build_structured_result(finalized, filtered_sources, tools_used)

    except Exception as e:
        logger.error(f"[3단계] 답변 생성 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "response": "죄송합니다. 답변 생성 중 오류가 발생했습니다. 다시 시도해 주세요.",
            "sources": [],
            "tools_used": tools_used if 'tools_used' in dir() else [],
            "response_type": "general",
        }


# ════════════════════════════════════════════════════════════
# LLM 응답에서 <USED_SOURCES> 태그 파싱
# ════════════════════════════════════════════════════════════
def _extract_used_sources(raw_answer):
    """
    LLM 응답에서 <USED_SOURCES>1,3,5</USED_SOURCES> 태그를 파싱합니다.

    Returns:
        list[int] or None: 0-based 인덱스 리스트, 태그 없으면 None
    """
    if not raw_answer:
        return None

    match = re.search(r'<USED_SOURCES>(.*?)</USED_SOURCES>', raw_answer, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    content = match.group(1).strip()
    if not content:
        return []  # 빈 태그 = 출처 미사용

    indices = []
    for part in content.split(","):
        part = part.strip()
        if part.isdigit():
            indices.append(int(part) - 1)  # 1-based → 0-based 변환

    return indices


def _remove_source_tags(text):
    """응답에서 <USED_SOURCES> 태그와 내용을 제거"""
    if not text:
        return text
    return re.sub(r'\s*<USED_SOURCES>.*?</USED_SOURCES>\s*', '', text, flags=re.IGNORECASE | re.DOTALL).strip()


# ════════════════════════════════════════════════════════════
# 수집 데이터 포맷
# ════════════════════════════════════════════════════════════
def _format_collected_data(collected_result):
    if not collected_result:
        return "(수집된 데이터 없음)"

    data_list = collected_result.get("data", [])
    if not data_list:
        return "(수집된 데이터 없음)"

    parts = []
    for i, item in enumerate(data_list, 1):
        tool = item.get("tool", "unknown")
        result = item.get("result", "")

        tool_display = {
            "search_web": "웹 검색 결과",
            "fetch_url_content": "웹 페이지 본문",
            "get_farm_realtime_data": "센서/릴레이 실시간 데이터",
            "search_farm_knowledge": "농장 지식 검색 결과",
            "control_relay": "릴레이 제어 결과",
            "delete_farm_knowledge": "학습 데이터 삭제 결과",
            "search_gas_price": "주유소 가격 정보",
        }.get(tool, tool)

        parts.append(f"--- [{i}] {tool_display} ---\n{result}")

    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════
# 인사/대화참조 등 단순 응답
# ════════════════════════════════════════════════════════════
def _generate_simple_response(user_query, conversation_history, farm_name, speech_style, response_type):
    try:
        from agri_ai_core.src.ai.llm_client import (
            _ollama_chat, _get_model_name, _extract_message_content,
            _finalize_user_facing_answer, _build_structured_result,
            _build_conversation_context,
        )

        model_name = _get_model_name()

        if speech_style == "female":
            tone = "부드러운 해요체(~예요, ~네요, ~해요)로 따뜻하게 응대하세요. 물결(~)을 자연스럽게 사용하세요."
        else:
            tone = "존댓말(~합니다, ~입니다)로 친절하게 응대하세요."

        if response_type == "conversation_ref":
            task = "사용자가 이전 대화 내용을 물어보고 있습니다. [직전 대화 맥락]을 참고하여 답변하세요."
            num_predict = NUM_PREDICT
        else:
            task = "인사나 일상 대화에 짧고 따뜻하게 응답하세요."
            num_predict = 256

        system_prompt = (
            f"당신은 {farm_name + ' 농장의 ' if farm_name else ''}AI 도우미입니다.\n"
            f"{tone}\n{task}\n"
            "내부 추론/think 태그 사용 금지. 순수 답변만 출력.\n/no_think"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            _build_conversation_context(messages, conversation_history, user_query)
        messages.append({"role": "user", "content": user_query})

        response = _ollama_chat(
            model=model_name, messages=messages, tools=None,
            options={"temperature": 0.7, "num_predict": num_predict, "num_ctx": 4096, "think": False},
            keep_alive='1h',
        )

        raw = _extract_message_content(response)
        finalized = _finalize_user_facing_answer(model_name, user_query, farm_name, raw)
        return _build_structured_result(finalized, [], [])

    except Exception as e:
        logger.error(f"[3단계] 단순 응답 오류: {e}")
        fallback = "안녕하세요!" if response_type == "greeting" else "이전 대화 내용을 확인하지 못했습니다."
        return {"response": fallback, "sources": [], "tools_used": [], "response_type": "general"}
