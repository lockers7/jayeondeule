# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 채팅 입력 컴포넌트
# 사용자 입력 및 전송 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import reflex as rx
from ..state import ChatState
from ..styles import INPUT_STYLE, BUTTON_PRIMARY, INPUT_AREA_STYLE


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 채팅 입력 영역 컴포넌트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def chat_input_area() -> rx.Component:
    # 농장 정보 표시
    farm_prompt = rx.cond(
        ChatState.farm_name != "",
        rx.text(
            f" [{ChatState.farm_name}] 농장입니다. 💬 무엇을 도와 드릴까요?",
            font_size="13px",
            color="#000000",
            font_weight="700",
            margin_bottom="4px",
        ),
        rx.text(
            "💬 무엇을 도와 드릴까요?",
            font_size="13px",
            color="#000000",
            font_weight="700",
            margin_bottom="4px",
        )
    )

    return rx.box(
        # 농장 정보 프롬프트
        farm_prompt,

        # 입력창 + 전송 버튼 (Enter 전송, Shift+Enter 줄바꿈)
        rx.form(
            rx.hstack(
                rx.text_area(
                    placeholder="메시지를 입력하세요...",
                    value=ChatState.current_input,
                    on_change=ChatState.set_current_input,
                    enter_key_submit=True,
                    disabled=ChatState.input_locked,
                    class_name="chat-textarea",
                    rows="3",
                    resize="none",
                    height="64px",
                    min_height="64px",
                    max_height="64px",
                    overflow_y="hidden",
                    custom_attrs={"wrap": "off"},
                    line_height="20px",
                    **INPUT_STYLE,
                ),
                rx.vstack(
                    rx.box(
                        rx.cond(
                            ChatState.is_loading,
                            rx.text("🚴", class_name="running-bicycle"),
                            rx.box(),
                        ),
                        class_name="send-running-fixed-slot",
                    ),
                    rx.button(
                        rx.cond(
                            ChatState.is_loading,
                            rx.spinner(size="2"),
                            rx.text("전송"),
                        ),
                        type="button",
                        on_click=ChatState.handle_send_button_click,
                        class_name="send-button-raised",
                        **BUTTON_PRIMARY,
                    ),
                    class_name="send-button-column",
                    spacing="1",
                    align="center",
                    justify="start",
                ),
                align="start",
                spacing="3",
                width="100%",
            ),
            on_submit=ChatState.handle_form_submit,
            width="100%",
        ),
        **INPUT_AREA_STYLE,
    )
