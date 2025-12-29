# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Streamlit 사이드바 모듈
# 농장/재배사 선택, 설정 변경 등 사이드바 UI 컴포넌트를
# 구성하고 관리합니다.
# --->
# farm_house_selection_sidebar: 농장 및 재배사 선택 사이드바 UI
# weather_location_sidebar: 날씨 위치 설정 UI
# render_sidebar: 전체 사이드바 렌더링
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import streamlit as stl

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.database.postgres.connection import db_session
from agri_ai_core.database.postgres import queries as db_queries
from agri_ai_core.ui.streamlit_app.location_handler import (
    get_available_cities,
    get_current_weather_city,
    set_weather_city
)

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 및 재배사 선택 사이드바
# --->
# 농장 및 재배사 선택 사이드바 UI
# Returns:
# tuple: (farm_id, house_id, farm_name, house_name)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def farm_house_selection_sidebar():
    farm_id = None
    house_id = None
    farm_name = "농장없음"
    house_name = "재배사없음"

    try:
        query_params = stl.query_params
        farm_id_param = query_params.get("farm_id", None)
        farm_id = int(farm_id_param) if farm_id_param else None

        with db_session() as database:
            if farm_id:
                farms = database.fetch_all(
                    query=db_queries.GET_FARM_NAME,
                    vals=(farm_id, farm_id),
                    as_dict=True
                )
                show_all = False
            else:
                farms = database.fetch_all(
                    query=db_queries.GET_FARM_NAME,
                    vals=(None, None),
                    as_dict=True
                )
                show_all = True

        if not farms:
            stl.warning("농장 정보가 없습니다.")
            return 1, 1, farm_name, house_name

        farm_options = [(f["farm_id"], f["farm_name"]) for f in farms]
        farm_names = [f"{name} ({fid})" for fid, name in farm_options]

        selected_farm_idx = stl.selectbox(
            "농장 선택",
            options=range(len(farm_options)),
            format_func=lambda i: farm_names[i],
            index=0
        )
        farm_id, farm_name = farm_options[selected_farm_idx]

        with db_session() as database:
            houses = database.fetch_all(
                query=db_queries.GET_FARM_HOUSE_LIST,
                vals=(farm_id, house_id, house_id),
                as_dict=True
            )

        if not houses:
            stl.warning(f"{farm_name}에 재배사가 없습니다.")
            return farm_id, 1, farm_name, house_name

        house_options = [(h["hous_id"], h["hous_name"]) for h in houses]
        house_names = [f"{name} ({hid})" for hid, name in house_options]

        selected_house_idx = stl.selectbox(
            "재배사 선택",
            options=range(len(house_options)),
            format_func=lambda i: house_names[i],
            index=0
        )
        house_id, house_name = house_options[selected_house_idx]

        stl.info(f" 현재 농장: **{farm_name}** / 재배사: **{house_name}**")
        if show_all:
            stl.caption(" 전체 농장 목록에서 선택됨")
        else:
            stl.caption(" URL로 지정된 농장만 표시됨")

        return farm_id, house_id, farm_name, house_name

    except Exception as e:
        stl.error(" 예외 발생")
        stl.exception(e)
        return 1, 1, farm_name, house_name


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 날씨 위치 설정 사이드바
# --->
# 날씨 위치 설정 UI
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def weather_location_sidebar():
    stl.markdown("---")
    stl.markdown("🌍 **현재 날씨 지역**")

    city = get_current_weather_city()

    # 위치 출처 표시
    if stl.session_state.get('client_location_applied', False):
        stl.success(f"📍 {city} (브라우저 위치)")
    elif stl.session_state.get('ip_location_detected', False):
        stl.success(f"📍 {city} (IP 추정)")
    elif stl.session_state.get('user_location_detected', False):
        stl.success(f"📍 {city}")
    else:
        stl.info(f"📍 {city} (기본값)")

    # 지역 변경 확장 패널
    with stl.expander("🔧 지역 변경", expanded=False):
        cities = get_available_cities()

        # 현재 도시 인덱스 찾기
        current_idx = 0
        if city in cities:
            current_idx = cities.index(city)

        new_city = stl.selectbox(
            "지역 선택:",
            cities,
            index=current_idx,
            key="city_selectbox"
        )

        if new_city != city:
            set_weather_city(new_city)
            stl.rerun()


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 전체 사이드바 구성
# --->
# 전체 사이드바 렌더링
# Returns:
# tuple: (farm_id, house_id, farm_name, house_name)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def render_sidebar():
    farm_id, house_id, farm_name, house_name = farm_house_selection_sidebar()
    weather_location_sidebar()

    return farm_id, house_id, farm_name, house_name
