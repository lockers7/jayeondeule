# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 제어 관리자 모듈
# 릴레이 설정값 변경, 상태 모니터링, 제어 이력 관리 등
# 릴레이 제어의 상위 레벨 관리 기능을 제공합니다.
# --->
# set_relay_value: 릴레이 값 설정
# get_relay_status: 릴레이 상태 조회
# batch_relay_control: 릴레이 일괄 제어
# auto_control_by_environment: 환경 기반 릴레이 자동 제어
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import get_relay_mapping
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry

logger = setup_logger(__name__)


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
def set_relay_value(farm_id, house_id, relay_settings):
    try:
        # house_id에 따라 적절한 릴레이 매핑 선택
        relay_mapping = get_relay_mapping(house_id)

        # 릴레이 설정 초기화 (relay_*_flag만 사용)
        # 1호 재배사 열풍댐퍼(relay_15st_flag)는 항상 ON 유지
        heater_valve_on = (str(house_id) == "1")

        relay_values = {
            "relay_1st_flag": False,
            "relay_2st_flag": False,
            "relay_3st_flag": True,   # 배수밸브 기본 ON
            "relay_4st_flag": False,
            "relay_5st_flag": True,   # 흡기팬 기본 ON
            "relay_6st_flag": True,   # 배기팬 기본 ON
            "relay_7st_flag": False,
            "relay_8st_flag": False,
            "relay_9st_flag": False,
            "relay_10st_flag": False,
            "relay_11st_flag": False,
            "relay_12st_flag": False,
            "relay_13st_flag": False,
            "relay_14st_flag": False,
            "relay_15st_flag": heater_valve_on,  # 1호 재배사 열풍댐퍼 항상 ON
            "relay_16st_flag": False,
        }

        # 제공된 릴레이 설정 적용
        # lighting_flag, irrigation_flag 같은 별칭을 relay_*_flag로 변환
        alias_mapping = {
            "lighting_flag": "relay_7st_flag",     # 조명토글
            "irrigation_flag": "relay_8st_flag",   # 관수밸브
        }

        for key, value in relay_settings.items():
            # 별칭을 실제 relay flag로 변환
            actual_key = alias_mapping.get(key, key)
            if actual_key in relay_values:
                relay_values[actual_key] = value

        # 1호 재배사 열풍댐퍼 강제 ON (덮어쓰기 방지)
        if str(house_id) == "1":
            relay_values["relay_15st_flag"] = True

        # SQL 파라미터 준비 (farm_id, hous_id, recd_dttm, relay flags...)
        from datetime import datetime
        recd_dttm = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params = (farm_id, int(house_id), recd_dttm) + tuple(relay_values.values())

        # 모든 재배사에 대해 동일한 쿼리 사용
        query = dbQry.SET_RELAY_VALUE

        with db_session() as database:
            result = database.execute_query(query, params)

            if result:
                logger.info(f"릴레이 값 설정 완료: farm_id={farm_id}, house_id={house_id}")
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 환경 기반 릴레이 자동 제어
# 환경 데이터 기반 릴레이 자동 제어
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     sensor_data: 센서 데이터
#     optimal_conditions: 최적 환경 조건
#
# Returns:
#     dict: 제어 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def auto_control_by_environment(farm_id, house_id, sensor_data, optimal_conditions):
    try:
        relay_commands = []
        current_hour = datetime.now().hour
        is_daytime = 6 <= current_hour < 18

        # 온도 기반 제어
        indoor_temp = sensor_data.get("indoor_temperature", 0)
        optimal_temp = optimal_conditions.get("temperature", {})

        if is_daytime:
            temp_min = optimal_temp.get("day", {}).get("min", 18)
            temp_max = optimal_temp.get("day", {}).get("max", 28)
        else:
            temp_min = optimal_temp.get("night", {}).get("min", 15)
            temp_max = optimal_temp.get("night", {}).get("max", 22)

        # 온도가 낮으면 히터 켜기
        if indoor_temp < temp_min:
            relay_commands.append({"relay_key": "indoor_heater_flag", "state": True})
            relay_commands.append({"relay_key": "water_heater_flag", "state": True})
        # 온도가 높으면 환풍기 켜기
        elif indoor_temp > temp_max:
            relay_commands.append({"relay_key": "exhaust_fan_flag", "state": True})
            relay_commands.append({"relay_key": "indoor_heater_flag", "state": False})

        # 습도 기반 제어
        indoor_humidity = sensor_data.get("indoor_humidity", 0)
        optimal_humidity = optimal_conditions.get("humidity", {})

        if is_daytime:
            humidity_min = optimal_humidity.get("day", {}).get("min", 60)
            humidity_max = optimal_humidity.get("day", {}).get("max", 80)
        else:
            humidity_min = optimal_humidity.get("night", {}).get("min", 65)
            humidity_max = optimal_humidity.get("night", {}).get("max", 85)

        # 습도가 낮으면 가습 켜기
        if indoor_humidity < humidity_min:
            relay_commands.append({"relay_key": "fog_occurs_flag", "state": True})
        # 습도가 높으면 환풍기 켜기
        elif indoor_humidity > humidity_max:
            relay_commands.append({"relay_key": "exhaust_fan_flag", "state": True})
            relay_commands.append({"relay_key": "fog_occurs_flag", "state": False})

        # 조명 제어 (주간에만)
        if is_daytime:
            relay_commands.append({"relay_key": "lighting_flag", "state": True})
        else:
            relay_commands.append({"relay_key": "lighting_flag", "state": False})

        # 릴레이 일괄 제어 실행
        if relay_commands:
            result = batch_relay_control(farm_id, house_id, relay_commands)
            logger.info(f"환경 기반 자동 제어 실행: {result}")
            return result
        else:
            return {
                "success": True,
                "message": "현재 환경이 최적 범위 내에 있어 제어가 필요하지 않습니다."
            }

    except Exception as e:
        logger.error(f"환경 기반 자동 제어 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }
