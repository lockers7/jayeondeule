# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Streamlit 채팅 핸들러 모듈
# 채팅 인터페이스의 메시지 표시, 입력 처리, 세션 관리 등
# UI 레벨의 채팅 기능을 구현합니다.
# --->
# display_chat_history: 채팅 기록 표시
# process_message_with_modules: 모듈 직접 호출을 통한 메시지 처리
# send_streaming_message_with_files: 서버 API를 통한 스트리밍 메시지 처리
# safe_json: 기능 설명 필요
# run_query: 기능 설명 필요
# run_streaming_query: 기능 설명 필요
# run_sync_fallback: 기능 설명 필요
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import re
import json
import base64
import decimal
import asyncio
import requests
import traceback
import streamlit as stl

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.shared_modules.config.settings import settings
from agri_ai_core.llm.qa.query_handler import query_llm_unified, process_llm_query_simple
from agri_ai_core.llm.core.llm_client import clean_llm_response, clean_streaming_chunk

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 대화 기록 표시
# --->
# 채팅 기록 표시
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def display_chat_history():
    for message in stl.session_state.messages:
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 서버 API를 통한 메시지 처리 (백업용)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def send_streaming_message_with_files(
    user_input: str,
    uploaded_files: list,
    farm_id: int = None,
    house_id: int = None,
    farm_name: str = None,
    house_name: str = None
) -> str:
    """
    서버 API를 통한 스트리밍 메시지 처리

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
    def safe_json(obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        raise TypeError(f"Type {type(obj)} not serializable")

    api_urls = [
        "http://localhost:8088",
        "http://127.0.0.1:8088",
        settings.fastapi_url or "http://localhost:8088"
    ]

    request_data = {
        "user_input": user_input,
        "farm_id": farm_id,
        "house_id": house_id,
        "farm_name": farm_name,
        "house_name": house_name
    }

    if uploaded_files:
        file_info_list = []
        for file in uploaded_files:
            import os
            if not os.path.exists(file["path"]):
                stl.warning(f"파일을 찾을 수 없습니다: {file['name']}")
                continue

            try:
                with open(file["path"], "rb") as f:
                    file_content = base64.b64encode(f.read()).decode('utf-8')

                file_info = {
                    "filename": file["name"],
                    "content": file_content,
                    "content_type": file["type"]
                }
                file_info_list.append(file_info)
            except Exception as e:
                stl.warning(f"파일 '{file['name']}' 처리 중 오류: {str(e)}")

        if file_info_list:
            request_data["files"] = file_info_list

    message_placeholder = stl.empty()
    message_placeholder.markdown("응답을 생성 중입니다...")

    serialized_request_data = json.loads(json.dumps(request_data, default=safe_json))

    with requests.Session() as session:
        for api_url in api_urls:
            try:
                full_response = ""
                inside_think_tag = False
                accumulated_text = ""

                with session.post(
                    f"{api_url}/chat_streaming",
                    json=serialized_request_data,
                    stream=True,
                    headers={"Accept": "text/event-stream"},
                    timeout=30
                ) as response:

                    if response.status_code != 200:
                        continue

                    for line in response.iter_lines():
                        if not line or not line.startswith(b'data: '):
                            continue

                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        data_type = data.get("type")
                        if data_type == "start":
                            continue
                        if data_type == "content":
                            chunk = data.get("chunk", "")

                            # 누적 텍스트에 추가
                            accumulated_text += chunk

                            # think 태그 감지
                            lower_text = accumulated_text.lower()
                            if '<think>' in lower_text:
                                inside_think_tag = True

                            if inside_think_tag:
                                # think 태그 종료 감지
                                if '</think>' in lower_text:
                                    # think 태그 전체 제거
                                    accumulated_text = re.sub(
                                        r'<think>.*?</think>', '',
                                        accumulated_text,
                                        flags=re.DOTALL | re.IGNORECASE
                                    )
                                    inside_think_tag = False
                                    if accumulated_text.strip():
                                        full_response += accumulated_text
                                        message_placeholder.markdown(full_response + "▌")
                                        accumulated_text = ""
                                continue
                            else:
                                cleaned_chunk = clean_streaming_chunk(chunk)
                                if cleaned_chunk:
                                    full_response += cleaned_chunk
                                    message_placeholder.markdown(full_response + "▌")
                            continue

                        if data_type == "end":
                            full_response = clean_llm_response(full_response)
                            message_placeholder.markdown(full_response)
                            return full_response

                        if data_type == "error":
                            error_msg = data.get("error", "알 수 없는 오류가 발생했습니다.")
                            message_placeholder.error(error_msg)
                            return error_msg

                full_response = clean_llm_response(full_response)
                return full_response

            except requests.exceptions.ConnectionError:
                continue
            except Exception as e:
                stl.warning(f"API 요청 실패 ({api_url}): {str(e)}")
                continue

    error_msg = "FastAPI 서버에 연결할 수 없습니다."
    message_placeholder.error(error_msg)
    return error_msg
