# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 단순화된 LLM 쿼리 핸들러 (Tool Use 방식)
# Tool Use를 사용하여 복잡한 분류 로직 없이 사용자 질문 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import asyncio
import traceback
from datetime import datetime

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.ai.llm_client import get_llm_response_with_tools
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
        logger.info("=" * 50)
        logger.info("    Tool Use 질의 처리 시작")
        logger.info("=" * 50)
        logger.info(f"사용자 질문: {user_query}")
        logger.info(f"농장 정보: {farm_name} (ID: {farm_id})")

        # 첨부 파일 처리
        full_query = user_query
        if file_paths:
            logger.info(f"첨부 파일 처리 중: {len(file_paths)}개 파일")
            file_content = process_uploaded_files(file_paths)
            full_query = f"{user_query}\n\n{file_content}"

        # Tool Use로 LLM 호출 (1단계로 완료)
        logger.info("\n[LLM Tool Use] 응답 생성 시작")
        response = await asyncio.to_thread(
            get_llm_response_with_tools,
            user_query=full_query,
            farm_name=farm_name
        )

        processing_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"\n질의 처리 완료 - 총 처리시간: {processing_time:.3f}초")
        logger.info(f"응답 길이: {len(response)}자")
        logger.info("=" * 50)

        yield response

    except Exception as e:
        logger.error(f"Tool Use 질의 처리 중 오류 발생: {e}")
        logger.error(traceback.format_exc())
        yield f"에러: 질의 처리 중 문제가 발생했습니다. ({str(e)})"
