# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Streamlit 메인 애플리케이션 모듈
# Streamlit 기반 웹 UI의 메인 진입점이며,
# 페이지 레이아웃과 전체 앱 구조를 정의합니다.
# --->
# setup_page: 페이지 초기 설정
# main: 메인 애플리케이션 실행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
import streamlit as stl

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.ai.llm_client import initialize_background_warmup

from agri_ai_core.src.ui.styles import CHAT_STYLES, PAGE_TITLE_HTML, FILE_ATTACHMENT_TEMPLATE
from agri_ai_core.src.ui.session_manager import (
    initialize_session_state,
    get_default_farm_info,
    add_user_message,
    add_assistant_message
)
from agri_ai_core.src.ui.file_handler import (
    handle_file_upload,
    display_uploaded_files
)
from agri_ai_core.src.ui.location_handler import (
    ensure_ip_location_set,
    auto_detect_user_location,
    process_location_from_params
)
from agri_ai_core.src.ui.chat_handler import (
    display_chat_history,
    process_message_with_modules
)
from agri_ai_core.src.ui.sidebar import render_sidebar

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 페이지 설정 및 스타일 적용
# --->
# 페이지 초기 설정
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def setup_page():
    stl.set_page_config(page_title="자연들에 상황버섯 AI", layout="wide")

    stl.cache_data.clear()
    stl.cache_resource.clear()

    stl.markdown(CHAT_STYLES, unsafe_allow_html=True)
    stl.markdown(PAGE_TITLE_HTML, unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 메인 애플리케이션
# --->
# 메인 애플리케이션 실행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def main():
    try:
        # 페이지 설정
        setup_page()

        # 세션 상태 초기화
        initialize_session_state()

        # 위치 처리
        if not process_location_from_params():
            ensure_ip_location_set()
        auto_detect_user_location()

        # 기본 농장 정보 로드
        get_default_farm_info()

        # LLM 워밍업
        initialize_background_warmup(
            stl.session_state.farm_id,
            stl.session_state.house_id,
            stl.session_state.farm_name,
            stl.session_state.house_name
        )

        # 레이아웃 구성
        left_col, right_col = stl.columns([2, 8])

        # 사이드바 (왼쪽 컬럼)
        with left_col:
            farm_id, house_id, farm_name, house_name = render_sidebar()

        # 메인 채팅 영역 (오른쪽 컬럼)
        with right_col:
            # ===== 최상단 고정 영역 =====
            # 1. 채팅 입력창 (최상단)
            farm_prompt = f"[{farm_name}] 농장입니다." if farm_name else "상황버섯 자연들에"
            user_input = stl.chat_input(
                f"💬 {farm_prompt} 무엇을 도와 드릴까요?"
            )

            # 2. 파일 첨부 영역 (입력창 바로 아래, 간격 없음)
            stl.markdown("<div class='file-upload-container' style='padding:6px 12px;'>", unsafe_allow_html=True)
            handle_file_upload()
            if stl.session_state.uploaded_files:
                stl.markdown(f"<div style='color:#6c757d; font-size:11px; margin:4px 0;'>📎 {len(stl.session_state.uploaded_files)}개 파일</div>", unsafe_allow_html=True)
            stl.markdown("</div>", unsafe_allow_html=True)

            # 3. 구분선
            stl.markdown("---")
            stl.markdown("<p style='font-size:13px; font-weight:600; margin:0; padding:3px 0; line-height:1.3; color:#495057;'>💬 대화 기록 (최신순)</p>", unsafe_allow_html=True)

            # ===== 채팅 히스토리 영역 =====
            # 4. 채팅 기록 표시 (역순 - 최신 것이 상단)
            display_chat_history(reverse=True)

            # ===== 사용자 입력 처리 =====
            if user_input and user_input.strip() != "":
                current_files = stl.session_state.uploaded_files.copy()

                # 사용자 메시지 추가
                user_message = {
                    "role": "user",
                    "content": user_input,
                    "files": current_files
                }

                stl.session_state.messages.append(user_message)

                # 사용자 메시지 표시
                with stl.chat_message("user"):
                    stl.markdown(user_input)
                    if current_files:
                        for file in current_files:
                            stl.markdown(
                                FILE_ATTACHMENT_TEMPLATE.format(filename=file["name"]),
                                unsafe_allow_html=True
                            )

                # 어시스턴트 응답
                with stl.chat_message("assistant"):
                    try:
                        bot_response = process_message_with_modules(
                            user_input,
                            current_files,
                            farm_id=farm_id,
                            house_id=house_id,
                            farm_name=farm_name,
                            house_name=house_name
                        )

                        # 어시스턴트 메시지 저장
                        bot_message = {"role": "assistant", "content": bot_response}
                        stl.session_state.messages.append(bot_message)

                    except Exception as e:
                        stl.error(f"메시지 전송 중 오류: {str(e)}")
                        stl.error(traceback.format_exc())

    except Exception as e:
        stl.error(f"애플리케이션 실행 중 오류 발생: {str(e)}")
        stl.error(traceback.format_exc())


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 실행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
