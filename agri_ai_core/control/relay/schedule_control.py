# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 스케줄 제어 모듈
# 시간대별 자동 제어 스케줄을 관리하고 실행하는 기능을 제공하며,
# 설정된 조건에 따라 릴레이를 자동으로 제어합니다.
# --->
# should_execute_interval: 주기 기반 실행 여부 확인
# should_execute_weekdays: 요일 기반 실행 여부 확인
# is_time_in_range: 현재 시간이 스케줄 시간 범위 내인지 확인
# control_lighting_schedule: 조명 스케줄 제어
# control_irrigation_schedule: 관수밸브 스케줄 제어
# control_all_schedules: 모든 재배사 조명/관수밸브 스케줄 제어
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback
from datetime import datetime

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.database.postgres.connection import db_session
from agri_ai_core.database.postgres import queries as dbQry
from agri_ai_core.data_ingestion.postgres_reader import read_light_irrigation_settings
from agri_ai_core.control.relay.relay_manager import set_relay_value

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 주기 기반 실행 여부 확인
# 주기 기반 스케줄 실행 여부 확인
#
# Args:
#     start_date: 시작일 (date 객체)
#     interval: 주기 (일 단위, int)
#     current_date: 현재 날짜 (date 객체)
#
# Returns:
#     bool: 실행 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def should_execute_interval(start_date, interval, current_date):
    if not start_date or not interval:
        return False

    # 시작일로부터 경과 일수
    days_elapsed = (current_date - start_date).days

    # 주기로 나누어 떨어지면 실행
    return days_elapsed >= 0 and days_elapsed % interval == 0


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 요일 기반 실행 여부 확인
# 요일 기반 스케줄 실행 여부 확인
#
# Args:
#     weekdays_str: 요일 문자열 ('1,3,5' 형식)
#     current_date: 현재 날짜 (date 객체)
#
# Returns:
#     bool: 실행 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 현재 시간이 스케줄 시간 범위 내인지 확인
# 현재 시간이 시작/종료 시간 범위 내에 있는지 확인
#
# Args:
#     current_time: 현재 시간 (time 객체)
#     start_time: 시작 시간 (time 객체)
#     finish_time: 종료 시간 (time 객체)
#
# Returns:
#     bool: 범위 내 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def is_time_in_range(current_time, start_time, finish_time):
    # 시작 시간과 종료 시간이 같은 날인 경우
    if start_time <= finish_time:
        return start_time <= current_time <= finish_time
    # 자정을 넘어가는 경우 (예: 23:00 ~ 01:00)
    else:
        return current_time >= start_time or current_time <= finish_time


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 조명 스케줄 제어
# 조명 스케줄에 따라 조명 제어
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#
# Returns:
#     dict: 제어 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def control_lighting_schedule(farm_id, house_id):
    try:
        # 조명 설정 조회 (dlte_yn = False만)
        light_settings = read_light_irrigation_settings(farm_id, house_id, 'light')

        if not light_settings:
            logger.debug(f"농장 {farm_id}, 재배사 {house_id}: 조명 스케줄 없음")
            return {
                "success": True,
                "action": "none",
                "message": "조명 스케줄이 설정되지 않음"
            }

        # 현재 시간
        now = datetime.now()
        current_time = now.time()
        current_date = now.date()

        # 조명을 켜야 하는 시간대인지 확인
        should_turn_on = False
        active_schedules = []

        for setting in light_settings:
            start_time = setting.get('strt_time')
            finish_time = setting.get('fnsh_time')
            excs_type = setting.get('excs_type', 'daily')
            excs_itvl = setting.get('excs_itvl')
            excs_strt_date = setting.get('excs_strt_date')
            excs_wkdy = setting.get('excs_wkdy')

            # 시간대 확인
            if not (start_time and finish_time):
                continue

            if not is_time_in_range(current_time, start_time, finish_time):
                continue

            # 실행 유형에 따른 추가 확인
            should_execute = False

            if excs_type == 'daily':
                # 매일 실행
                should_execute = True

            elif excs_type == 'interval':
                # N일마다 실행
                should_execute = should_execute_interval(
                    excs_strt_date, excs_itvl, current_date
                )

            elif excs_type == 'weekdays':
                # 특정 요일만 실행
                should_execute = should_execute_weekdays(
                    excs_wkdy, current_date
                )

            if should_execute:
                should_turn_on = True
                schedule_info = f"{start_time.strftime('%H:%M')}-{finish_time.strftime('%H:%M')}"

                # 주기 정보 추가
                if excs_type == 'interval' and excs_itvl:
                    schedule_info += f"({excs_itvl}일마다)"
                elif excs_type == 'weekdays' and excs_wkdy:
                    weekday_names = {1: '월', 2: '화', 3: '수', 4: '목', 5: '금', 6: '토', 7: '일'}
                    days = [weekday_names.get(int(d.strip()), d) for d in excs_wkdy.split(',') if d.strip()]
                    schedule_info += f"({'/'.join(days)})"

                active_schedules.append(schedule_info)

        # 릴레이 설정
        relay_settings = {
            "lighting_flag": should_turn_on
        }

        # 릴레이 값 설정
        result = set_relay_value(farm_id, house_id, relay_settings)

        if result.get("success"):
            status = "ON" if should_turn_on else "OFF"
            schedule_info = f" (스케줄: {', '.join(active_schedules)})" if active_schedules else ""
            logger.info(f"농장 {farm_id}, 재배사 {house_id}: 조명 {status}{schedule_info}")

            return {
                "success": True,
                "action": "lighting_controlled",
                "status": status,
                "schedules": active_schedules,
                "message": f"조명 {status}"
            }
        else:
            logger.error(f"농장 {farm_id}, 재배사 {house_id}: 조명 제어 실패 - {result.get('message')}")
            return {
                "success": False,
                "message": f"조명 제어 실패: {result.get('message')}"
            }

    except Exception as e:
        logger.error(f"조명 스케줄 제어 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 관수밸브 스케줄 제어
# 관수밸브 스케줄에 따라 관수밸브 제어
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#
# Returns:
#     dict: 제어 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def control_irrigation_schedule(farm_id, house_id):
    try:
        # 관수밸브 설정 조회 (dlte_yn = False만)
        irrigation_settings = read_light_irrigation_settings(farm_id, house_id, 'water')

        if not irrigation_settings:
            logger.debug(f"농장 {farm_id}, 재배사 {house_id}: 관수밸브 스케줄 없음")
            return {
                "success": True,
                "action": "none",
                "message": "관수밸브 스케줄이 설정되지 않음"
            }

        # 현재 시간
        now = datetime.now()
        current_time = now.time()
        current_date = now.date()

        # 관수밸브를 켜야 하는 시간대인지 확인
        should_turn_on = False
        active_schedules = []

        for setting in irrigation_settings:
            start_time = setting.get('strt_time')
            finish_time = setting.get('fnsh_time')
            excs_type = setting.get('excs_type', 'daily')
            excs_itvl = setting.get('excs_itvl')
            excs_strt_date = setting.get('excs_strt_date')
            excs_wkdy = setting.get('excs_wkdy')

            # 시간대 확인
            if not (start_time and finish_time):
                continue

            if not is_time_in_range(current_time, start_time, finish_time):
                continue

            # 실행 유형에 따른 추가 확인
            should_execute = False

            if excs_type == 'daily':
                # 매일 실행
                should_execute = True

            elif excs_type == 'interval':
                # N일마다 실행
                should_execute = should_execute_interval(
                    excs_strt_date, excs_itvl, current_date
                )

            elif excs_type == 'weekdays':
                # 특정 요일만 실행
                should_execute = should_execute_weekdays(
                    excs_wkdy, current_date
                )

            if should_execute:
                should_turn_on = True
                schedule_info = f"{start_time.strftime('%H:%M')}-{finish_time.strftime('%H:%M')}"

                # 주기 정보 추가
                if excs_type == 'interval' and excs_itvl:
                    schedule_info += f"({excs_itvl}일마다)"
                elif excs_type == 'weekdays' and excs_wkdy:
                    weekday_names = {1: '월', 2: '화', 3: '수', 4: '목', 5: '금', 6: '토', 7: '일'}
                    days = [weekday_names.get(int(d.strip()), d) for d in excs_wkdy.split(',') if d.strip()]
                    schedule_info += f"({'/'.join(days)})"

                active_schedules.append(schedule_info)

        # 릴레이 설정
        relay_settings = {
            "irrigation_flag": should_turn_on
        }

        # 릴레이 값 설정
        result = set_relay_value(farm_id, house_id, relay_settings)

        if result.get("success"):
            status = "ON" if should_turn_on else "OFF"
            schedule_info = f" (스케줄: {', '.join(active_schedules)})" if active_schedules else ""
            logger.info(f"농장 {farm_id}, 재배사 {house_id}: 관수밸브 {status}{schedule_info}")

            return {
                "success": True,
                "action": "irrigation_controlled",
                "status": status,
                "schedules": active_schedules,
                "message": f"관수밸브 {status}"
            }
        else:
            logger.error(f"농장 {farm_id}, 재배사 {house_id}: 관수밸브 제어 실패 - {result.get('message')}")
            return {
                "success": False,
                "message": f"관수밸브 제어 실패: {result.get('message')}"
            }

    except Exception as e:
        logger.error(f"관수밸브 스케줄 제어 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 모든 재배사 조명/관수밸브 스케줄 제어
# 모든 농장/재배사의 조명 및 관수밸브 스케줄 제어
#
# Returns:
#     dict: 전체 제어 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

            results = []
            success_count = 0
            fail_count = 0

            for house in houses:
                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")

                if farm_id is None or house_id is None:
                    continue

                # 조명 제어
                light_result = control_lighting_schedule(farm_id, house_id)

                # 관수밸브 제어
                irrigation_result = control_irrigation_schedule(farm_id, house_id)

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
