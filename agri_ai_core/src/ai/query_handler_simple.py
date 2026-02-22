# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 쿼리 핸들러 (Tool Use 방식)
# LLM이 필요한 도구를 자율적으로 선택하고 실행하여 사용자 질문 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import asyncio
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger, setup_web_logger
from agri_ai_core.src.ai.llm_client import get_llm_response_with_tools
from agri_ai_core.src.ai.file_processor import process_uploaded_files

logger = setup_logger(__name__)
web_logger = setup_web_logger("chat")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질의 처리 (Tool Use 방식)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def query_llm_simple(user_query, file_paths=None, farm_id=None, house_id=None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use를 사용한 질의 처리
# LLM이 필요한 도구를 자율적으로 선택하고 호출하여 답변 생성
# Args: user_query: 사용자 질의
#       file_paths: 첨부 파일 경로
#       farm_id: 농장 ID
#       house_id: 재배사 ID
#       farm_name: 농장명
#       house_name: 재배사명
# Returns: str: 응답 텍스트
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
                           farm_name=None, house_name=None):
    start_time = datetime.now()

    try:
        # [1/3] 사용자 질문
        logger.info(f"[사용자질문] \"{(user_query or '')[:120]}\" (len={len(user_query or '')}, farm={farm_name or '-'})")

        # 웹 로그: 요청 JSON 기록
        request_json = {
            "type": "chat_request",
            "timestamp": start_time.isoformat(),
            "query": user_query,
            "farm_id": farm_id,
            "house_id": house_id,
            "farm_name": farm_name,
            "house_name": house_name,
            "files": [f.get("filename", "") for f in file_paths] if file_paths else [],
        }
        web_logger.info(
            "[Chat 요청]\n%s",
            json.dumps(request_json, ensure_ascii=False, indent=2),
        )

        # 첨부 파일 처리
        full_query = user_query
        if file_paths:
            logger.info(f"[첨부파일] {len(file_paths)}개 파일 처리")
            file_content = process_uploaded_files(file_paths)
            full_query = f"{user_query}\n\n{file_content}"

        default_tool_args = {
            "search_web": {"query": full_query},
            "search_farm_knowledge": {"query": full_query, "n_results": 3},
            "get_farm_realtime_data": {
                "farm_id": str(farm_id) if farm_id is not None else None,
                "house_id": str(house_id) if house_id is not None else None,
                "data_type": "all",
            },
        }

        # [2/3] LLM 답변 생성 (LLM이 도구 자율 선택)
        llm_start = datetime.now()
        logger.info("[LLM시작] 모드=Tool Use (LLM 자율 도구 선택)")
        response = await asyncio.to_thread(
            get_llm_response_with_tools,
            user_query=full_query,
            farm_name=farm_name,
            default_tool_args=default_tool_args,
        )

        llm_elapsed = (datetime.now() - llm_start).total_seconds()
        total_elapsed = (datetime.now() - start_time).total_seconds()

        # [3/3] 최종 답변
        logger.info(f"[LLM완료] 답변생성={llm_elapsed:.1f}s")
        answer_preview = (response or "")[:200]
        if len(response or "") > 200:
            answer_preview += "..."
        logger.info(f"[최종답변] len={len(response or '')} 총소요={total_elapsed:.1f}s")
        logger.info(f"[답변내용] {answer_preview}")

        # 웹 로그: 응답 JSON 기록
        response_json = {
            "type": "chat_response",
            "timestamp": datetime.now().isoformat(),
            "query": user_query,
            "response": response,
            "processing_time": round(total_elapsed, 3),
            "farm_name": farm_name,
            "house_name": house_name,
        }
        web_logger.info(
            "[Chat 응답]\n%s",
            json.dumps(response_json, ensure_ascii=False, indent=2),
        )

        yield response

    except Exception as e:
        logger.error(f"Tool Use 질의 처리 중 오류 발생: {e}")
        logger.error(traceback.format_exc())
        yield f"에러: 질의 처리 중 문제가 발생했습니다. ({str(e)})"
