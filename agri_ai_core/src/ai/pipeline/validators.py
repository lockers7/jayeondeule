"""2단계 데이터 검증: LLM 기반 수집 데이터 충분성 판단."""
import json
import re
import time
import traceback

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


def validate_with_llm(user_query, analysis_result, collected_data_summary):
    """
    LLM에게 수집된 데이터가 질문에 답하기에 충분한지 판단을 요청합니다.

    Args:
        user_query: 사용자 원본 질문
        analysis_result: 1단계 분석 결과 (intent, question_type 등)
        collected_data_summary: 수집된 데이터 요약 텍스트

    Returns:
        dict: {"sufficient": bool, "reason": str, "supplement": [{"tool":..., "args":...}]}
              LLM 호출 실패 시 {"sufficient": True} 반환 (안전 fallback)
    """
    t0 = time.time()

    try:
        from agri_ai_core.src.ai.llm_client import _ollama_chat, _get_model_name, _extract_message_content
        from agri_ai_core.src.ai.pipeline.prompts import DATA_VALIDATOR_PROMPT

        model_name = _get_model_name()

        intent = analysis_result.get("intent", "")
        question_type = analysis_result.get("question_type", "")

        user_content = (
            f"[사용자 질문]\n{user_query}\n\n"
            f"[1단계 분석]\n- 핵심 의도: {intent}\n- 질문 유형: {question_type}\n\n"
            f"[수집된 데이터 요약]\n{collected_data_summary}\n\n"
            f"위 데이터가 사용자 질문에 답변하기에 충분한지 판단하세요."
        )

        messages = [
            {"role": "system", "content": DATA_VALIDATOR_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = _ollama_chat(
            model=model_name,
            messages=messages,
            tools=None,
            options={
                "temperature": 0.1,
                "num_predict": 512,
                "num_ctx": 4096,
                "think": False,
            },
            keep_alive='1h',
        )

        llm_ms = (time.time() - t0) * 1000
        response_text = _extract_message_content(response)

        result = _parse_validator_json(response_text)
        if result:
            sufficient = result.get("sufficient", True)
            reason = result.get("reason", "")
            supplements = result.get("supplement", [])

            logger.info(
                f"[2단계검증] LLM판단: sufficient={sufficient} "
                f"reason=\"{reason[:80]}\" 보충={len(supplements)}건 ({llm_ms:.0f}ms)"
            )
            return result
        else:
            logger.warning(f"[2단계검증] LLM 응답 파싱 실패, sufficient=True로 처리. response={response_text[:200]}")
            return {"sufficient": True, "reason": "검증 응답 파싱 실패", "supplement": []}

    except Exception as e:
        logger.error(f"[2단계검증] LLM 검증 오류, sufficient=True로 처리: {e}")
        logger.debug(traceback.format_exc())
        return {"sufficient": True, "reason": f"검증 오류: {e}", "supplement": []}


def _parse_validator_json(response_text):
    """LLM 응답에서 JSON을 안전하게 추출"""
    if not response_text:
        return None

    text = response_text.strip()

    # 마크다운 코드블록 제거
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_block:
        text = code_block.group(1).strip()

    # JSON 객체 추출
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
                try:
                    return json.loads(text[brace_start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def summarize_collected_data(collected_data_list):
    """
    수집된 데이터를 LLM 검증용 요약 텍스트로 변환합니다.
    전체 데이터를 보내면 토큰이 낭비되므로, 각 도구 결과의 앞부분만 요약.
    """
    if not collected_data_list:
        return "(수집된 데이터 없음)"

    parts = []
    for item in collected_data_list:
        tool = item.get("tool", "?")
        result = item.get("result", "")
        # 각 결과의 앞 500자만 요약
        preview = result[:500] if result else "(빈 결과)"
        if len(result) > 500:
            preview += "... (이하 생략)"
        parts.append(f"[{tool}] {preview}")

    return "\n\n".join(parts)
