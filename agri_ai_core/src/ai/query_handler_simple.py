# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 단순화된 LLM 쿼리 핸들러 (Tool Use 방식)
# Tool Use를 사용하여 복잡한 분류 로직 없이 사용자 질문 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import asyncio
import traceback
import hashlib
import os
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.llm_client import get_llm_response, get_llm_response_with_tools
from agri_ai_core.src.ai.query_router import ROUTE_LLM_ONLY, build_query_route_plan
from agri_ai_core.src.ai.file_processor import process_uploaded_files

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 단순 질의 처리 (Tool Use 방식)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def query_llm_simple(user_query, file_paths=None, farm_id=None, house_id=None,
                           farm_name=None, house_name=None):
    """
    Tool Use를 사용한 단순화된 질의 처리

    Args:
        user_query: 사용자 질의
        file_paths: 첨부 파일 경로
        farm_id: 농장 ID
        house_id: 재배사 ID
        farm_name: 농장명
        house_name: 재배사명

    Yields:
        str: 응답 텍스트
    """
    start_time = datetime.now()

    try:
        logger.debug("=" * 50)
        logger.debug("    Tool Use 질의 처리 시작")
        logger.debug("=" * 50)
        query_digest = hashlib.sha1((user_query or "").encode("utf-8", errors="replace")).hexdigest()[:12]
        logger.debug(f"요청 수신: len={len(user_query or '')} digest={query_digest}")
        logger.debug(f"농장 정보: {farm_name} (ID: {farm_id})")

        # 첨부 파일 처리
        full_query = user_query
        if file_paths:
            logger.debug(f"첨부 파일 처리 중: {len(file_paths)}개 파일")
            file_content = process_uploaded_files(file_paths)
            full_query = f"{user_query}\n\n{file_content}"

        # 자동 라우팅으로 1/2/3/4 경로 선택
        auto_route_enabled = str(os.getenv("AUTO_QUERY_ROUTING", "true")).strip().lower() in {
            "1", "true", "yes", "y", "on"
        }
        route_plan = None
        if auto_route_enabled:
            route_plan = build_query_route_plan(
                user_query=full_query,
                farm_id=farm_id,
                house_id=house_id,
            )
            logger.info(
                "[AutoRoute] mode=%s strategy=%s reason=%s tools=%s confidence=%.2f capabilities=%s",
                route_plan.mode_label,
                route_plan.strategy,
                route_plan.reason,
                route_plan.allowed_tool_names,
                route_plan.confidence,
                route_plan.capabilities,
            )
        else:
            logger.info("[AutoRoute] 비활성화(AUTO_QUERY_ROUTING=false) -> 기존 Tool Use 전체 허용")

        default_tool_args = {
            "search_web": {"query": full_query},
            "search_farm_knowledge": {"query": full_query, "n_results": 3},
            "get_farm_realtime_data": {
                "farm_id": str(farm_id) if farm_id is not None else None,
                "house_id": str(house_id) if house_id is not None else None,
                "data_type": "all",
            },
        }

        # 경로 1(LLM 자체) + 도구 없음이면 일반 LLM 호출, 그 외에는 Tool Use 호출
        if route_plan and route_plan.mode == ROUTE_LLM_ONLY and not route_plan.allowed_tool_names:
            logger.debug("\n[LLM] 라우팅 모드 1(도구 없음)으로 응답 생성")
            llm_system_prompt = (
                "당신은 다양한 분야의 지식을 갖춘 친근한 AI 어시스턴트입니다.\n\n"
                "**대화 원칙:**\n"
                "- 한글로 자연스럽고 친근하게 대화합니다.\n"
                "- 인사나 일상 대화에는 따뜻하고 다정하게 응대하며, 대화를 이어갈 수 있는 질문이나 화제를 제안합니다.\n"
                "- 질문에는 구체적이고 실용적인 정보를 포함하여 충분히 답변합니다.\n"
                "- 정보가 부족하면 솔직하게 말하되, 관련된 유용한 내용을 추가로 안내합니다.\n"
                "- 사용자의 의도를 파악하여 맥락에 맞는 풍부한 답변을 제공합니다.\n\n"
                "**출력 형식:**\n"
                "- 내부 추론/독백/분석 과정을 절대 출력하지 않습니다.\n"
                "- 최종 사용자에게 보여줄 순수 답변 본문만 출력합니다."
            )
            if route_plan.route_system_prompt:
                llm_system_prompt = f"{llm_system_prompt}\n\n{route_plan.route_system_prompt}"

            response = await asyncio.to_thread(
                get_llm_response,
                system_prompt=llm_system_prompt,
                user_prompt=full_query,
                query_type="general",
            )
        else:
            logger.debug("\n[LLM Tool Use] 라우팅 기반 응답 생성 시작")
            response = await asyncio.to_thread(
                get_llm_response_with_tools,
                user_query=full_query,
                farm_name=farm_name,
                allowed_tool_names=(route_plan.allowed_tool_names if route_plan else None),
                route_system_prompt=(route_plan.route_system_prompt if route_plan else None),
                enable_recent_web_context=(route_plan.enable_recent_web_context if route_plan else None),
                default_tool_args=default_tool_args,
            )

        processing_time = (datetime.now() - start_time).total_seconds()
        logger.debug(f"\n질의 처리 완료 - 총 처리시간: {processing_time:.3f}초")
        logger.debug(f"응답 길이: {len(response)}자")
        logger.debug("=" * 50)

        yield response

    except Exception as e:
        logger.error(f"Tool Use 질의 처리 중 오류 발생: {e}")
        logger.error(traceback.format_exc())
        yield f"에러: 질의 처리 중 문제가 발생했습니다. ({str(e)})"
