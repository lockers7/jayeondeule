# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PostgreSQL 데이터 수집 모듈
# PostgreSQL에서 센서 데이터, 제어 이력 등을 읽어와
# 분석 및 학습에 활용할 수 있도록 추출합니다.
# --->
# read_farm_house_list: 농장-재배사 목록 조회
# read_units_data: Units 데이터 조회
# read_crops_data: Crops 데이터 조회
# read_current_growth_stage: 현재 생육단계 조회
# read_farm_info: 농장 정보 조회
# read_optimal_condition: 최적 조건 조회
# read_current_sensor_info: 현재 센서 정보 조회
# read_latest_relay_info: 릴레이 정보 조회
# read_light_irrigation_settings: 조명/관수밸브 설정 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# DB 조회 공통 래퍼 (fetch_all / fetch_one 통합)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _db_query(query, vals=(), *, fetch="all", error_msg="DB 조회", default=None):
    with db_session() as database:
        try:
            if fetch == "one":
                return database.fetch_one(query=query, vals=vals)
            return database.fetch_all(query=query, vals=vals, as_dict=True)
        except Exception as e:
            logger.warning(f"{error_msg}: {e}")
            return default


def read_farm_house_list():
    return _db_query(dbQry.GET_FARM_HOUSE_LIST, error_msg="농장-재배사 목록 조회", default=[])


def read_units_data(farm_id, house_id):
    return _db_query(dbQry.GET_UNITS_VALUE, (farm_id, int(house_id)),
                     error_msg=f"Units 조회 farm={farm_id} house={house_id}", default=[])


def read_crops_data(farm_id, house_id):
    return _db_query(dbQry.GET_CROPS_VALUE, (farm_id, int(house_id)),
                     error_msg=f"Crops 조회 farm={farm_id} house={house_id}", default=[])


def read_current_growth_stage(farm_id, house_id):
    result = _db_query(dbQry.GET_CURRENT_CROP_LVEL, (farm_id, int(house_id)),
                       fetch="one", error_msg=f"생육단계 조회 farm={farm_id} house={house_id}")
    return result.get("생육단계") if result else None


def read_farm_info():
    return _db_query(dbQry.GET_FARM_INFO_LIST, error_msg="농장 정보 조회", default=[])


def read_optimal_condition(farm_id, house_id):
    return _db_query(dbQry.GET_OPTIMAL_CONDITION, (farm_id, house_id),
                     fetch="one", error_msg=f"최적조건 조회 farm={farm_id} house={house_id}")


def read_current_sensor_info(farm_id, house_id):
    return _db_query(dbQry.GET_NOW_UNIT_INFO, (farm_id, house_id),
                     fetch="one", error_msg=f"센서정보 조회 farm={farm_id} house={house_id}")


def read_latest_relay_info(farm_id, house_id):
    return _db_query(dbQry.GET_LATEST_RELAY_INFO, (farm_id, house_id),
                     fetch="one", error_msg=f"릴레이정보 조회 farm={farm_id} house={house_id}")


def read_light_irrigation_settings(farm_id, house_id, unit_type):
    return _db_query(dbQry.GET_LIGHT_IRRIGATION, (farm_id, house_id, unit_type.lower()),
                     error_msg=f"{unit_type} 설정 조회 farm={farm_id} house={house_id}", default=[])


