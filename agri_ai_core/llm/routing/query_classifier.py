# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 쿼리 분류기 모듈
# 사용자 쿼리의 의도를 분석하여 적절한 처리 경로로 라우팅하며,
# 제어 명령, 정보 조회, 일반 대화 등을 구분합니다.
# --->
# [클래스] QueryType: 질의 유형 정의
# classify_query_fast: 1단계: 초고속 질문 분류 (LLM 1차 호출)
# parse_classification_response: JSON 응답 파싱
# fallback_classification: 폴백 분류 (JSON 파싱 실패 시)
# classify_query_fast_sync: 동기 버전 (기존 코드 호환성)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import re
from typing import Dict, Any

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.llm.core.llm_client import get_llm_response

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질의 유형 정의
# 질의 유형 상수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class QueryType:
    DIRECT_LLM = "llm자체응답"      # LLM이 직접 답변 가능
    FARM_DATA = "농장데이터참고"     # 농장 센서/설정 데이터 필요
    SYSTEM_INFO = "시스템정보참고"   # 날짜/시스템 정보 필요
    WEB_SEARCH = "웹검색"           # 웹 검색 필요


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 1단계: 초고속 질문 분류 (LLM 1차 호출)
# LLM을 사용하여 사용자 질문을 빠르게 분류하고 필요한 데이터를 식별
#
# Args:
#     user_query: 사용자 질문
#
# Returns:
#     dict: 구조화된 분류 결과
#     {
#         "query_types": ["llm자체응답"] or ["농장데이터참고", "시스템정보참고"],
#         "can_answer_directly": True/False,
#         "required_data": {
#             "farm": {...},
#             "system": {...},
#             "web": {...}
#         },
#         "confidence": 0.95,
#         "reasoning": "분류 근거"
#     }
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def classify_query_fast(user_query: str) -> Dict[str, Any]:
    try:
        system_prompt = """당신은 스마트팜 질문 분류 전문가입니다. 사용자 질문을 분석하여 어떤 데이터가 필요한지 판단하세요.

**4가지 유형:**
1. **llm자체응답**: 일반 인사, 간단한 대화만 (예: "안녕", "고마워")
2. **농장데이터참고**: 2가지로 세분화
   - **farm_knowledge (ChromaDB)**: 스마트팜 개념, 재배 기술, 농업 지식 질문
     예: "스마트팜이란?", "토마토 재배법", "LED 조명 효과"
   - **farm_realtime (PostgreSQL)**: 실시간 센서/릴레이 데이터 질문
     예: "1재배사 온도", "릴레이 상태", "현재 습도"
3. **시스템정보참고**: 현재 날짜/시간/시스템 상태
4. **웹검색**: 실시간 외부 정보 (날씨, 뉴스 등)

**핵심 규칙:**
- ⚠️ 농장/스마트팜 관련 전문 지식 → farm_knowledge 필수
- ⚠️ "N재배사", "N농장" 같은 구체적 데이터 → farm_realtime 필수
- 복합 가능 (예: "스마트팜이란? 그리고 1재배사 온도는?" → farm_knowledge + farm_realtime)
- 일반 인사/대화만 llm자체응답

**출력 형식 (반드시 JSON):**
```json
{
  "query_types": ["유형1", "유형2"],
  "can_answer_directly": true/false,
  "required_data": {
    "farm_knowledge": {
      "query": "사용자질문원문" or null,
      "n_results": 3
    },
    "farm_realtime": {
      "farm_id": null or "추출된ID",
      "house_id": null or "추출된ID"
    },
    "system": {
      "current_time": true/false,
      "current_date": true/false,
      "system_status": true/false
    },
    "web": {
      "search_keywords": "검색어" or null,
      "search_type": "날씨" or "뉴스" or null
    }
  },
  "confidence": 0.0~1.0,
  "reasoning": "분류 근거 1줄"
}
```

**예시:**
질문: "안녕하세요"
```json
{
  "query_types": ["llm자체응답"],
  "can_answer_directly": true,
  "required_data": {"farm_knowledge": null, "farm_realtime": null, "system": null, "web": null},
  "confidence": 1.0,
  "reasoning": "일반 인사로 LLM이 직접 답변 가능"
}
```

질문: "스마트팜이 뭐야?"
```json
{
  "query_types": ["농장데이터참고"],
  "can_answer_directly": false,
  "required_data": {
    "farm_knowledge": {"query": "스마트팜이 뭐야?", "n_results": 3},
    "farm_realtime": null,
    "system": null,
    "web": null
  },
  "confidence": 0.95,
  "reasoning": "ChromaDB 농장 지식 검색 필요"
}
```

질문: "1재배사 상태는?"
```json
{
  "query_types": ["농장데이터참고"],
  "can_answer_directly": false,
  "required_data": {
    "farm_knowledge": null,
    "farm_realtime": {"farm_id": "1", "house_id": "1"},
    "system": null,
    "web": null
  },
  "confidence": 0.9,
  "reasoning": "PostgreSQL 실시간 센서/릴레이 데이터 조회 필요"
}
```

**절대 규칙: JSON만 출력, 다른 설명 금지**"""

        user_prompt = f"질문: {user_query}"

        # LLM 호출 (초고속 설정 - 최적화)
        llm_response = get_llm_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            top_p=0.8,
            top_k=20,
            num_predict=150,  # 300 → 150으로 단축 (JSON은 짧음)
            query_type="fast_classification"
        )

        # JSON 파싱
        classification = parse_classification_response(llm_response)

        logger.info(f"질문 분류 완료: {user_query[:50]}... -> {classification['query_types']}")

        return classification

    except Exception as e:
        logger.error(f"질문 분류 중 오류: {e}")
        # 폴백: 안전한 기본값
        return {
            "query_types": [QueryType.DIRECT_LLM],
            "can_answer_directly": True,
            "required_data": {"farm": None, "system": None, "web": None},
            "confidence": 0.3,
            "reasoning": f"분류 실패, 기본 모드로 처리: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# JSON 응답 파싱
# LLM의 JSON 응답을 파싱하여 구조화된 딕셔너리로 변환
#
# Args:
#     llm_response: LLM의 원본 응답
#
# Returns:
#     dict: 파싱된 분류 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def parse_classification_response(llm_response: str) -> Dict[str, Any]:
    try:
        # JSON 코드 블록 제거
        cleaned_response = llm_response.strip()

        # ```json ... ``` 형식 처리
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, cleaned_response, re.DOTALL)
        if match:
            cleaned_response = match.group(1)
        else:
            # ``` ... ``` 형식 처리
            json_pattern = r'```\s*(\{.*?\})\s*```'
            match = re.search(json_pattern, cleaned_response, re.DOTALL)
            if match:
                cleaned_response = match.group(1)

        # { ... } 추출
        if not cleaned_response.startswith('{'):
            brace_start = cleaned_response.find('{')
            brace_end = cleaned_response.rfind('}')
            if brace_start != -1 and brace_end != -1:
                cleaned_response = cleaned_response[brace_start:brace_end+1]

        # JSON 파싱
        parsed = json.loads(cleaned_response)

        # 필수 필드 검증
        if "query_types" not in parsed:
            parsed["query_types"] = [QueryType.DIRECT_LLM]
        if "can_answer_directly" not in parsed:
            parsed["can_answer_directly"] = True
        if "required_data" not in parsed:
            parsed["required_data"] = {"farm": None, "system": None, "web": None}
        if "confidence" not in parsed:
            parsed["confidence"] = 0.5
        if "reasoning" not in parsed:
            parsed["reasoning"] = "파싱 성공"

        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패: {e}\n원본: {llm_response}")
        # 키워드 기반 폴백
        return fallback_classification(llm_response)
    except Exception as e:
        logger.error(f"응답 파싱 중 오류: {e}")
        return fallback_classification(llm_response)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 폴백 분류 (JSON 파싱 실패 시)
