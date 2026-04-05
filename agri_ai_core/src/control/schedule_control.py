# ══════════════════════════════════
# 릴레이 스케줄 제어 모듈.
#
# 시간대별 자동 제어 스케줄(조명/관수밸브)을 관리·실행하며,
# 주기/요일 기반 실행 여부를 판단하여 릴레이를 자동 제어한다.
# ══════════════════════════════════
import traceback
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_light_irrigation_settings, read_current_sensor_info
from agri_ai_core.src.control.relay_manager import set_relay_value, log_relay_detail
from agri_ai_core.src.postgresql.reader import read_latest_relay_info
from agri_ai_core.src.control.control_common import get_pin_map, RELAY_COUNT
from agri_ai_core.src.control.control_common import (
    sort_houses as _sort_houses,
    TEMP_LOW, TEMP_HIGH,
    HUMIDITY_LOW, HUMIDITY_HIGH,
    CO2_LOW, CO2_HIGH,
    WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
)

logger = setup_logger(__name__)

_WEEKDAY_NAMES = {1: '월', 2: '화', 3: '수', 4: '목', 5: '금', 6: '토', 7: '일'}


# 센서 상태 포맷 (임계값 비교 포함)
_SENSOR_THRESHOLDS = {
    'indoor_temperature': ('내부온도', '℃', TEMP_LOW, TEMP_HIGH),
    'indoor_humidity':    ('내부습도', '%', HUMIDITY_LOW, HUMIDITY_HIGH),
    'co2':                ('CO2', 'ppm', CO2_LOW, CO2_HIGH),
    'water_temperature':  ('수온', '℃', WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH),
}


def _format_sensor_status(sensor):
    parts = []
    for key, (name, unit, low, high) in _SENSOR_THRESHOLDS.items():
        value = sensor.get(key)
        if value is None:
            parts.append(f"{name}: -")
            continue
        text = f"{name}: {value}{unit}"
        if value < low:
            text += f" < {low}{unit}(최저값)"
        elif value > high:
            text += f" > {high}{unit}(최고값)"
        parts.append(text)
    return ", ".join(parts)


# 주기 기반 실행 여부 확인
# ══════════════════
def should_execute_interval(start_date, interval, current_date):
    if not start_date or not interval:
        return False

    # 시작일로부터 경과 일수
    days_elapsed = (current_date - start_date).days

    # 주기로 나누어 떨어지면 실행
    return days_elapsed >= 0 and days_elapsed % interval == 0


# 요일 기반 실행 여부 확인
# ══════════════════
def should_execute_weekdays(weekdays_str, current_date):
    if not weekdays_str:
        return False

    try:
        # 현재 요일 (1=월요일, 7=일요일)
        current_weekday = current_date.isoweekday()

        # 설정된 요일 목록
        allowed_weekdays = [int(w.strip()) for w in weekdays_str.split(',')]

        return current_weekday in allowed_weekdays
    except (ValueError, AttributeError) as e:
        logger.warning(f"요일 형식 오류: {weekdays_str}, 오류: {e}")
        return False


# 현재 시간이 스케줄 시간 범위 내인지 확인
# ═══════════════════════
def is_time_in_range(current_time, start_time, finish_time):
    # 시작 시간과 종료 시간이 같은 날인 경우
    if start_time <= finish_time:
        return start_time <= current_time <= finish_time
    # 자정을 넘어가는 경우 (예: 23:00 ~ 01:00)
    else:
        return current_time >= start_time or current_time <= finish_time


