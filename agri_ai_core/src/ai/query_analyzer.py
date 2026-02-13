# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 쿼리 분석기 모듈
# 사용자 쿼리에서 핵심 정보(농장명, 재배사, 날짜 등)를 추출하고,
# 쿼리 의도를 심층 분석하여 적절한 응답을 생성하도록 지원합니다.
# --->
# analyze_and_respond_unified: 메인 통합 함수
# analyze_and_respond_unified_sync: 동기 버전 (기존 코드 호환성)
# analyze_query_unified: 기존 인터페이스 호환 함수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.ai.query_classifier import classify_query_fast, QueryType
from agri_ai_core.src.ai.context_collector import collect_context_parallel
from agri_ai_core.src.ai.response_generator import (
    validate_data_sufficiency,
    generate_final_response
)

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 메인 통합 함수
# 사용자 질문을 분석하고 최종 답변을 생성하는 통합 함수
#
# **처리 흐름:**
# 1단계: LLM으로 질문 분류 및 필요 데이터 식별
# 2단계: 필요한 데이터를 병렬로 수집 (농장, 시스템, 웹)
# 3단계: (선택적) 데이터 충분성 검증
# 4단계: 컨텍스트 기반 최종 답변 생성
#
# Args:
#     user_query: 사용자 질문
#     farm_id: 농장 ID (선택)
#     house_id: 재배사 ID (선택)
#     farm_name: 농장명 (선택)
#     house_name: 재배사명 (선택)
#     stream: 스트리밍 모드
#
# Returns:
#     dict: 최종 결과
#     {
#         "response": "최종 답변",
#         "classification": {...},
#         "context": {...},
#         "metadata": {...}
#     }
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def analyze_and_respond_unified(
    user_query: str,
    farm_id: Optional[str] = None,
    house_id: Optional[str] = None,
    farm_name: Optional[str] = None,
    house_name: Optional[str] = None,
    stream: bool = False
) -> Dict[str, Any]:
    start_time = datetime.now()

    try:
        logger.info(f"질의 처리 시작: '{user_query[:100]}...'")

        # ============================================================
        # 1단계: LLM 기반 질문 분류 (초고속)
        # ============================================================
        logger.info("[1/4] 질문 분류 중...")
        classification = await classify_query_fast(user_query)

        # 농장 정보 병합 (사용자가 제공한 정보 우선)
        if farm_id or house_id:
            if classification["required_data"].get("farm"):
                classification["required_data"]["farm"]["farm_id"] = farm_id or classification["required_data"]["farm"].get("farm_id")
                classification["required_data"]["farm"]["house_id"] = house_id or classification["required_data"]["farm"].get("house_id")

        logger.info(
            f"[1/4] 분류 완료: {classification['query_types']} "
            f"(신뢰도: {classification['confidence']:.2f})"
        )

        # ============================================================
        # 빠른 경로: LLM 직접 응답 (데이터 수집 불필요)
        # ============================================================
        if classification.get("can_answer_directly"):
            logger.info("[Fast] LLM 직접 응답 모드")
            from agri_ai_core.src.ai.response_generator import generate_direct_response

            response_text = await generate_direct_response(user_query, stream)

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"[Fast] 직접 응답 완료 ({elapsed:.2f}초)")

            return {
                "response": response_text,
                "classification": classification,
                "context": None,
                "metadata": {
                    "mode": "direct",
                    "elapsed_seconds": elapsed,
                    "timestamp": datetime.now().isoformat()
                }
            }

        # ============================================================
        # 2단계: 병렬 데이터 수집
        # ============================================================
        logger.info("[2/4] 데이터 수집 중...")
        collected_context = await collect_context_parallel(classification)

        logger.info(
            f"[2/4] 데이터 수집 완료: {collected_context.get('summary', 'N/A')}"
        )

        # ============================================================
        # 3단계: 데이터 충분성 검증 (선택적)
        # ============================================================
        validation = None
        if classification.get("confidence", 1.0) < 0.85:
            logger.info("[3/4] 데이터 충분성 검증 중...")
            validation = await validate_data_sufficiency(
                user_query,
                classification,
                collected_context
            )

            logger.info(
                f"[3/4] 검증 완료: {'충분' if validation['sufficient'] else '불충분'} "
                f"- {validation['reasoning']}"
            )

            # 데이터 불충분 시 추가 수집 (현재는 로깅만)
            if not validation["sufficient"]:
                logger.warning(f"부족한 데이터: {validation['missing_data']}")
                # TODO: 추가 데이터 수집 로직
        else:
            logger.info("[3/4] 검증 생략 (높은 신뢰도)")

        # ============================================================
        # 4단계: 최종 답변 생성
        # ============================================================
        logger.info("[4/4] 최종 답변 생성 중...")
        response_text = await generate_final_response(
            user_query,
            classification,
            collected_context,
            stream
        )

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[4/4] 답변 생성 완료 ({elapsed:.2f}초, {len(response_text)}자)")

        # ============================================================
        # 최종 결과 반환
        # ============================================================
        return {
            "response": response_text,
            "classification": classification,
            "context": collected_context,
            "validation": validation,
            "metadata": {
                "mode": "context_based",
                "elapsed_seconds": elapsed,
                "timestamp": datetime.now().isoformat(),
                "query_types": classification.get("query_types", []),
                "confidence": classification.get("confidence", 0)
            }
        }

    except Exception as e:
        logger.error(f"질의 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())

        elapsed = (datetime.now() - start_time).total_seconds()

        return {
            "response": f"죄송합니다. 질문을 처리하는 중 오류가 발생했습니다: {str(e)}",
            "classification": None,
            "context": None,
            "validation": None,
            "metadata": {
                "mode": "error",
                "elapsed_seconds": elapsed,
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 동기 버전 (기존 코드 호환성)
# 동기 버전의 통합 질의 분석 및 응답 함수
#
# Args:
#     user_query: 사용자 질문
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     farm_name: 농장명
#     house_name: 재배사명
#     stream: 스트리밍 모드
#
# Returns:
#     dict: 최종 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_and_respond_unified_sync(
    user_query: str,
    farm_id: Optional[str] = None,
    house_id: Optional[str] = None,
    farm_name: Optional[str] = None,
    house_name: Optional[str] = None,
    stream: bool = False
) -> Dict[str, Any]:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        analyze_and_respond_unified(
            user_query,
            farm_id,
            house_id,
            farm_name,
            house_name,
            stream
        )
    )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 기존 인터페이스 호환 함수
# 기존 analyze_query_unified 인터페이스 호환 함수
# (하위 호환성 유지)
#
# Args:
#     query: 사용자 질의
#     file_paths: 첨부 파일 (미사용)
#     enhanced_mode: 향상 모드 (항상 True)
#
# Returns:
#     dict: 분류 결과 (기존 형식과 유사)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def analyze_query_unified(
    query: str,
    file_paths: Optional[list] = None,
    enhanced_mode: bool = True
) -> Dict[str, Any]:
    try:
        # 새로운 시스템으로 처리
        result = analyze_and_respond_unified_sync(query)

        # 기존 형식으로 변환
        classification = result.get("classification", {})

        return {
            "query_type": classification.get("query_types", ["일반질문"])[0],
            "query_types": classification.get("query_types", ["일반질문"]),
            "can_answer_directly": classification.get("can_answer_directly", False),
            "query_category": "general",  # 기존 호환성
            "needs_web_search": QueryType.WEB_SEARCH in classification.get("query_types", []),
            "web_search_keywords": classification.get("required_data", {}).get("web", {}).get("search_keywords") if classification.get("required_data", {}).get("web") else None,
            "farm_id": classification.get("required_data", {}).get("farm", {}).get("farm_id") if classification.get("required_data", {}).get("farm") else None,
            "house_id": classification.get("required_data", {}).get("farm", {}).get("house_id") if classification.get("required_data", {}).get("farm") else None,
            "confidence": classification.get("confidence", 0.5),
            "reasoning": classification.get("reasoning", ""),
            "special_command": None,
            "found_farm_names": [],
            "found_house_names": []
        }

    except Exception as e:
        logger.error(f"기존 인터페이스 호환 처리 중 오류: {e}")
        return {
            "query_type": "general_chat",
            "query_category": "general",
            "needs_web_search": False,
            "confidence": 0.3,
            "error": str(e)
        }
