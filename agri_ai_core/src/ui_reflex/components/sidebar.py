# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 사이드바 컴포넌트
# 농장/재배사 선택 및 설정
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import reflex as rx
from ..state import ChatState
from ..styles import (
    SIDEBAR_STYLE,
    FARM_HOUSE_SELECT_STYLE,
    WEATHER_SELECT_STYLE,
    BUTTON_SECONDARY,
)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 도시 목록 (위치 정보)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
AVAILABLE_CITIES = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "수원", "전주", "정읍", "청주", "천안", "포항", "창원", "제주"
]


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 사이드바 컴포넌트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def sidebar() -> rx.Component:
    """
    사이드바 렌더링

    Returns:
        rx.Component: 사이드바 컴포넌트
    """
    return rx.box(
        # 헤더
        rx.heading(
            "🍄 자연들에",
            size="6",
            color="#1B5E20",
            margin_bottom="8px",
        ),
        rx.text(
            "스마트팜 AI 관리",
            font_size="13px",
            color="#6c757d",
            margin_bottom="24px",
        ),

        rx.divider(margin="12px 0"),

        # 농장 선택
        rx.box(
            rx.text(
                "농장 선택",
                font_weight="600",
                font_size="14px",
                margin_bottom="8px",
            ),
            rx.select(
                ChatState.farm_option_labels,
                value=ChatState.selected_farm_label,
                on_change=ChatState.select_farm,
                placeholder="농장을 선택하세요",
                class_name="farm-house-select",
                custom_attrs={"data-select-kind": "farm-house"},
                **FARM_HOUSE_SELECT_STYLE,
            ),
            margin_bottom="20px",
        ),

        # 재배사 선택
        rx.box(
            rx.text(
                "재배사 선택",
                font_weight="600",
                font_size="14px",
                margin_bottom="8px",
            ),
            rx.select(
                ChatState.house_option_labels,
                value=ChatState.selected_house_label,
                on_change=ChatState.select_house,
                placeholder="재배사를 선택하세요",
                class_name="farm-house-select",
                custom_attrs={"data-select-kind": "farm-house"},
                **FARM_HOUSE_SELECT_STYLE,
            ),
            margin_bottom="20px",
        ),

        # 현재 선택 정보
        rx.box(
            rx.text(
                "현재 선택",
                font_weight="600",
                font_size="13px",
                margin_bottom="8px",
                color="#495057",
            ),
            rx.box(
                rx.text(
                    f"농장: {ChatState.farm_name}",
                    font_size="13px",
                    color="#212529",
                ),
                rx.text(
                    f"재배사: {ChatState.house_name}",
                    font_size="13px",
                    color="#212529",
                ),
                background_color="#E3F2FD",
                padding="12px",
                border_radius="6px",
                border_left="3px solid #2196F3",
            ),
            margin_bottom="20px",
        ),

        rx.divider(margin="12px 0"),

        # 날씨 위치 설정
        rx.box(
            rx.text(
                "🌍 날씨 지역",
                font_weight="600",
                font_size="14px",
                margin_bottom="8px",
            ),
            rx.select(
                AVAILABLE_CITIES,
                value=ChatState.weather_city,
                on_change=ChatState.set_weather_city,
                placeholder="지역을 선택하세요",
                class_name="weather-select",
                custom_attrs={"data-select-kind": "weather"},
                **WEATHER_SELECT_STYLE,
            ),
            rx.box(
                rx.text(
                    f"📍 {ChatState.weather_city}",
                    font_size="13px",
                    color="#4CAF50",
                ),
                background_color="#E8F5E9",
                padding="8px",
                border_radius="6px",
                margin_top="8px",
            ),
            margin_bottom="20px",
        ),

        rx.divider(margin="12px 0"),

        # 대화 초기화 버튼
        rx.button(
            "🗑️ 대화 기록 삭제",
            on_click=ChatState.clear_messages,
            width="100%",
            **BUTTON_SECONDARY,
        ),

        **SIDEBAR_STYLE,
    )
