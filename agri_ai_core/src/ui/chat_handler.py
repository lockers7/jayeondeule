# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Streamlit 채팅 핸들러 모듈
# 채팅 인터페이스의 메시지 표시, 입력 처리, 세션 관리 등
# UI 레벨의 채팅 기능을 구현합니다.
# --->
# display_chat_history: 채팅 기록 표시
# process_message_with_modules: 모듈 직접 호출을 통한 메시지 처리
# run_query: 기능 설명 필요
# run_streaming_query: 기능 설명 필요
# run_sync_fallback: 기능 설명 필요
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import asyncio
import traceback
import streamlit as stl

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.ai.query_handler import query_llm_unified, process_llm_query_simple
from agri_ai_core.src.ai.llm_client import clean_llm_response, clean_streaming_chunk

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 대화 기록 표시
# --->
# 채팅 기록 표시
# Args:
#     reverse: True면 최신 메시지를 상단에 표시 (역순)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def display_chat_history(reverse: bool = False):
    messages = stl.session_state.messages[::-1] if reverse else stl.session_state.messages
    for message in messages:
        try:
            if isinstance(message, tuple) and len(message) == 2:
                role, content = message
                with stl.chat_message(role):
                    stl.markdown(content)
            elif isinstance(message, dict):
                role = message.get("role", "user")
                content = message.get("content", "")
                with stl.chat_message(role):
                    stl.markdown(content)
                    if "files" in message and message["files"]:
                        for file in message["files"]:
                            stl.markdown(f"""
                            <div class='file-attachment'>
                                📎 <span class='file-name'>{file["name"]}</span>
                            </div>
                            """, unsafe_allow_html=True)
            else:
                stl.warning("잘못된 메시지 형식입니다.")
        except Exception as e:
            stl.error(f"메시지 표시 중 오류 발생: {str(e)}")
            continue


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 모듈 직접 호출 방식으로 메시지 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def process_message_with_modules(
    user_input: str,
    uploaded_files: list,
    farm_id: int = None,
    house_id: int = None,
    farm_name: str = None,
    house_name: str = None
) -> str:
    """
    모듈 직접 호출을 통한 메시지 처리

    Args:
        user_input: 사용자 입력
        uploaded_files: 업로드된 파일 목록
        farm_id: 농장 ID
        house_id: 재배사 ID
        farm_name: 농장명
        house_name: 재배사명

    Returns:
        str: LLM 응답
    """
    try:
        file_paths = (
            [{"filename": file["name"], "path": file["path"]} for file in uploaded_files]
            if uploaded_files
            else None
        )

        message_placeholder = stl.empty()
        message_placeholder.markdown("응답을 생성 중입니다...")

        full_response = ""

        async def run_query():
            nonlocal full_response

            async for chunk in query_llm_unified(
                user_input,
                file_paths,
                farm_id,
                house_id,
                farm_name,
                house_name,
                stream=True
            ):
                if not chunk:
                    continue

                cleaned_chunk = clean_streaming_chunk(chunk)
                if cleaned_chunk:
                    full_response += cleaned_chunk
                    message_placeholder.markdown(full_response + "▌")

            full_response = clean_llm_response(full_response)
            message_placeholder.markdown(full_response)
            return full_response

        def run_streaming_query():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(run_query())
            finally:
                asyncio.set_event_loop(None)
                loop.close()

        def run_sync_fallback(error=None):
            if error is not None:
                stl.error(f"비동기 처리 실패: {error}")
            try:
                fallback = process_llm_query_simple(
                    user_query=user_input,
                    farm_id=farm_id,
                    house_id=house_id,
                    farm_name=farm_name,
                    house_name=house_name
                )
                fallback = clean_llm_response(fallback)
            except Exception as fallback_error:
                fallback = f"응답 생성 중 오류가 발생했습니다: {str(fallback_error)}"
            message_placeholder.markdown(fallback)
            return fallback

        try:
            result = run_streaming_query()
        except Exception as async_error:
            result = run_sync_fallback(async_error)

        return result

    except Exception as e:
        error_msg = f"모듈 처리 중 오류가 발생했습니다: {str(e)}"
        stl.error(error_msg)
        stl.error(traceback.format_exc())
        return error_msg