# 조명/관수 공통 스케줄 제어 로직
# ══════════════════
def _handle_schedule_control(farm_id, house_id, setting_type, relay_flag_key, label, action_name):
    try:
        settings = read_light_irrigation_settings(farm_id, house_id, setting_type)

        if not settings:
            logger.debug(f"농장 {farm_id}, 재배사 {house_id}: {label} 스케줄 없음")
            return {"success": True, "action": "none", "message": f"{label} 스케줄이 설정되지 않음"}

        now = datetime.now()
        current_time = now.time()
        current_date = now.date()

        should_turn_on = False
        active_schedules = []

        for setting in settings:
            start_time = setting.get('strt_time')
            finish_time = setting.get('fnsh_time')
            excs_type = setting.get('excs_type', 'daily')
            excs_itvl = setting.get('excs_itvl')
            excs_strt_date = setting.get('excs_strt_date')
            excs_wkdy = setting.get('excs_wkdy')

            if not (start_time and finish_time):
                continue
            if not is_time_in_range(current_time, start_time, finish_time):
                continue

            should_execute = False
            if excs_type == 'daily':
                should_execute = True
            elif excs_type == 'interval':
                should_execute = should_execute_interval(excs_strt_date, excs_itvl, current_date)
            elif excs_type == 'weekdays':
                should_execute = should_execute_weekdays(excs_wkdy, current_date)

            if should_execute:
                should_turn_on = True
                schedule_info = f"{start_time.strftime('%H:%M')}-{finish_time.strftime('%H:%M')}"
                if excs_type == 'interval' and excs_itvl:
                    schedule_info += f"({excs_itvl}일마다)"
                elif excs_type == 'weekdays' and excs_wkdy:
                    days = [_WEEKDAY_NAMES.get(int(d.strip()), d) for d in excs_wkdy.split(',') if d.strip()]
                    schedule_info += f"({'/'.join(days)})"
                active_schedules.append(schedule_info)

        # 스케줄 시간대 내 → ON / 스케줄 있고 시간대 밖 → OFF (스케줄 종료)
        # 스케줄 설정 자체가 없으면 → 현재 상태 유지 (웹 수동 제어값 보존)
        # ※ raw_mode=True로 호출하여 반복쓰기 스레드 생성 방지 (다른 릴레이 덮어쓰기 방지)
        has_any_schedule = any(
            s.get('strt_time') and s.get('fnsh_time') for s in settings
        )

        if should_turn_on or has_any_schedule:
            new_value = should_turn_on  # True=ON, False=OFF

            # 현재 전체 릴레이 상태를 읽어서 해당 릴레이만 변경 (raw_mode용)
            current = read_latest_relay_info(farm_id, house_id)
            if current:
                relay_values = {
                    f"relay_{i}st_flag": bool(current.get(f"relay_{i}st_flag", False))
                    for i in range(1, RELAY_COUNT + 1)
                }
            else:
                relay_values = {f"relay_{i}st_flag": False for i in range(1, RELAY_COUNT + 1)}

            # 시멘틱 키 → 실제 릴레이 핀 변환
            pin_map = get_pin_map(house_id)
            actual_pin = pin_map.get(relay_flag_key, relay_flag_key)
            relay_values[actual_pin] = new_value

            # raw_mode=True: 반복쓰기 스레드 없이 1회 DB 쓰기만 (다른 릴레이 보존)
            result = set_relay_value(farm_id, house_id, relay_values, raw_mode=True)

            if result.get("success"):
                status = "ON" if new_value else "OFF"
                sched_str = f" (스케줄: {', '.join(active_schedules)})" if active_schedules else ""
                suffix = "" if new_value else " (스케줄 종료)"
                logger.debug(f"농장 {farm_id}, 재배사 {house_id}: {label} {status}{sched_str}{suffix}")
                return {"success": True, "action": action_name, "status": status,
                        "schedules": active_schedules, "message": f"{label} {status}"}
            else:
                logger.error(f"농장 {farm_id}, 재배사 {house_id}: {label} 제어 실패 - {result.get('message')}")
                return {"success": False, "message": f"{label} 제어 실패: {result.get('message')}"}
        else:
            # 스케줄 설정 없음 → 현재 상태 유지 (웹 수동 제어값 보존)
            return {"success": True, "action": "none", "status": "-",
                    "schedules": [], "message": f"{label} 스케줄 미설정 (현재 상태 유지)"}

    except Exception as e:
        logger.error(f"{label} 스케줄 제어 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}


def control_lighting_schedule(farm_id, house_id):
    return _handle_schedule_control(farm_id, house_id, 'light', 'lighting_flag', '조명', 'lighting_controlled')


def control_irrigation_schedule(farm_id, house_id):
    return _handle_schedule_control(farm_id, house_id, 'water', 'irrigation_flag', '관수밸브', 'irrigation_controlled')


# 모든 재배사 조명/관수밸브 스케줄 제어
# ═════════════════════
def control_all_schedules():
    try:
        with db_session() as database:
            # 모든 활성 재배사 조회
            houses = database.fetch_all(
                query=dbQry.GET_HOUSE_NAME,
                vals=(None, None, None, None),
                as_dict=True
            )

            if not houses:
                logger.warning("등록된 재배사가 없습니다")
                return {
                    "success": True,
                    "total": 0,
                    "results": []
                }

            ordered_houses = _sort_houses(houses)
            house_order = ", ".join(
                str(house.get("hous_id"))
                for house in ordered_houses
                if house.get("hous_id") is not None
            )
            if house_order:
                logger.info(f"스케줄 제어 대상 순서: {house_order}")

            results = []
            success_count = 0
            fail_count = 0

            for index, house in enumerate(ordered_houses, start=1):
                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")

                if farm_id is None or house_id is None:
                    continue

                # 조명 제어
                light_result = control_lighting_schedule(farm_id, house_id)

                # 관수밸브 제어
                irrigation_result = control_irrigation_schedule(farm_id, house_id)

                # 결합 로그 출력
                parts = []
                all_schedules = []

                light_status = light_result.get("status", "-")
                parts.append(f"조명 {light_status}")
                all_schedules.extend(light_result.get("schedules", []))

                irr_status = irrigation_result.get("status", "-")
                parts.append(f"관수 {irr_status}")
                all_schedules.extend(irrigation_result.get("schedules", []))

                schedule_info = f" (스케줄: {', '.join(all_schedules)})" if all_schedules else ""
                logger.info("-")
                logger.info(
                    f"[{index}/{len(ordered_houses)}] 농장 {farm_id}, 재배사 {house_id}: "
                    f"{' / '.join(parts)}{schedule_info}"
                )

                # 센서 상태 + 릴레이 상세 로그 (실제 제어가 발생한 경우만)
                has_control = (light_result.get("action") != "none" or irrigation_result.get("action") != "none")
                if has_control:
                    sensor = read_current_sensor_info(farm_id, house_id)
                    if sensor:
                        logger.info(f"센서 상태: {_format_sensor_status(sensor)}")
                    log_relay_detail(farm_id, house_id)

                # 결과 집계
                house_result = {
                    "farm_id": farm_id,
                    "house_id": house_id,
                    "lighting": light_result,
                    "irrigation": irrigation_result
                }

                if light_result.get("success") and irrigation_result.get("success"):
                    success_count += 1
                else:
                    fail_count += 1

                results.append(house_result)

            logger.info(f"스케줄 제어 완료: 총 {len(results)}개 재배사 (성공: {success_count}, 실패: {fail_count})")
            logger.info("-")
            
            return {
                "success": fail_count == 0,
                "total": len(results),
                "success_count": success_count,
                "fail_count": fail_count,
                "results": results
            }

    except Exception as e:
        logger.error(f"전체 스케줄 제어 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }
