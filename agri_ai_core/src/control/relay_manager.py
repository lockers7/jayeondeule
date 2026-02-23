# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 제어 관리자 모듈
# 릴레이 설정값 변경, 상태 모니터링, 제어 이력 관리 등
# 릴레이 제어의 상위 레벨 관리 기능을 제공합니다.
# --->
# set_relay_value: 릴레이 값 설정
# get_relay_status: 릴레이 상태 조회
# batch_relay_control: 릴레이 일괄 제어
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_relay_mapping
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_latest_relay_info

logger = setup_logger(__name__)


def _get_alias_mapping(house_id):
    if int(house_id) == 2:
        return {
            "lighting_flag": "relay_5st_flag",
            "irrigation_flag": "relay_6st_flag",
        }
    return {
        "lighting_flag": "relay_7st_flag",
        "irrigation_flag": "relay_8st_flag",
    }


# 릴레이 번호 → (영문 기능명, 한글명) 매핑
_RELAY_DESC_STANDARD = {
    'relay_1st_flag': ('water_heater_flag', '물가열기'),
    'relay_2st_flag': ('fog_occurs_flag', '분사펌프'),
    'relay_3st_flag': ('drainage_motor_flag', '배수밸브'),
    'relay_4st_flag': ('unused', '미사용'),
    'relay_5st_flag': ('intake_fan_flag', '흡기팬'),
    'relay_6st_flag': ('exhaust_fan_flag', '배기팬'),
    'relay_7st_flag': ('lighting_flag', '조명토글'),
    'relay_8st_flag': ('irrigation_flag', '관수밸브'),
    'relay_9st_flag': ('indoor_heater_flag', '열풍기'),
    'relay_10st_flag': ('air_circulation_valve_flag', '순환댐퍼'),
    'relay_11st_flag': ('air_intake_valve_flag', '흡기댐퍼'),
    'relay_12st_flag': ('unused', '미사용'),
    'relay_13st_flag': ('unused', '미사용'),
    'relay_14st_flag': ('air_exhaust_valve_flag', '배기댐퍼'),
    'relay_15st_flag': ('indoor_heater2_flag', '열풍댐퍼'),
    'relay_16st_flag': ('unused', '미사용'),
}

_RELAY_DESC_E = {
    'relay_1st_flag': ('water_heater_flag', '물가열기'),
    'relay_2st_flag': ('fog_occurs_flag', '분사펌프'),
    'relay_3st_flag': ('radiator_flag', '라디에터'),
    'relay_4st_flag': ('unused', '미사용'),
    'relay_5st_flag': ('lighting_flag', '조명토글'),
    'relay_6st_flag': ('irrigation_flag', '관수밸브'),
    'relay_7st_flag': ('intake_fan_flag', '흡기팬'),
    'relay_8st_flag': ('exhaust_fan_flag', '배기팬'),
    'relay_9st_flag': ('air_circulation_valve_flag', '순환댐퍼'),
    'relay_10st_flag': ('air_intake_valve_flag', '흡기댐퍼'),
    'relay_11st_flag': ('air_exhaust_valve_flag', '배기댐퍼'),
    'relay_12st_flag': ('drainage_motor_flag', '배수밸브'),
    'relay_13st_flag': ('indoor_heater_flag', '열풍기'),
    'relay_14st_flag': ('indoor_heater2_flag', '열풍댐퍼'),
    'relay_15st_flag': ('unused', '미사용'),
    'relay_16st_flag': ('unused', '미사용'),
}


def format_relay_detail(house_id, relay_values):
    desc_map = _RELAY_DESC_E if int(house_id) == 2 else _RELAY_DESC_STANDARD
    parts = []
    for i in range(1, 17):
        key = f"relay_{i}st_flag"
        value = relay_values.get(key, False)
        eng, kor = desc_map.get(key, (key, ''))
        status = "ON" if value else "OFF"
        parts.append(f"{key}({eng}-{kor}): {status}")
    return ", ".join(parts)


def log_relay_detail(farm_id, house_id):
    current = read_latest_relay_info(farm_id, house_id)
    if not current:
        return
    desc_map = _RELAY_DESC_E if int(house_id) == 2 else _RELAY_DESC_STANDARD
    for i in range(1, 17):
        key = f"relay_{i}st_flag"
        value = bool(current.get(key, False))
        eng, kor = desc_map.get(key, (key, ''))
        status = "ON" if value else "OFF"
        logger.info(f"{key}({eng}-{kor}): {status}")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 값 설정
# 릴레이 값 설정
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     relay_settings: 릴레이 설정 딕셔너리
#
# Returns:
#     dict: 실행 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def set_relay_value(farm_id, house_id, relay_settings, raw_mode=False):
    try:
        # raw_mode: 수동환경제어에서 16개 relay_*st_flag를 직접 전달할 때 사용
        # raw_mode=True이면 기본값 초기화/별칭 변환/강제 ON 없이 그대로 사용
        if raw_mode:
            relay_values = dict(relay_settings)
        else:
            # 현재 릴레이 상태를 읽어 기존 상태 보존 (부분 갱신)
            current = read_latest_relay_info(farm_id, house_id)

            if current:
                relay_values = {
                    f"relay_{i}st_flag": bool(current.get(f"relay_{i}st_flag", False))
                    for i in range(1, 17)
                }
            else:
                # DB에 상태가 없으면 기본값 사용
                relay_values = {f"relay_{i}st_flag": False for i in range(1, 17)}

            # house_id별 alias 매핑 적용
            alias_mapping = _get_alias_mapping(house_id)

            for key, value in relay_settings.items():
                # 별칭을 실제 relay flag로 변환
                actual_key = alias_mapping.get(key, key)
                if actual_key in relay_values:
                    relay_values[actual_key] = value

        # SQL 파라미터 준비 (farm_id, hous_id, recd_dttm, relay flags...)
        from datetime import datetime
        recd_dttm = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params = (farm_id, int(house_id), recd_dttm) + tuple(relay_values.values())

        # 모든 재배사에 대해 동일한 쿼리 사용
        query = dbQry.SET_RELAY_VALUE

        with db_session() as database:
            result = database.execute_query(query, params)

            if result:
                logger.debug(f"릴레이 값 설정 완료: farm_id={farm_id}, house_id={house_id}")
                return {
                    "success": True,
                    "message": "릴레이 값이 성공적으로 설정되었습니다.",
                    "farm_id": farm_id,
                    "house_id": house_id,
                    "settings": relay_values
                }
            else:
                logger.warning(f"릴레이 값 설정 실패: farm_id={farm_id}, house_id={house_id}")
                return {
                    "success": False,
                    "message": "릴레이 값 설정에 실패했습니다."
                }

    except Exception as e:
        logger.error(f"릴레이 값 설정 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 상태 조회
# 릴레이 상태 조회
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#
# Returns:
#     dict: 릴레이 상태 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_relay_status(farm_id, house_id):
    try:
        with db_session() as database:
            result = database.fetch_one(
                query=dbQry.GET_LATEST_RELAY_INFO,
                vals=(farm_id, house_id)
            )

            if not result:
                logger.warning(f"릴레이 상태 조회 실패: farm_id={farm_id}, house_id={house_id}")
                return None

            # house_id에 따라 적절한 릴레이 매핑 선택
            relay_mapping = get_relay_mapping(house_id)

            relay_status = {}
            for relay_key, relay_info in relay_mapping.items():
                # relay_info는 [UI 표시 이름, 간단한 설명, 상세 기능 설명] 형식
                db_key = relay_key.replace("_flag", "")
                value = result.get(db_key, False)

                # relay_info가 리스트/튜플이면 적절히 추출
                if isinstance(relay_info, (list, tuple)):
                    relay_name = relay_info[1] if len(relay_info) > 1 else relay_key
                    relay_desc = relay_info[2] if len(relay_info) > 2 else ""
                else:
                    relay_name = relay_key
                    relay_desc = ""

                relay_status[relay_key] = {
                    "name": relay_name,
                    "description": relay_desc,
                    "value": value,
                    "status": "작동중" if value else "미작동"
                }

            return {
                "farm_id": farm_id,
                "house_id": house_id,
                "record_datetime": result.get("기록일시"),
                "relays": relay_status
            }

    except Exception as e:
        logger.error(f"릴레이 상태 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        return None


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 일괄 제어
# 여러 릴레이 일괄 제어
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     relay_commands: 릴레이 명령 목록
#
# Returns:
#     dict: 실행 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def batch_relay_control(farm_id, house_id, relay_commands):
    try:
        results = []
        success_count = 0
        fail_count = 0

        for command in relay_commands:
            relay_key = command.get("relay_key")
            state = command.get("state")

            try:
                # 단일 릴레이 설정
                relay_settings = {relay_key: state}
                result = set_relay_value(farm_id, house_id, relay_settings)

                if result["success"]:
                    success_count += 1
                    results.append({
                        "relay_key": relay_key,
                        "state": state,
                        "success": True
                    })
                else:
                    fail_count += 1
                    results.append({
                        "relay_key": relay_key,
                        "state": state,
                        "success": False,
                        "error": result.get("message")
                    })

            except Exception as e:
                fail_count += 1
                results.append({
                    "relay_key": relay_key,
                    "state": state,
                    "success": False,
                    "error": str(e)
                })

        return {
            "success": fail_count == 0,
            "total": len(relay_commands),
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results
        }

    except Exception as e:
        logger.error(f"릴레이 일괄 제어 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }


