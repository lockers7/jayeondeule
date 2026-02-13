# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 쿼리 통합 처리 모듈
# 사용자 쿼리를 받아 분석, 컨텍스트 수집, LLM 호출, 응답 생성까지
# 전체 파이프라인을 조율하는 핵심 핸들러입니다.
# --->
# query_llm_unified: 통합 질의 처리 (비동기 스트리밍)
# process_llm_query: LLM 질의 처리
# process_llm_query_simple: 단순 질의 처리 (동기)
# prepare_query_context: 질의 컨텍스트 준비
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
from datetime import datetime
from typing import Optional

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.config import NUM_PREDICT
from agri_ai_core.src.ai.llm_client import (
    get_llm_response,
    get_llm_streaming_response
)
from agri_ai_core.src.ai.query_analyzer import analyze_query_unified

logger = setup_logger(__name__)

# 제어 질의 유형
CONTROL_QUERY_TYPES = {"environment_control", "relay_control", "control_suggestion", "relay_llm_control"}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 통합 질의 처리 (비동기 스트리밍)
# 사용자 질의 처리 및 답변 생성
#
# Args:
#     user_query: 사용자 질의
#     file_paths: 첨부 파일 경로
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     farm_name: 농장명
#     house_name: 재배사명
#     stream: 스트리밍 여부
#
# Yields:
#     str: 응답 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def query_llm_unified(user_query, file_paths=None, farm_id=None, house_id=None,
                            farm_name=None, house_name=None, stream=False):
    start_time = datetime.now()

    try:
        analysis_result = analyze_query_unified(user_query, file_paths)

        if not farm_id and analysis_result.get("farm_id"):
            farm_id = analysis_result["farm_id"]
        if not farm_name and analysis_result.get("farm_name"):
            farm_name = analysis_result["farm_name"]

        logger.info("=" * 50)
        logger.info("    질의 처리 시작")
        logger.info("=" * 50)
        logger.info(f"농장, 재배사 정보: 농장ID={farm_id}, 이름={farm_name} - 재배사ID={house_id}, 이름={house_name}")
        logger.info(f"사용자 질문: {user_query}")
        if file_paths:
            logger.info(f"첨부 파일 수: {len(file_paths)}")
        logger.info(f"\n[0단계] 질문 유형 분석 시작 쿼리: {user_query}")

        special_command = analysis_result.get("special_command")
        query_type = analysis_result.get("query_type", "")
        llm_query_type = analysis_result.get("llm_query_type")
        hour = analysis_result.get("hour") or datetime.now().hour

        query_category = analysis_result.get("query_category", "general")
        logger.info(f"\n[1단계] 질의 유형: {query_type}, LLM 분석: {llm_query_type}, 분류 카테고리: {query_category}")

        # 날짜 관련 질문 처리
        if llm_query_type == "날짜관련질문":
            current_date = datetime.now()
            weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
            today_weekday = weekdays[current_date.weekday()]
            response = f"오늘은 {current_date.strftime('%Y년 %m월 %d일')} {today_weekday}입니다."
            logger.info(f"날짜 질문 직접 응답: {response}")
            yield response
            return

        # 특수 명령어 처리
        logger.info(f"\n[2단계] 특수한 질문 대상 판단: {special_command}")
        if special_command:
            if special_command == "llm_identity":
                farm_name_display = f"{farm_name}" if farm_name else "스마트팜"
                response = f"안녕하세요! 저는 {farm_name_display}의 지킴이입니다. 스마트팜 데이터를 관리하고 분석하여 농장주님께 도움을 드리는 AI 어시스턴트입니다. 어떤 도움이 필요하신가요?"
                yield response
                return

        # 컨텍스트 데이터 검색
        logger.info("\n[3단계] 질문 관련 데이터 검색 시작")
        context_data = {
            "learned_data": [],
            "stats_data": [],
            "optimal_data": [],
            "current_data": [],
            "document_data": [],
            "farm_info": {
                "farm_id": farm_id,
                "farm_name": farm_name,
                "house_id": house_id,
                "house_name": house_name
            }
        }

        if query_category == "general":
            logger.info("일반 대화형 질문으로 판단되어 농장 데이터 조회를 생략합니다.")

        # 프롬프트 생성
        logger.info("\n[4단계] 프롬프트 생성 시작")
        default_system_prompt = "너는 스마트팜 농장 지킴이이다."
        system_prompt = default_system_prompt
        user_prompt = f"사용자 질문: {user_query}\n답변해주세요."

        logger.info("\n[5단계] LLM 응답 생성 시작")
        if not stream:
            llm_response = ""
            async for chunk in process_llm_query(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                query_type=query_type,
                context_data=context_data,
                hour=hour,
                stream=False
            ):
                llm_response += chunk

            processing_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"\n질의 처리 완료 - 총 처리시간: {processing_time:.3f}초")
            logger.info("=" * 50)

            yield llm_response
        else:
            full_response = ""
            async for chunk in process_llm_query(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                query_type=query_type,
                context_data=context_data,
                hour=hour,
                stream=True
            ):
                full_response += chunk
                yield chunk

            processing_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"\n질의 처리 완료 - 총 처리시간: {processing_time:.3f}초")
            logger.info("=" * 50)

    except Exception as e:
        logger.error(f"질의 처리 중 오류 발생: {e}")
        logger.error(traceback.format_exc())
        yield f"에러: 질의 처리 중 문제가 발생했습니다. ({str(e)})"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 질의 처리
# LLM 질의 처리 및 응답 생성
#
# Args:
#     system_prompt: 시스템 프롬프트
#     user_prompt: 사용자 프롬프트
#     query_type: 질의 유형
#     context_data: 컨텍스트 데이터
#     hour: 시간대
#     stream: 스트리밍 여부
#     llm_options: LLM 옵션
#     control_mode: 제어 모드
#
# Yields:
#     str: 응답 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def process_llm_query(system_prompt=None, user_prompt=None, query_type=None,
                            context_data=None, hour=None, stream=False,
                            llm_options=None, control_mode: Optional[str] = None):
    start_time = datetime.now()
    if system_prompt is None:
        system_prompt = ""
    try:
        system_length = len(system_prompt)
        user_length = len(user_prompt)
        total_length = system_length + user_length
        logger.info("\n" * 1)
        if not stream:
            logger.info("=" * 20 + " " + ">" * 3 + " LLM PROCESSING START " + "<" * 3 + " " + "=" * 20)
        else:
            logger.info("=" * 20 + " " + ">" * 3 + " LLM STREAM PROCESSING START " + "<" * 3 + " " + "=" * 20)
        logger.info(f"[1] 질의 유형: {query_type}자 \n 프롬프트 길이: {total_length}")
        logger.info(f"[2] 시스템 질의: {system_length}자\n {system_prompt}")
        logger.info(f"[3] 사용자 질의: {user_length}자\n {user_prompt}")
        logger.info(">>>" + "-" * 50 + "<<<")

        if not stream:
            if llm_options:
                response = get_llm_response(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    query_type=query_type,
                    llm_options=llm_options
                )
            elif query_type == "relay_llm_control":
                response = get_llm_response(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    top_p=0.8,
                    top_k=20,
                    num_predict=NUM_PREDICT,
                    query_type=query_type
                )
            else:
                response = get_llm_response(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt
                )
        else:
            response = ""
            async for chunk in get_llm_streaming_response(user_prompt):
                response += chunk
                yield chunk

        response_length = len(response)
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"[4] LLM 응답: {response_length}자\n\n\n{response}")
        logger.info(f"[5] 처리 시간: {processing_time:.3f}초")
        if not stream:
            logger.info("=" * 20 + " " + ">" * 3 + " LLM PROCESSING FINISH " + "<" * 3 + " " + "=" * 20)
            logger.info("\n" * 1)

            yield response
        else:
            logger.info("=" * 20 + " " + ">" * 3 + " LLM STREAM PROCESSING FINISH " + "<" * 3 + " " + "=" * 20)
            logger.info("\n" * 1)

    except Exception as e:
        logger.error(f"LLM 질의 처리 중 오류: {e}")
        logger.error(traceback.format_exc())

        error_message = "죄송합니다. 응답 생성 중 오류가 발생했습니다."
        yield error_message


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 단순 질의 처리 (동기)
# 단순 질의 처리 (동기 버전)
#
# Args:
#     user_query: 사용자 질의
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     farm_name: 농장명
#     house_name: 재배사명
#
# Returns:
#     str: LLM 응답
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_llm_query_simple(user_query=None, farm_id=None, house_id=None,
                             farm_name=None, house_name=None):
    try:
        context_result = prepare_query_context(user_query, None, farm_id, house_id, farm_name, house_name)

        prompt_payload = context_result.get("prompt", "")
        query_type = context_result.get("query_type", "general_chat")

        if prompt_payload:
            if isinstance(prompt_payload, dict):
                system_prompt = prompt_payload.get("system_prompt")
                user_prompt = prompt_payload.get("user_prompt")
                llm_options = prompt_payload.get("llm_options")
            else:
                system_prompt = None
                user_prompt = prompt_payload
                llm_options = None

            llm_response = get_llm_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                llm_options=llm_options
            )

            return llm_response
        else:
            return "질문을 처리할 수 없습니다. 다시 시도해주세요."

    except Exception as e:
        logger.error(f"단순 질의 처리 중 오류: {e}")
        logger.error(traceback.format_exc())
        return f"질의 처리 중 오류가 발생했습니다: {str(e)}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질의 컨텍스트 준비
# LLM 응답 생성에 필요한 컨텍스트 준비
#
# Args:
#     user_query: 사용자 질의
#     file_paths: 첨부 파일 경로
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     farm_name: 농장명
#     house_name: 재배사명
#
# Returns:
#     dict: 컨텍스트 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def prepare_query_context(user_query, file_paths=None, farm_id=None, house_id=None,
                          farm_name=None, house_name=None):
    logger.info(f"prepare_query_context user_query: {user_query}")
    try:
        analysis_result = analyze_query_unified(user_query, file_paths)

        query_type = analysis_result.get("query_type", "")
        hour = analysis_result.get("hour") or datetime.now().hour
        query_category = analysis_result.get("query_category", "general")

        if not farm_id and analysis_result.get("farm_id"):
            farm_id = analysis_result["farm_id"]
        if not farm_name and analysis_result.get("farm_name"):
            farm_name = analysis_result["farm_name"]

        # 컨텍스트 데이터 구성
        if query_category == "general":
            context_data = {
                "learned_data": [],
                "stats_data": [],
                "optimal_data": [],
                "current_data": [],
                "document_data": [],
                "farm_info": {
                    "farm_id": farm_id,
                    "farm_name": farm_name,
                    "house_id": house_id,
                    "house_name": house_name
                }
            }
        else:
            context_data = {
                "learned_data": [],
                "stats_data": [],
                "optimal_data": [],
                "current_data": [],
                "document_data": [],
                "farm_info": {
                    "farm_id": farm_id,
                    "farm_name": farm_name,
                    "house_id": house_id,
                    "house_name": house_name
                }
            }

        # 기본 프롬프트 구성
        prompt_payload = {
            "system_prompt": "너는 스마트팜 농장 지킴이이다.",
            "user_prompt": f"사용자 질문: {user_query}\n답변해주세요."
        }

        return {
            "query_type": query_type,
            "farm_id": farm_id,
            "hour": hour,
            "context_data": context_data,
            "prompt": prompt_payload,
            "special_command": None
        }

    except Exception as e:
        logger.error(f"컨텍스트 준비 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "query_type": "general_chat",
            "farm_id": farm_id,
            "hour": datetime.now().hour,
            "context_data": {"current_data": [], "learned_data": [], "optimal_data": [], "stats_data": []},
            "prompt": {
                "system_prompt": "",
                "user_prompt": f"사용자 질문: {user_query}\n간단하게 답변해주세요."
            },
            "special_command": None
        }
