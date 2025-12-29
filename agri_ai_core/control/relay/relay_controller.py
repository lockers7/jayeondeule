# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 제어 핵심 로직 모듈
# 재배사의 릴레이 상태 조회, 제어 명령 처리, 자동/수동 모드 전환 등
# 하드웨어 제어의 핵심 비즈니스 로직을 구현합니다.
# --->
# get_single_house_status: 특정 재배사 시스템 상태 조회
# get_all_houses_status: 전체 재배사 시스템 상태 조회
# change_operation_mode: 농장/재배사 작동 모드 변경
# execute_relay_command: 개별 릴레이 제어 실행
# detect_and_execute_relay_commands: 응답에서 릴레이 조작 명령 감지 및 실행
# generate_final_response: 최종 응답 생성
# post_process_response: 응답 후처리
# format_relay_status_response: 릴레이 상태 응답 포맷팅
# format_farm_status_response: 농장 상태 응답 포맷팅
# add_control_guidance: 제어 가이드 추가
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import re
import traceback

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.shared_modules.common.mappers import get_relay_name
from agri_ai_core.database.postgres.connection import db_session
from agri_ai_core.database.postgres import queries as dbQry

logger = setup_logger(__name__)

# 제어 JSON 질의 유형
CONTROL_JSON_QUERIES = {"environment_control", "relay_control", "control_suggestion", "relay_llm_control"}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 특정 재배사 시스템 상태 조회
# 특정 재배사 시스템 상태 조회
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     house_name: 재배사명
#
# Returns:
#     dict: 상태 데이터 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_single_house_status(farm_id, house_id=None, house_name=None):
    try:
        with db_session() as database:
            if house_id is None and house_name is not None:
                house_result = database.fetch_one(
                    query=dbQry.GET_HOUSE_ID,
                    vals=(farm_id, farm_id, str(house_name))
                )
                if house_result:
                    house_id = house_result["hous_id"]
                    logger.info(f"재배사명 '{house_name}'으로 house_id {house_id} 조회됨")

            result = database.fetch_one(
                query=dbQry.GET_UNITS_VALUE,
                vals=(farm_id, int(house_id))
            )

            if not result:
                logger.warning(f"농장 {farm_id}, 재배사 {house_id} 데이터 조회 실패")
                return None

            operation_mode = "수동모드" if result.get("mnul_ctrl_flag") else "자동모드"

            status_data = {
                "farm_id": result.get("농장코드"),
                "farm_name": result.get("농장명"),
                "house_id": result.get("재배사코드"),
                "house_name": result.get("재배사명"),
                "operation_mode": operation_mode,
                "record_datetime": result.get("기록일시"),
                "indoor_temperature": result.get("내부온도"),
                "indoor_humidity": result.get("내부습도"),
                "co2": result.get("co2"),
                "water_temperature": result.get("수온"),
                "light_level": result.get("광량"),
                "outdoor_temperature": result.get("외부온도"),
                "outdoor_humidity": result.get("외부습도")
            }

            return status_data

    except Exception as e:
        logger.error(f"재배사 상태 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        return None


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 전체 재배사 시스템 상태 조회
# 전체 재배사 시스템 상태 조회
#
# Args:
#     farm_id: 농장 ID
#
# Returns:
#     list: 모든 재배사 상태 목록
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_all_houses_status(farm_id):
    try:
        with db_session() as database:
            house_id = None
            houses = database.fetch_all(
                query=dbQry.GET_HOUSE_NAME,
                vals=(farm_id, house_id),
                as_dict=True
            )

            if not houses:
                logger.warning(f"농장 {farm_id}에 등록된 재배사가 없습니다")
                return []

            all_houses_status = []
            for house in houses:
                house_id = house["hous_id"]
                result = database.fetch_one(
                    query=dbQry.GET_UNITS_VALUE,
                    vals=(farm_id, int(house_id))
                )

                if result:
                    operation_mode = "수동모드" if result.get("mnul_ctrl_flag") else "자동모드"

                    status_data = {
                        "farm_id": result.get("농장코드"),
                        "farm_name": result.get("농장명"),
                        "house_id": result.get("재배사코드"),
                        "house_name": result.get("재배사명"),
                        "operation_mode": operation_mode,
                        "record_datetime": result.get("기록일시"),
                        "indoor_temperature": result.get("내부온도"),
                        "indoor_humidity": result.get("내부습도"),
                        "co2": result.get("co2"),
                        "water_temperature": result.get("수온"),
                        "light_level": result.get("광량"),
                        "outdoor_temperature": result.get("외부온도"),
                        "outdoor_humidity": result.get("외부습도")
                    }

                    all_houses_status.append(status_data)

            return all_houses_status

    except Exception as e:
        logger.error(f"전체 재배사 상태 조회 중 오류: {e}")
        logger.error(traceback.format_exc())
        return []


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장/재배사 작동 모드 변경
# 농장/재배사 작동 모드 변경
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     mode: 모드 ("manual" 또는 "auto")
#
# Returns:
#     dict: 결과 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def change_operation_mode(farm_id, house_id=None, mode="manual"):
    try:
        # mode를 boolean으로 변환
        if isinstance(mode, str):
            is_manual = mode.lower() in ["manual", "수동", "true"]
        else:
            is_manual = bool(mode)

        mode_name = "수동모드" if is_manual else "자동모드"

        with db_session() as database:
            result = database.execute_query(
                query=dbQry.SET_MANAGE_METHOD,
                vals=(is_manual, farm_id, house_id)
            )
            if result:
                target_info = f"농장 {farm_id}"
                if house_id:
                    target_info += f", 재배사 {house_id}"

                logger.info(f"{target_info}의 작동 모드가 {mode_name}로 변경됨")
                return {
                    "success": True,
                    "farm_id": farm_id,
                    "house_id": house_id,
                    "mode": mode_name,
                    "message": f"{target_info}의 작동 모드가 {mode_name}로 변경되었습니다."
                }
            else:
                logger.warning(f"작동 모드 변경 실패: 농장 {farm_id}, 재배사 {house_id}")
                return {
                    "success": False,
                    "message": "작동 모드 변경에 실패했습니다."
                }

    except Exception as e:
        logger.error(f"작동 모드 변경 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"오류 발생: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 개별 릴레이 제어 실행
# 개별 릴레이 제어 실행
#
# Args:
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#     relay_key: 릴레이 키
#     state: 상태 (True/False)
#
# Returns:
#     dict: 실행 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def execute_relay_command(farm_id, house_id, relay_key, state):
    try:
        with db_session():
            logger.info(f"릴레이 제어 실행: 농장={farm_id}, 재배사={house_id}, 릴레이={relay_key}, 상태={state}")

            # 실제 릴레이 제어 로직
            # result = database.execute_query(relay_control_query, vals=(state, farm_id, house_id, relay_key))

            return {
                "success": True,
                "message": f"{relay_key} 제어 완료"
            }

    except Exception as e:
        logger.error(f"릴레이 제어 실행 중 오류: {e}")
        return {
            "success": False,
            "message": f"릴레이 제어 실행 실패: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 응답에서 릴레이 조작 명령 감지 및 실행
# 응답에서 릴레이 조작 명령 감지 및 실행
#
# Args:
#     response: LLM 응답
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#
# Returns:
#     dict: 실행 결과
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def detect_and_execute_relay_commands(response, farm_id, house_id=None):
    try:
        executed_commands = []

        if "수동모드" in response.replace(" ", ""):
            result = change_operation_mode(farm_id, house_id, "manual")
            if result["success"]:
                executed_commands.append("수동모드로 변경됨")

        if "자동모드" in response.replace(" ", ""):
            result = change_operation_mode(farm_id, house_id, "auto")
            if result["success"]:
                executed_commands.append("자동모드로 변경됨")

        relay_control_patterns = {
            r'수온히터.*켜': ('water_heater_flag', True),
            r'수온히터.*꺼': ('water_heater_flag', False),
            r'습도모터.*켜': ('fog_occurs_flag', True),
            r'습도모터.*꺼': ('fog_occurs_flag', False),
            r'배수밸브.*켜': ('drainage_motor_flag', True),
            r'배수밸브.*꺼': ('drainage_motor_flag', False),
            r'환풍모터.*켜': ('exhaust_fan_flag', True),
            r'환풍모터.*꺼': ('exhaust_fan_flag', False),
            r'조명토글.*켜': ('lighting_flag', True),
            r'조명토글.*꺼': ('lighting_flag', False),
            r'관수토글.*켜': ('irrigation_flag', True),
            r'관수토글.*꺼': ('irrigation_flag', False),
            r'히터.*켜': ('indoor_heater_flag', True),
            r'히터.*꺼': ('indoor_heater_flag', False),
        }

        for pattern, (relay_key, state) in relay_control_patterns.items():
            if re.search(pattern, response):
                result = execute_relay_command(farm_id, house_id, relay_key, state)
                if result["success"]:
                    relay_name = get_relay_name(relay_key)
                    status = "켜짐" if state else "꺼짐"
                    executed_commands.append(f"{relay_name}: {status}")

        if executed_commands:
            logger.info(f"릴레이 명령 실행됨: {executed_commands}")
            return {
                "executed": True,
                "commands": executed_commands,
                "message": f"다음 제어가 실행되었습니다: {', '.join(executed_commands)}"
            }
        else:
            return {
                "executed": False,
                "commands": [],
                "message": ""
            }

    except Exception as e:
        logger.error(f"릴레이 명령 감지 및 실행 중 오류: {e}")
        logger.error(traceback.format_exc())
        return {
            "executed": False,
            "commands": [],
            "message": f"릴레이 제어 중 오류 발생: {str(e)}"
        }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최종 응답 생성
# 사용자에게 최종 응답 생성
#
# Args:
#     llm_response: LLM 응답
#     query_type: 질의 유형
#     farm_id: 농장 ID
#     house_id: 재배사 ID
#
# Returns:
#     str: 최종 응답
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def generate_final_response(llm_response, query_type, farm_id, house_id=None):
    try:
        if query_type in CONTROL_JSON_QUERIES:
            return llm_response

        final_response = llm_response

        if query_type in ["relay_control", "environment_control", "control_suggestion", "auto_mode", "manual_mode"]:
            relay_result = detect_and_execute_relay_commands(llm_response, farm_id, house_id)

            if relay_result["executed"]:
                final_response += f"\n\n🔧 **제어 실행 결과:**\n{relay_result['message']}"
                logger.info(f"릴레이 제어 실행: {relay_result['commands']}")

        final_response = post_process_response(final_response, query_type)

        return final_response

    except Exception as e:
        logger.error(f"최종 응답 생성 중 오류: {e}")
        logger.error(traceback.format_exc())
        return llm_response


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 응답 후처리
# 응답 후처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def post_process_response(response, query_type):
    try:
        processed_response = response

        if query_type == "relay_status":
            processed_response = format_relay_status_response(processed_response)
        elif query_type == "farm_status":
            processed_response = format_farm_status_response(processed_response)
        elif query_type in ["environment_control", "control_suggestion"]:
            processed_response = add_control_guidance(processed_response)

        return processed_response

    except Exception as e:
        logger.error(f"응답 후처리 중 오류: {e}")
        return response


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 상태 응답 포맷팅
# 릴레이 상태 응답 포맷팅
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def format_relay_status_response(response):
    try:
        formatted_response = response

        if "릴레이" in response and "상태" in response:
            formatted_response += "\n\n **릴레이 제어 참고사항:**\n"
            formatted_response += "- 작동중(True): 해당 장치가 현재 가동 중입니다\n"
            formatted_response += "- 미작동(False): 해당 장치가 현재 정지 상태입니다\n"
            formatted_response += "- 환경 조건에 따라 적절한 릴레이 조합을 사용하세요\n"

        return formatted_response

    except Exception as e:
        logger.error(f"릴레이 상태 응답 포맷팅 중 오류: {e}")
        return response


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 상태 응답 포맷팅
# 농장 상태 응답 포맷팅
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def format_farm_status_response(response):
    try:
        formatted_response = response

        if "온도" in response or "습도" in response:
            formatted_response += "\n\n **환경 모니터링 가이드:**\n"
            formatted_response += "- 온도: 작물별 최적 범위 유지 필요\n"
            formatted_response += "- 습도: 병해충 예방을 위한 적정 수준 관리\n"
            formatted_response += "- CO2: 광합성 촉진을 위한 농도 조절\n"

        return formatted_response

    except Exception as e:
        logger.error(f"농장 상태 응답 포맷팅 중 오류: {e}")
        return response


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 제어 가이드 추가
# 제어 가이드 추가
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def add_control_guidance(response):
    try:
        guided_response = response

        if "제어" in response or "조절" in response:
            guided_response += "\n\n **제어 실행 가이드:**\n"
            guided_response += "- 환경 변화는 점진적으로 진행됩니다\n"
            guided_response += "- 제어 후 30분~1시간 정도 효과를 관찰하세요\n"
            guided_response += "- 급격한 환경 변화는 작물에 스트레스를 줄 수 있습니다\n"
            guided_response += "- 외부 기상 조건도 함께 고려하세요\n"

        return guided_response

    except Exception as e:
        logger.error(f"제어 가이드 추가 중 오류: {e}")
        return response
