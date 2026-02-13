# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex UI 스타일 상수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 색상 팔레트
COLORS = {
    "primary": "#0D47A1",
    "primary_dark": "#08306B",
    "primary_light": "#E3F2FD",
    "success": "#4CAF50",
    "success_light": "#E8F5E9",
    "background": "#FFFFFF",
    "text": "#212529",
    "text_secondary": "#6c757d",
    "border": "#E0E0E0",
    "hover": "#BBDEFB",
}

# 기본 스타일
BASE_STYLE = {
    "font_family": "'Noto Sans KR', sans-serif",
    "font_size": "14px",
    "line_height": "1.5",
}

# 채팅 버블 스타일
CHAT_BUBBLE_USER = {
    "background_color": COLORS["success_light"],
    "border": f"2px solid {COLORS['primary']}",
    "border_radius": "10px",
    "padding": "0 16px",
    "margin": "8px 0",
    "max_width": "75%",
    "align_self": "flex-end",
    "color": "#000000",
}

CHAT_BUBBLE_ASSISTANT = {
    "background_color": COLORS["primary_light"],
    "border": f"2px solid {COLORS['primary']}",
    "border_radius": "10px",
    "padding": "0 16px",
    "margin": "8px 0",
    "max_width": "75%",
    "align_self": "flex-start",
    "color": "#000000",
}

# 입력창 스타일
INPUT_STYLE = {
    "border": f"2px solid {COLORS['primary']}",
    "border_radius": "8px",
    "padding": "12px 16px",
    "font_size": "14px",
    "width": "100%",
    "background_color": "#E5E7EB",
    "color": "#000000",
    "_placeholder": {
        "color": "#4B5563",
    },
    "_focus": {
        "border_color": COLORS["primary_dark"],
        "box_shadow": f"0 2px 8px rgba(33, 150, 243, 0.3)",
    }
}

# 버튼 스타일
BUTTON_PRIMARY = {
    "background_color": COLORS["primary"],
    "color": "white",
    "border_radius": "8px",
    "padding": "12px 24px",
    "font_weight": "600",
    "cursor": "pointer",
    "_hover": {
        "background_color": COLORS["primary_dark"],
    }
}

BUTTON_SECONDARY = {
    "background_color": "#0D47A1",
    "color": "white",
    "border_radius": "6px",
    "padding": "8px 16px",
    "font_size": "13px",
    "cursor": "pointer",
    "_hover": {
        "background_color": "#08306B",
    }
}

# 파일 첨부 스타일
FILE_ATTACHMENT_STYLE = {
    "background_color": COLORS["primary_light"],
    "border_left": f"3px solid {COLORS['primary']}",
    "border_radius": "4px",
    "padding": "8px 12px",
    "margin": "4px 0",
    "font_size": "13px",
}

# 사이드바 스타일
SIDEBAR_STYLE = {
    "width": "280px",
    "height": "100vh",
    "background_color": "#F8F9FA",
    "border_right": f"1px solid {COLORS['border']}",
    "padding": "20px",
    "overflow_y": "auto",
}

# 메인 컨텐츠 스타일
MAIN_CONTENT_STYLE = {
    "flex": "1",
    "display": "flex",
    "flex_direction": "column",
    "height": "100vh",
    "background_color": COLORS["background"],
}

# 채팅 컨테이너 스타일
CHAT_CONTAINER_STYLE = {
    "flex": "1",
    "overflow_y": "auto",
    "min_height": "0",
    "padding": "20px",
    "display": "flex",
    "flex_direction": "column",
    "justify_content": "flex-start",
}

# 입력 영역 스타일
INPUT_AREA_STYLE = {
    "padding": "8px 20px",
    "border_top": f"1px solid {COLORS['border']}",
    "background_color": COLORS["background"],
}

# 헤더 스타일
HEADER_STYLE = {
    "text_align": "center",
    "padding": "16px 0",
    "background_color": COLORS["primary_light"],
    "border_radius": "8px",
    "margin_bottom": "20px",
}

# Select 스타일 (농장/재배사: 선택값 녹색)
FARM_HOUSE_SELECT_STYLE = {
    "border": f"1px solid {COLORS['border']}",
    "border_radius": "6px",
    "padding": "8px 12px",
    "font_size": "14px",
    "width": "100%",
    "margin": "8px 0",
    "color": "#000000",
    "font_weight": "700",
    "background_color": "#D1D5DB",
}

# Select 스타일 (날씨 지역: 검정 글자)
WEATHER_SELECT_STYLE = {
    "border": f"1px solid {COLORS['border']}",
    "border_radius": "6px",
    "padding": "8px 12px",
    "font_size": "14px",
    "width": "100%",
    "margin": "8px 0",
    "color": "#000000",
    "font_weight": "500",
    "background_color": "#D1D5DB",
}

# 하위 호환용 별칭
SELECT_STYLE = FARM_HOUSE_SELECT_STYLE
