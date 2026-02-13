# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 파일 업로드 컴포넌트
# 파일 첨부 및 관리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import reflex as rx
from ..state import ChatState
from ..styles import BUTTON_SECONDARY


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 파일 업로드 영역 컴포넌트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def file_upload_area() -> rx.Component:
    """
    파일 업로드 영역 렌더링

    Returns:
        rx.Component: 파일 업로드 컴포넌트
    """
    return rx.box(
        # 파일 업로드 버튼
        rx.box(
            rx.upload(
                rx.button(
                    "📎 파일 첨부",
                    **BUTTON_SECONDARY,
                ),
                id="file_upload",
                multiple=True,
                accept={
                    "text/csv": [".csv"],
                    "application/vnd.ms-excel": [".xls", ".xlsx"],
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
                    "image/*": [".jpg", ".jpeg", ".png"],
                    "application/pdf": [".pdf"],
                    "text/plain": [".txt"],
                },
                on_drop=ChatState.handle_file_upload,
                class_name="compact-upload",
                border="none",
                padding="0",
                text_align="center",
            ),
            width="100%",
            display="flex",
            justify_content="center",
        ),

        # 업로드된 파일 목록
        rx.cond(
            ChatState.uploaded_files,
            rx.box(
                rx.vstack(
                    rx.foreach(
                        ChatState.uploaded_files,
                        lambda file, idx: rx.hstack(
                            rx.text(
                                f"📎 {file['name']} ({file['size'] / 1024:.1f} KB)",
                                font_size="13px",
                                color="#1976D2",
                                flex="1",
                            ),
                            rx.text(
                                file["upload_time"],
                                font_size="11px",
                                color="#6c757d",
                            ),
                            rx.button(
                                "삭제",
                                on_click=lambda: ChatState.remove_file(idx),
                                size="1",
                                color_scheme="red",
                                font_size="11px",
                                padding="4px 8px",
                            ),
                            spacing="3",
                            width="100%",
                            padding="4px 12px",
                            border_bottom="1px solid #e9ecef",
                        ),
                    ),
                    spacing="0",
                    width="100%",
                ),
                background_color="#E3F2FD",
                border="1px solid #BBDEFB",
                border_radius="6px",
                margin_top="4px",
                padding="4px",
            ),
            rx.box(),  # 파일이 없을 때는 빈 박스
        ),

        class_name="file-upload-area",
        padding="4px 20px 6px 20px",
        background_color="#FFFFFF",
    )