# JSON 파싱 실패 시 키워드 기반 폴백 분류
#
# Args:
#     llm_response: LLM 응답
#
# Returns:
#     dict: 기본 분류 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def fallback_classification(llm_response: str) -> Dict[str, Any]:
    query_types = []
    required_data = {"farm": None, "system": None, "web": None}

    # 키워드 기반 유형 추론
    if any(keyword in llm_response for keyword in ["농장", "센서", "온도", "습도", "릴레이"]):
        query_types.append(QueryType.FARM_DATA)
        required_data["farm"] = {
            "farm_id": None,
            "house_id": None,
            "metrics": ["온도", "습도"],
            "time_range": "현재",
            "relay_info": False
        }

    if any(keyword in llm_response for keyword in ["날짜", "시간", "오늘", "어제"]):
        query_types.append(QueryType.SYSTEM_INFO)
        required_data["system"] = {
            "current_time": True,
            "current_date": True,
            "system_status": False
        }

    if any(keyword in llm_response for keyword in ["날씨", "검색", "뉴스"]):
        query_types.append(QueryType.WEB_SEARCH)
        required_data["web"] = {
            "search_keywords": None,
            "search_type": None
        }

    # 아무것도 없으면 직접 응답
    if not query_types:
        query_types = [QueryType.DIRECT_LLM]

    return {
        "query_types": query_types,
        "can_answer_directly": QueryType.DIRECT_LLM in query_types and len(query_types) == 1,
        "required_data": required_data,
        "confidence": 0.4,
        "reasoning": "JSON 파싱 실패, 키워드 기반 폴백"
    }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 동기 버전 (기존 코드 호환성)
# 동기 버전의 질문 분류 함수
#
# Args:
#     user_query: 사용자 질문
#
# Returns:
#     dict: 분류 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def classify_query_fast_sync(user_query: str) -> Dict[str, Any]:
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(classify_query_fast(user_query))
