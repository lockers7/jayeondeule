# ════════════════════════════════════════════════════════════════════
# PostgreSQL 데이터 조회 계층 (read-only).
# 농장/재배사/센서/릴레이/생육단계/최적조건 등 운영 데이터를 조회.
# 모든 함수는 예외를 잡아 로그 기록 후 default 값을 반환.
# --->
# _db_query                      : fetch_all/fetch_one 공통 래퍼 (예외 안전)
# read_farm_house_list           : 전체 농장-재배사 목록 조회
# read_units_data                : 특정 재배사의 센서 최신값 목록
# read_crops_data                : 특정 재배사의 작물/생육 설정 목록
# read_current_growth_stage      : 현재 생육단계 단일값 조회
# read_farm_info                 : 전체 농장 기본정보 목록
# read_optimal_condition         : 재배사 현재 생육단계의 최적 환경조건
# read_current_sensor_info       : 재배사 최신 센서값 한 건
# read_latest_relay_info         : 재배사 최근 릴레이 상태 한 건
# read_light_irrigation_settings : 조명/관수 스케줄 설정
# read_schedule_settings         : 통합 스케줄(SCHEDULE_M_SETTING) 전체 row 조회
# read_schedule_max_updt         : 통합 스케줄 최대 updt_dttm — 변경 감지용 polling key
# read_sensor_setting_max_updt   : 호기별 SENSOR_M_SETTING 최대 updt_dttm
# read_prompt_block_updt         : PROMPT_BLOCK_M 단건 updt_dttm (캐시 invalidate)
# read_tool_definition_max_updt  : TOOL_DEFINITION_M 활성행 최대 updt_dttm
# read_control_prompt_updt       : CONTROL_PROMPT_M 단건 updt_dttm (캐시 invalidate)
# ════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
# queries를 직접 import (postgresql/__init__.py 경유 방지 → 순환 참조 해소)
import agri_ai_core.src.postgresql.queries as dbQry
import os
import time

logger = setup_logger(__name__)

# 센서 결함값 WARNING 스로틀 — 필터(None 처리=안전)는 매 read 유지하되, 로깅만
# (farm,house,센서)별 간격으로 억제(기본 600초). 3호 수온계 상시 0℃ 같은 고정 결함이
# 로그의 99%(하루 7.4만건)를 차지하던 문제 해소. 상태변화(정상↔결함) 시엔 즉시 로깅.
_FAULT_LOG_LAST = {}                # (farm,house,key) -> (last_ts, last_bad)
_FAULT_LOG_INTERVAL = int(os.getenv("SENSOR_FAULT_LOG_INTERVAL_SEC", "600"))


# ────────────────────────────────────────────────────────────────────
# DB 조회 공통 래퍼 — fetch_all / fetch_one 통합 + 예외 안전.
# fetch='all' → list[dict], fetch='one' → dict|None.
# ────────────────────────────────────────────────────────────────────
def _db_query(query, vals=(), *, fetch="all", error_msg="DB 조회", default=None):
    with db_session() as database:
        try:
            if fetch == "one":
                return database.fetch_one(query=query, vals=vals)
            return database.fetch_all(query=query, vals=vals, as_dict=True)
        except Exception as e:
            logger.error(f"{error_msg}: {e}")
            return default


# ────────────────────────────────────────────────────────────────────
# 전체 농장-재배사 매핑 목록 반환.
# ────────────────────────────────────────────────────────────────────
def read_farm_house_list():
    return _db_query(dbQry.GET_FARM_HOUSE_LIST, error_msg="농장-재배사 목록 조회", default=[])


# ────────────────────────────────────────────────────────────────────
# 특정 재배사의 센서별 최신값 목록(Units) 조회.
# ────────────────────────────────────────────────────────────────────
def read_units_data(farm_id, house_id):
    return _db_query(dbQry.GET_UNITS_VALUE, (farm_id, int(house_id)),
                     error_msg=f"Units 조회 farm={farm_id} house={house_id}", default=[])


# ────────────────────────────────────────────────────────────────────
# 특정 재배사의 작물/생육 설정 목록(Crops) 조회.
# ────────────────────────────────────────────────────────────────────
def read_crops_data(farm_id, house_id):
    return _db_query(dbQry.GET_CROPS_VALUE, (farm_id, int(house_id)),
                     error_msg=f"Crops 조회 farm={farm_id} house={house_id}", default=[])


# ────────────────────────────────────────────────────────────────────
# 해당 재배사의 현재 생육단계 명칭만 반환 (없으면 None).
# ────────────────────────────────────────────────────────────────────
def read_current_growth_stage(farm_id, house_id):
    result = _db_query(dbQry.GET_CURRENT_CROP_LVEL, (farm_id, int(house_id)),
                       fetch="one", error_msg=f"생육단계 조회 farm={farm_id} house={house_id}")
    return result.get("생육단계") if result else None


# ────────────────────────────────────────────────────────────────────
# 전체 농장 기본정보(이름/주소/비고 등) 목록 반환.
# ────────────────────────────────────────────────────────────────────
def read_farm_info():
    return _db_query(dbQry.GET_FARM_INFO_LIST, error_msg="농장 정보 조회", default=[])


# ────────────────────────────────────────────────────────────────────
# 재배사 현재 생육단계의 최적 환경조건(온/습/CO₂ 등) 한 건 반환.
# ────────────────────────────────────────────────────────────────────
def read_optimal_condition(farm_id, house_id):
    return _db_query(dbQry.GET_OPTIMAL_CONDITION, (farm_id, house_id),
                     fetch="one", error_msg=f"최적조건 조회 farm={farm_id} house={house_id}")


# ────────────────────────────────────────────────────────────────────
# 재배사의 최신 센서값(온/습/CO₂/수온/조도 등) 한 건 반환.
# ────────────────────────────────────────────────────────────────────
def read_current_sensor_info(farm_id, house_id):
    row = _db_query(dbQry.GET_NOW_UNIT_INFO, (farm_id, house_id),
                    fetch="one", error_msg=f"센서정보 조회 farm={farm_id} house={house_id}")
    # 센서 결함값 필터.
    #   RPi 보드는 센서 읽기 실패 시 0.0 을 폴백 기록(raspi jayeondeule.py)하며,
    #   단선 시 -454℃ 같은 물리불가값도 기록된다. 이를 그대로 제어에 투입하면
    #   비상가드가 "실내 0.0℃ < 비상하한" 을 저온비상으로 오인해 수온히터를 강제
    #   ON 할 수 있으므로 결함값은 무효(None) 처리 — 비상가드/절대안전게이트/LLM
    #   모두 None 이면 해당 판단을 건너뛰므로(전부 is-not-None 가드) 안전 방향으로만
    #   작용한다.
    #   범위: 정확히 0.0(읽기실패 폴백) 또는 물리 범위 밖 → None.
    #   ※ 실외 0.0℃ 실측 가능성: 센서는 소수 3자리로 기록되므로 정확한 0.0 은
    #     사실상 폴백값. 오인해도 해당 tick 만 스킵되고 다음 정상값으로 복구.
    if isinstance(row, dict):
        _RULES = {
            'water_temperature':   (0.0, 100.0,    '수온',     '℃'),
            'indoor_temperature':  (-30.0, 80.0,   '실내온도', '℃'),
            'outdoor_temperature': (-30.0, 80.0,   '실외온도', '℃'),
            'indoor_humidity':     (0.0, 100.0001, '실내습도', '%'),
            'outdoor_humidity':    (0.0, 100.0001, '실외습도', '%'),
            'co2':                 (0.0, 10000.0,  'CO2',      'ppm'),
        }
        for _key, (_lo, _hi, _label, _unit) in _RULES.items():
            _v = row.get(_key)
            if _v is None:
                continue
            try:
                _vf = float(_v)
                # 정확히 0.0 = RPi 읽기실패 폴백 / 범위 밖 = 물리불가
                _bad = (_vf == 0.0) or not (_lo < _vf < _hi)
            except (TypeError, ValueError):
                _bad = True
            if _bad:
                # 로깅만 스로틀(필터는 매번 적용). 상태가 정상→결함으로 바뀌었거나
                # 간격 경과 시에만 WARNING.
                _lk = (farm_id, house_id, _key)
                _now = time.time()
                _last_ts, _last_bad = _FAULT_LOG_LAST.get(_lk, (0.0, False))
                if (not _last_bad) or (_now - _last_ts >= _FAULT_LOG_INTERVAL):
                    logger.warning(
                        f"[센서필터] {_label} 결함값 {_v}{_unit} "
                        f"(farm={farm_id} house={house_id}) → None 처리"
                        f"{'' if not _last_bad else f' (반복 억제 {_FAULT_LOG_INTERVAL//60}분 간격)'}"
                    )
                    _FAULT_LOG_LAST[_lk] = (_now, True)
                row[_key] = None
            else:
                # 정상값 복귀 시 다음 결함을 다시 즉시 로깅하도록 상태 리셋
                _lk = (farm_id, house_id, _key)
                if _FAULT_LOG_LAST.get(_lk, (0.0, False))[1]:
                    _FAULT_LOG_LAST[_lk] = (time.time(), False)
    return row


# ────────────────────────────────────────────────────────────────────
# 재배사의 최근 릴레이(팬/히터/조명/관수 등) ON/OFF 상태 반환.
# ────────────────────────────────────────────────────────────────────
def read_latest_relay_info(farm_id, house_id):
    return _db_query(dbQry.GET_LATEST_RELAY_INFO, (farm_id, house_id),
                     fetch="one", error_msg=f"릴레이정보 조회 farm={farm_id} house={house_id}")


# ────────────────────────────────────────────────────────────────────
# 조명/관수 자동 제어 스케줄 설정 목록 반환.
# unit_type: 'light' | 'irrigation'.
# ────────────────────────────────────────────────────────────────────
def read_light_irrigation_settings(farm_id, house_id, unit_type):
    return _db_query(dbQry.GET_LIGHT_IRRIGATION, (farm_id, house_id, unit_type.lower()),
                     error_msg=f"{unit_type} 설정 조회 farm={farm_id} house={house_id}", default=[])


# ────────────────────────────────────────────────────────────────────
# 통합 스케줄 설정(SCHEDULE_M_SETTING) 전체 row 반환 — task_scheduler 폴링 진입점.
# ────────────────────────────────────────────────────────────────────
def read_schedule_settings():
    return _db_query(dbQry.GET_ALL_SCHEDULE_SETTINGS,
                     error_msg="schedule 설정 조회", default=[])


# ────────────────────────────────────────────────────────────────────
# 통합 스케줄 테이블의 최대 updt_dttm 한 건 반환 — 변경 감지 polling key.
# 결과 없으면 None.
# ────────────────────────────────────────────────────────────────────
def read_schedule_max_updt():
    row = _db_query(dbQry.GET_SCHEDULE_MAX_UPDT, fetch="one",
                    error_msg="schedule 최대 updt_dttm 조회")
    return row.get("max_updt") if row else None


# ────────────────────────────────────────────────────────────────────
# 호기별 SENSOR_M_SETTING 최대 updt_dttm — ai_thresholds 캐시 invalidate key.
# row 없으면 None.
# ────────────────────────────────────────────────────────────────────
def read_sensor_setting_max_updt(farm_id, house_id):
    row = _db_query(dbQry.GET_SENSOR_SETTING_MAX_UPDT,
                    (int(farm_id), int(house_id)), fetch="one",
                    error_msg=f"sensor_setting max_updt 조회 farm={farm_id} house={house_id}")
    return row.get("max_updt") if row else None


# ────────────────────────────────────────────────────────────────────
# PROMPT_BLOCK_M 단건 updt_dttm — prompt_registry 블록 캐시 invalidate key.
# block_id row 없으면 None.
# ────────────────────────────────────────────────────────────────────
def read_prompt_block_updt(block_id):
    row = _db_query(dbQry.GET_PROMPT_BLOCK_UPDT, (block_id,),
                    fetch="one",
                    error_msg=f"prompt_block updt_dttm 조회 block={block_id}")
    return row.get("updt_dttm") if row else None


# ────────────────────────────────────────────────────────────────────
# TOOL_DEFINITION_M 활성행 최대 updt_dttm — tools 캐시 invalidate key.
# 활성 row 없으면 None.
# ────────────────────────────────────────────────────────────────────
def read_tool_definition_max_updt():
    row = _db_query(dbQry.GET_TOOL_DEFINITION_MAX_UPDT, (),
                    fetch="one",
                    error_msg="tool_definition max_updt 조회")
    return row.get("max_updt") if row else None


# ────────────────────────────────────────────────────────────────────
# CONTROL_PROMPT_M 단건 updt_dttm — control_prompt 캐시 invalidate key.
# block_id row 없으면 None.
# ────────────────────────────────────────────────────────────────────
def read_control_prompt_updt(block_id):
    row = _db_query(dbQry.GET_CONTROL_PROMPT_UPDT, (block_id,),
                    fetch="one",
                    error_msg=f"control_prompt updt_dttm 조회 block={block_id}")
    return row.get("updt_dttm") if row else None


