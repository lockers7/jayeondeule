# ═════════════════════════════════════════════════════════════════════════════════════
# 2단계 데이터 검증: LLM 기반 수집 데이터 충분성 판단.
# --->
# validate_with_llm: LLM에게 수집된 데이터가 질문에 답하기에 충분한지 판단을 요청합니다
# _parse_validator_json: LLM 응답에서 JSON을 안전하게 추출
# summarize_collected_data: 수집된 데이터를 LLM 검증용 요약 텍스트로 변환합니다
# ═════════════════════════════════════════════════════════════════════════════════════
import json
import re
import time
import traceback

from agri_ai_core.config import NUM_CTX
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.json_utils import safe_json_load

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# LLM에게 수집된 데이터가 질문에 답하기에 충분한지 판단을 요청합니다.
# 
# Args:
#     user_query: 사용자 원본 질문
#     analysis_result: 1단계 분석 결과 (intent, question_type 등)
#     collected_data_summary: 수집된 데이터 요약 텍스트
# 
# Returns:
#     dict: {"sufficient": bool, "reason": str, "supplement": [{"tool":..., "args":...}]}
#           LLM 호출 실패 시 {"sufficient": True} 반환 (안전 fallback)
# ────────────────────────────────────────────────────────────────────
def validate_with_llm(user_query, analysis_result, collected_data_summary):
    t0 = time.time()

    try:
        from agri_ai_core.src.ai.llm_client import _ollama_chat, _get_model_name, _extract_message_content
        from agri_ai_core.src.ai.pipeline.prompts import DATA_VALIDATOR_PROMPT, get_data_validator_prompt

        # USE_DB_PROMPTS=1 시 ChromaDB 우선, 실패 시 inline.
        validator_prompt = get_data_validator_prompt()

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
            {"role": "system", "content": validator_prompt},
            {"role": "user", "content": user_content},
        ]

        response = _ollama_chat(
            model=model_name,
            messages=messages,
            tools=None,
            options={
                "temperature": 0.1,
                "num_predict": 512,
                # ⛔ 다른 gemma3:27b 소비자와 동일(16384). 값이 다르면 90초 모델 리로드
                #   (27b 가 16GB VRAM 에 겨우 들어가 리로드가 느림, 2026-07-19 실측).
                "num_ctx": NUM_CTX,
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


# ────────────────────────────────────────────────────────────────────
# LLM 응답에서 JSON을 안전하게 추출
# ────────────────────────────────────────────────────────────────────
def _parse_validator_json(response_text):
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
                return safe_json_load(text[brace_start:i + 1])
    return None


# ────────────────────────────────────────────────────────────────────
# 수집된 데이터를 LLM 검증용 요약 텍스트로 변환합니다.
# 전체 데이터를 보내면 토큰이 낭비되므로, 각 도구 결과의 앞부분만 요약.
# ────────────────────────────────────────────────────────────────────
def summarize_collected_data(collected_data_list):
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
