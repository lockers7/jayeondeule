# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 메인 애플리케이션
# 앱 구조 및 페이지 정의
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import reflex as rx
from .state import ChatState
from .components import chat_history, chat_input_area, file_upload_area, sidebar
from .styles import MAIN_CONTENT_STYLE, HEADER_STYLE


def rag_action_button(label: str, action: str, on_click_event) -> rx.Component:
    """RAG 액션 버튼: 텍스트는 항상 유지, 실행 중일 때만 spinner 표시."""
    is_active = ChatState.rag_processing & (ChatState.rag_active_action == action)
    return rx.button(
        rx.hstack(
            rx.cond(
                is_active,
                rx.spinner(size="1"),
                rx.box(width="12px", height="12px"),
            ),
            rx.text(label, font_size="12px"),
            spacing="1",
            align="center",
            justify="center",
        ),
        on_click=on_click_event,
        size="1",
        variant="surface",
        color_scheme="gray",
        cursor="pointer",
        min_width="88px",
        class_name="rag-action-button",
    )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 메인 페이지
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def index() -> rx.Component:
    """
    메인 페이지 렌더링

    Returns:
        rx.Component: 전체 페이지 레이아웃
    """
    return rx.hstack(
        # 왼쪽 사이드바
        sidebar(),

        # 오른쪽 메인 컨텐츠
        rx.box(
            # 상단 1라인: 제목 + RAG 버튼
            rx.box(
                rx.box(
                    rx.heading(
                        "🍄 자연들에 상황버섯 AI",
                        size="7",
                        color="#1B5E20",
                        margin="0",
                        position="absolute",
                        left="50%",
                        top="50%",
                        transform="translate(-50%, -50%)",
                        white_space="nowrap",
                        pointer_events="none",
                        z_index="1",
                    ),
                    rx.hstack(
                        rag_action_button("RAG수행", "perform", ChatState.trigger_perform_rag),
                        rag_action_button("RAG저장", "save", ChatState.trigger_save_rag),
                        spacing="2",
                        align="center",
                        justify="end",
                        position="relative",
                        z_index="2",
                    ),
                    width="100%",
                    min_height="44px",
                    position="relative",
                    display="flex",
                    align_items="center",
                    justify_content="flex-end",
                ),
                # 두 번째 줄: 부제목
                rx.text(
                    "스마트팜 관리 및 재배 상담 서비스",
                    font_size="13px",
                    color="#616161",
                    font_weight="700",
                    margin_top="4px",
                    margin_left="2px",
                ),
                **HEADER_STYLE,
            ),

            # 채팅 히스토리
            chat_history(),

            # 입력 영역
            chat_input_area(),

            # 파일 업로드 영역 (입력창 아래)
            file_upload_area(),

            **MAIN_CONTENT_STYLE,
        ),

        spacing="0",
        padding="0",
        width="100%",
        height="100vh",
    )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 앱 생성 및 설정
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# "Built with Reflex" 푸터 제거를 위한 커스텀 스타일
custom_style = {
    "footer": {
        "display": "none",
    },
    "a[href*='reflex.dev']": {
        "display": "none !important",
    },
}

app = rx.App(
    style=custom_style,
    stylesheets=[
        "/custom.css",  # 커스텀 CSS로 Reflex 푸터 완전 제거
    ],
)
app.add_page(
    index,
    title="자연들에 상황버섯 AI",
    description="스마트팜 관리 및 재배 상담 서비스",
    on_load=ChatState.on_load,
)
