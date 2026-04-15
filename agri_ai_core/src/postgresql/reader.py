# ══════════════════════════════════════════════════════════════
# PostgreSQL 데이터 조회 계층 (read-only)
# 농장/재배사/센서/릴레이/생육단계/최적조건 등 운영 데이터를 조회한다.
# 모든 함수는 예외를 잡아 로그 기록 후 default 값을 반환한다.
# --->
# _db_query: fetch_all/fetch_one 공통 래퍼 (예외 안전)
# read_farm_house_list: 전체 농장-재배사 목록 조회
# read_units_data: 특정 재배사의 센서 최신값 목록
# read_crops_data: 특정 재배사의 작물/생육 설정 목록
# read_current_growth_stage: 현재 생육단계 단일값 조회
# read_farm_info: 전체 농장 기본정보 목록
# read_optimal_condition: 재배사 현재 생육단계의 최적 환경조건
# read_current_sensor_info: 재배사 최신 센서값 한 건
# read_latest_relay_info: 재배사 최근 릴레이 상태 한 건
# read_light_irrigation_settings: 조명/관수 스케줄 설정
# ══════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
# queries를 직접 import (postgresql/__init__.py 경유 방지 → 순환 참조 해소)
import agri_ai_core.src.postgresql.queries as dbQry

logger = setup_logger(__name__)


# ══════════════════════════════════════════════
# DB 조회 공통 래퍼 (fetch_all / fetch_one 통합)
# ══════════════════════════════════════════════
def _db_query(query, vals=(), *, fetch="all", error_msg="DB 조회", default=None):
    """DB 조회 공통 래퍼. fetch='all' → list[dict], fetch='one' → dict|None."""
    with db_session() as database:
        try:
            if fetch == "one":
                return database.fetch_one(query=query, vals=vals)
            return database.fetch_all(query=query, vals=vals, as_dict=True)
        except Exception as e:
            logger.error(f"{error_msg}: {e}")
            return default


def read_farm_house_list():
    """전체 농장과 재배사 매핑 목록을 반환한다."""
    return _db_query(dbQry.GET_FARM_HOUSE_LIST, error_msg="농장-재배사 목록 조회", default=[])


def read_units_data(farm_id, house_id):
    """특정 재배사의 센서별 최신값 목록(Units) 조회."""
    return _db_query(dbQry.GET_UNITS_VALUE, (farm_id, int(house_id)),
                     error_msg=f"Units 조회 farm={farm_id} house={house_id}", default=[])


def read_crops_data(farm_id, house_id):
    """특정 재배사의 작물/생육 설정 목록(Crops) 조회."""
    return _db_query(dbQry.GET_CROPS_VALUE, (farm_id, int(house_id)),
                     error_msg=f"Crops 조회 farm={farm_id} house={house_id}", default=[])


def read_current_growth_stage(farm_id, house_id):
    """해당 재배사의 현재 생육단계 명칭만 반환한다 (없으면 None)."""
    result = _db_query(dbQry.GET_CURRENT_CROP_LVEL, (farm_id, int(house_id)),
                       fetch="one", error_msg=f"생육단계 조회 farm={farm_id} house={house_id}")
    return result.get("생육단계") if result else None


def read_farm_info():
    """전체 농장 기본정보(이름/주소/비고 등) 목록 반환."""
    return _db_query(dbQry.GET_FARM_INFO_LIST, error_msg="농장 정보 조회", default=[])


def read_optimal_condition(farm_id, house_id):
    """재배사 현재 생육단계의 최적 환경조건(온/습/CO₂ 등) 한 건 반환."""
    return _db_query(dbQry.GET_OPTIMAL_CONDITION, (farm_id, house_id),
                     fetch="one", error_msg=f"최적조건 조회 farm={farm_id} house={house_id}")


def read_current_sensor_info(farm_id, house_id):
    """재배사의 최신 센서값(온/습/CO₂/수온/조도 등) 한 건 반환."""
    return _db_query(dbQry.GET_NOW_UNIT_INFO, (farm_id, house_id),
                     fetch="one", error_msg=f"센서정보 조회 farm={farm_id} house={house_id}")


def read_latest_relay_info(farm_id, house_id):
    """재배사의 최근 릴레이(팬/히터/조명/관수 등) ON/OFF 상태 반환."""
    return _db_query(dbQry.GET_LATEST_RELAY_INFO, (farm_id, house_id),
                     fetch="one", error_msg=f"릴레이정보 조회 farm={farm_id} house={house_id}")


def read_light_irrigation_settings(farm_id, house_id, unit_type):
    """조명/관수 자동 제어 스케줄 설정 목록 반환.
    unit_type: 'light' | 'irrigation'."""
    return _db_query(dbQry.GET_LIGHT_IRRIGATION, (farm_id, house_id, unit_type.lower()),
                     error_msg=f"{unit_type} 설정 조회 farm={farm_id} house={house_id}", default=[])


