# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 응답 생성기 모듈
# 수집된 컨텍스트와 LLM 출력을 조합하여 최종 사용자 응답을 생성하며,
# 포맷팅, 검증, 후처리 등을 수행합니다.
# --->
# validate_data_sufficiency: 데이터 충분성 검증 (LLM 2차 호출, 선택적)
# parse_validation_response: 검증 응답 파싱
# generate_final_response: 최종 답변 생성 (LLM 3차 호출)
# generate_direct_response: 직접 응답 (LLM 자체 응답)
# generate_context_based_response: 컨텍스트 기반 응답
# format_context_for_llm: 컨텍스트 포맷팅
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
from typing import Dict, Any

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.ai.llm_client import get_llm_response

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 데이터 충분성 검증 (LLM 2차 호출, 선택적)
# 수집된 데이터가 사용자 질문에 답변하기에 충분한지 LLM으로 검증
#
# Args:
#     user_query: 사용자 질문
#     classification: 질문 분류 결과
#     collected_context: 수집된 컨텍스트 데이터
#
# Returns:
#     dict: 검증 결과
#     {
#         "sufficient": True/False,
#         "missing_data": ["필요한 추가 데이터"],
#         "reasoning": "검증 근거"
#     }
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def validate_data_sufficiency(
    user_query: str,
    classification: Dict[str, Any],
    collected_context: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        # 신뢰도가 높으면 검증 생략
        if classification.get("confidence", 0) >= 0.85:
            return {
                "sufficient": True,
                "missing_data": [],
                "reasoning": "높은 신뢰도로 검증 생략"
            }

        # 수집된 데이터 요약
        collected_summary = collected_context.get("summary", "데이터 없음")

        system_prompt = """당신은 데이터 충분성 검증 전문가입니다.
사용자 질문에 답변하기 위해 수집된 데이터가 충분한지 판단하세요.

**출력 형식 (JSON):**
```json
{
  "sufficient": true/false,
  "missing_data": ["추가로 필요한 데이터1", "데이터2"] or [],
  "reasoning": "판단 근거 1줄"
}
```

**규칙:**
- sufficient=true: 수집된 데이터로 답변 가능
- sufficient=false: 추가 데이터 필요
- missing_data: 구체적으로 무엇이 필요한지 명시

**JSON만 출력하세요.**"""

        user_prompt = f"""질문: {user_query}

수집된 데이터:
{collected_summary}

이 데이터로 질문에 답변할 수 있나요?"""

        llm_response = get_llm_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            top_p=0.8,
            top_k=20,
            num_predict=150,
            query_type="data_validation"
        )

        # JSON 파싱
        validation = parse_validation_response(llm_response)

        logger.info(f"데이터 충분성 검증: {validation['sufficient']} - {validation['reasoning']}")
        return validation

    except Exception as e:
        logger.error(f"데이터 검증 중 오류: {e}")
        # 오류 시 충분하다고 간주 (진행)
        return {
            "sufficient": True,
            "missing_data": [],
            "reasoning": f"검증 실패, 계속 진행: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 검증 응답 파싱
# 검증 응답 파싱
#
# Args:
#     llm_response: LLM 응답
#
# Returns:
#     dict: 파싱된 검증 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def parse_validation_response(llm_response: str) -> Dict[str, Any]:
    import re

    try:
        # JSON 추출
        cleaned = llm_response.strip()
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        elif cleaned.find('{') != -1:
            brace_start = cleaned.find('{')
            brace_end = cleaned.rfind('}')
            cleaned = cleaned[brace_start:brace_end+1]

        parsed = json.loads(cleaned)

        return {
            "sufficient": parsed.get("sufficient", True),
            "missing_data": parsed.get("missing_data", []),
            "reasoning": parsed.get("reasoning", "파싱 성공")
        }

    except Exception as e:
        logger.warning(f"검증 응답 파싱 실패: {e}")
        return {
            "sufficient": True,
            "missing_data": [],
            "reasoning": "파싱 실패, 계속 진행"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최종 답변 생성 (LLM 3차 호출)
# 수집된 컨텍스트를 기반으로 사용자 질문에 대한 최종 답변 생성
#
# Args:
#     user_query: 사용자 질문
#     classification: 질문 분류 결과
#     collected_context: 수집된 컨텍스트 데이터
#     stream: 스트리밍 모드 여부
#
# Returns:
#     str: 최종 답변
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def generate_final_response(
    user_query: str,
    classification: Dict[str, Any],
    collected_context: Dict[str, Any],
    stream: bool = False
) -> str:
    try:
        query_types = classification.get("query_types", [])
        can_answer_directly = classification.get("can_answer_directly", False)

        # LLM 직접 응답 모드
        if can_answer_directly:
            return await generate_direct_response(user_query, stream)

        # 컨텍스트 기반 응답 생성
        return await generate_context_based_response(
            user_query,
            classification,
            collected_context,
            stream
        )

    except Exception as e:
        logger.error(f"최종 답변 생성 중 오류: {e}")
        return f"죄송합니다. 답변 생성 중 오류가 발생했습니다: {str(e)}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 직접 응답 (LLM 자체 응답)
# LLM이 직접 답변 가능한 경우 (추가 데이터 불필요)
#
# Args:
#     user_query: 사용자 질문
#     stream: 스트리밍 모드
#
# Returns:
#     str: 답변
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def generate_direct_response(user_query: str, stream: bool = False) -> str:
    try:
        system_prompt = """당신은 친절하고 전문적인 스마트팜 AI 어시스턴트입니다.

**역할:**
- 사용자의 질문에 명확하고 친절하게 답변
- 농업, 스마트팜, IoT 관련 전문 지식 제공
- 간결하면서도 충분한 정보 제공

**답변 스타일:**
- 존댓말 사용
- 3-5문장으로 간결하게
- 필요시 단계별 설명
- 이모지는 사용하지 않음

**제한사항:**
- 실시간 데이터는 제공할 수 없음을 명확히 알림
- 추측하지 말고 모르면 솔직히 인정
- 농장 데이터가 필요한 경우 사용자에게 안내"""

        user_prompt = user_query

        response = get_llm_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            top_p=0.9,
            top_k=40,
            num_predict=300,  # 500 → 300으로 단축 (간결한 답변)
            query_type="direct_chat"
        )

        logger.info(f"직접 응답 생성 완료: {len(response)}자")
        return response

    except Exception as e:
        logger.error(f"직접 응답 생성 중 오류: {e}")
        return "죄송합니다. 답변을 생성할 수 없습니다."


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컨텍스트 기반 응답
# 수집된 컨텍스트 데이터를 활용한 답변 생성
#
# Args:
#     user_query: 사용자 질문
#     classification: 질문 분류 결과
#     collected_context: 수집된 컨텍스트
#     stream: 스트리밍 모드
#
# Returns:
#     str: 답변
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def generate_context_based_response(
    user_query: str,
    classification: Dict[str, Any],
    collected_context: Dict[str, Any],
    stream: bool = False
) -> str:
    try:
        # 컨텍스트 포맷팅
        context_text = format_context_for_llm(collected_context)

        system_prompt = """당신은 스마트팜 데이터 분석 전문 AI입니다.

**역할:**
- 제공된 농장 데이터, 시스템 정보, 검색 결과를 분석
- 사용자 질문에 데이터 기반으로 정확히 답변
- 데이터에 없는 내용은 추측하지 말 것

**답변 형식:**
1. 핵심 답변 먼저 제시
2. 데이터 근거 제시
3. 필요시 추가 설명이나 권장사항

**답변 스타일:**
- 존댓말 사용
- 구체적인 수치 포함
- 간결하고 명확하게 (5-10문장)
- 이모지 사용 금지

**중요:**
- 제공된 데이터만 사용
- 데이터가 부족하면 명시적으로 언급
- 날짜/시간 정보는 정확히 표시"""

        user_prompt = f"""질문: {user_query}

제공된 데이터:
{context_text}

위 데이터를 참고하여 질문에 답변해주세요."""

        response = get_llm_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            top_p=0.85,
            top_k=30,
            num_predict=400,  # 800 → 400으로 단축 (핵심만)
            query_type="context_based_answer"
        )

        logger.info(f"컨텍스트 기반 응답 생성 완료: {len(response)}자")
        return response

    except Exception as e:
        logger.error(f"컨텍스트 기반 응답 생성 중 오류: {e}")
        return "죄송합니다. 데이터를 분석하여 답변을 생성할 수 없습니다."


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컨텍스트 포맷팅
# 수집된 컨텍스트를 LLM이 이해하기 쉬운 텍스트로 포맷팅
#
# Args:
#     collected_context: 수집된 컨텍스트 데이터
#
# Returns:
#     str: 포맷팅된 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def format_context_for_llm(collected_context: Dict[str, Any]) -> str:
    try:
        collected = collected_context.get("collected", {})
        sections = []

        # 농장 데이터
        if "farm" in collected:
            farm_data = collected["farm"]
            if farm_data.get("sensors"):
                sections.append("=== 농장 센서 데이터 ===")

                latest = farm_data["sensors"].get("latest", {})
                if latest:
                    sections.append(f"현재 상태 (기록시간: {latest.get('기록시간', 'N/A')})")
                    sections.append(f"- 내부온도: {latest.get('내부온도')}°C")
                    sections.append(f"- 내부습도: {latest.get('내부습도')}%")
                    sections.append(f"- CO2: {latest.get('CO2')}ppm")
                    sections.append(f"- 수온: {latest.get('수온')}°C")

                stats = farm_data["sensors"].get("stats", {})
                if stats and stats.get("온도"):
                    sections.append("\n통계 (수집 기간 데이터)")
                    temp_stats = stats["온도"]
                    sections.append(
                        f"- 온도: 평균 {temp_stats['평균']}°C, "
                        f"최고 {temp_stats['최고']}°C, 최저 {temp_stats['최저']}°C"
                    )
                    if stats.get("습도") and stats["습도"]["평균"]:
                        humid_stats = stats["습도"]
                        sections.append(
                            f"- 습도: 평균 {humid_stats['평균']}%, "
                            f"최고 {humid_stats['최고']}%, 최저 {humid_stats['최저']}%"
                        )

            if farm_data.get("relays"):
                sections.append("\n=== 릴레이 상태 ===")
                relay_info = farm_data["relays"]
                sections.append(
                    f"총 {relay_info['count']}개 릴레이 중 {relay_info['on_count']}개 작동 중"
                )
                for relay in relay_info.get("list", [])[:5]:  # 최대 5개만 표시
                    sections.append(f"- {relay['이름']} (#{relay['번호']}): {relay['상태']}")

        # 시스템 정보
        if "system" in collected:
            system_data = collected["system"]
            if system_data.get("datetime"):
                sections.append("\n=== 시스템 정보 ===")
                dt = system_data["datetime"]
                sections.append(f"현재 날짜: {dt.get('현재날짜')} ({dt.get('한글요일')})")
                sections.append(f"현재 시간: {dt.get('현재시간')}")

            if system_data.get("system"):
                sys_info = system_data["system"]
                sections.append(
                    f"시스템 상태: CPU {sys_info.get('CPU사용률')}, "
                    f"메모리 {sys_info.get('메모리사용률')}"
                )

        # 웹 검색 결과
        if "web" in collected:
            web_data = collected["web"]
            if web_data.get("results"):
                sections.append("\n=== 웹 검색 결과 ===")
                for result in web_data["results"][:3]:  # 최대 3개
                    sections.append(f"- {result.get('title')}: {result.get('snippet')}")

        # 데이터 없을 때
        if not sections:
            return "제공된 데이터가 없습니다."

        return "\n".join(sections)

    except Exception as e:
        logger.error(f"컨텍스트 포맷팅 중 오류: {e}")
        return f"데이터 포맷팅 실패: {str(e)}"
