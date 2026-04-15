# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 환경제어 모듈.
# 센서값 기반 릴레이 자동 제어 알고리즘 (온도/습도/CO2).
# 생육단계별 제어, 비상제어, 열풍기 쿨다운, 외부순환, 64케이스 분기를 포함한다.
# --->
# _log_house_status: log house status
# _classify: classify
# _is_external_normal: is external normal
# _is_internal_abnormal: is internal abnormal
# _reset_heater_cooldown: reset heater cooldown
# _get_current_heater_state: get current heater state
# _build_device_settings: 4대 장치 설정 딕셔너리를 생성한다
# _determine_devices: determine devices
# _determine_circulation: determine circulation
# _check_emergency: check emergency
# _build_relay_values: build relay values
# _write_relay: write relay
# _execute_control: execute control
# _execute_water_temp_emergency: execute water temp emergency
# _handle_ai_emergency: handle ai emergency
# _determine_environment_action: 센서 데이터 기반으로 장치/순환모드를 결정하고 판단 결과를 반환한다
# get_ai_environment_judgment: 현재 센서값 기반으로 알고리즘이 판단하는 최적 릴레이 상태를 반환 (실제 제어 없음)
# control_manual_environment: control manual environment
# control_all_manual: control all manual
# _ai_control_loop: AI 재배사 순환 제어 루프 (별도 스레드에서 실행)
# start_ai_control_loop: AI 순환 제어 루프를 별도 스레드로 시작
# stop_ai_control_loop: AI 순환 제어 루프 정지
# _mode_short: mode short
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
import time
import traceback
from datetime import datetime, timedelta

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_current_sensor_info, read_latest_relay_info, read_current_growth_stage
from agri_ai_core.src.control.relay_manager import set_relay_value
from agri_ai_core.src.control.schedule_control import control_lighting_schedule, control_irrigation_schedule
from agri_ai_core.src.control.control_common import (
    RELAY_COUNT,
    sort_houses as _sort_houses,
    house_prefix as _house_prefix,
    get_pin_map as _get_pin_map,
    format_sensor_parts,
    format_device_decision,
    format_relay_on_str,
    format_relay_off_str,
    is_llm_relay_locked,
    CIRCULATION_MODES,
    TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
    HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
    CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
    WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
    BUDDING_TEMP_LOW, BUDDING_TEMP_HIGH,
    DAMPER_FAN_DELAY_SEC,
    check_heater_cooldown, update_heater_tracking, reset_heater_state,
)

logger = setup_logger(__name__)


# ═════════════════════════════════════════
# 헬퍼 함수
# 센서 현황(INFO) + 릴레이 상세(DEBUG) 로그
# ═════════════════════════════════════════
def _log_house_status(farm_id, house_id, order_label=""):
    scope = _house_prefix(order_label, farm_id, house_id)

    sensor = read_current_sensor_info(farm_id, house_id)
    sensor_str = format_sensor_parts(sensor)
    if sensor_str:
        logger.info(f"{scope}: 센서 현황 - {sensor_str}")
    else:
        logger.info(f"{scope}: 센서 데이터 없음")

    relay = read_latest_relay_info(farm_id, house_id)
    if relay:
        logger.debug(f"{scope}: 릴레이 ON → [{format_relay_on_str(relay, house_id)}]")
        logger.debug(f"{scope}: 릴레이 OFF → [{format_relay_off_str(relay, house_id)}]")


def _classify(value, low, high):
    if value is None:
        logger.debug(f"센서값 None → 'normal' 처리 (범위: {low}~{high})")
        return 'normal'
    if value < low:
        return 'low'
    if value > high:
        return 'high'
    return 'normal'


def _is_external_normal(outdoor_temp, outdoor_humidity):
    temp_ok = outdoor_temp is not None and TEMP_LOW <= outdoor_temp <= TEMP_HIGH
    hum_ok = outdoor_humidity is not None and HUMIDITY_LOW <= outdoor_humidity <= HUMIDITY_HIGH
    return temp_ok and hum_ok


def _is_internal_abnormal(indoor_temp, indoor_humidity, co2):
    temp_bad = indoor_temp is not None and (indoor_temp < TEMP_LOW or indoor_temp > TEMP_HIGH)
    hum_bad = indoor_humidity is not None and (indoor_humidity < HUMIDITY_LOW or indoor_humidity > HUMIDITY_HIGH)
    co2_bad = co2 is not None and (co2 < CO2_LOW or co2 > CO2_HIGH)
    return temp_bad or hum_bad or co2_bad


# 히터 쿨다운 함수는 control_common에서 import (순환참조 방지)
_check_heater_cooldown = check_heater_cooldown
_update_heater_tracking = update_heater_tracking


def _reset_heater_cooldown(farm_id, house_id, order_label=""):
    reset_heater_state(farm_id, house_id)
    scope = _house_prefix(order_label, farm_id, house_id)
    logger.info(f"{scope}: 비상제어 → 열풍기 쿨다운 초기화")


def _get_current_heater_state(current_relay, pin_map):
    if not current_relay:
        return False
    heater_pin = pin_map.get('indoor_heater_flag')
    if heater_pin:
        return bool(current_relay.get(heater_pin, False))
    return False


def _build_device_settings(water_heater=False, fog=False, heater=False, heater_valve=False):
    """4대 장치 설정 딕셔너리를 생성한다."""
    return {
        'water_heater_flag': water_heater,
        'fog_occurs_flag': fog,
        'indoor_heater_flag': heater,
        'indoor_heater_valve_flag': heater_valve,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 64케이스 장치 결정: 온도/습도 → (water_heater, fog_pump, heater, heater_damper)
# ═══════════════════════════════════════════════════════════════════════════════
def _determine_devices(temp_state, humidity_state):
    if temp_state == 'low':
        if humidity_state == 'low':
            return True, True, False, False
        elif humidity_state == 'high':
            return False, False, True, True
        else:
            return True, False, False, False

    elif temp_state == 'high':
        if humidity_state == 'low':
            return False, True, False, False
        else:
            return False, False, False, False

    else:
        if humidity_state == 'low':
            return False, True, False, False
        else:
            return False, False, False, False


# ═══════════════════════════════════════════════════
# 64케이스 순환모드 결정: 센서 조건 → 순환모드 문자열
# ═══════════════════════════════════════════════════
def _determine_circulation(temp_state, ext_temp_state, humidity_state, ext_humidity_state, co2_state, ext_co2_state):
    # 내부온도 < 27
    if temp_state == 'low':
        if co2_state == 'high':
            return '배기순환'
        return '내부순환'

    # 내부온도 > 30
    if temp_state == 'high':
        if humidity_state == 'normal' and ext_humidity_state == 'abnormal':
            if co2_state == 'high':
                return '배기순환'
            return '내부순환'
        else:
            if co2_state == 'normal' and ext_co2_state == 'abnormal':
                return '내부순환'
            return '배기순환'

    # 온도정상
    if ext_temp_state == 'normal':
        # 온도정상 + 외부온도정상
        if humidity_state == 'low':
            if co2_state == 'high':
                return '배기순환'
            return '내부순환'
        elif humidity_state == 'high':
            if co2_state == 'normal' and ext_co2_state == 'abnormal':
                return '내부순환'
            return '배기순환'
        elif humidity_state == 'normal' and ext_humidity_state == 'normal':
            # #41~#44 (온도정상+외부정상+습도정상+외부정상)
            if co2_state == 'high':
                return '외부순환'
            return '내부순환'
        else:
            # 습도정상 + 외부습도비정상
            if co2_state == 'high':
                return '배기순환'
            return '내부순환'
    else:
        # 온도정상 + 외부온도비정상 (모든 습도 variant 동일)
        if co2_state == 'high':
            return '배기순환'
        return '내부순환'


# ═══════════════════════════════════════════════════
# 비상제어 체크: 임계값 이탈 시 비상 릴레이 설정 반환
# ═══════════════════════════════════════════════════
def _check_emergency(sensor_data):
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')

    # 온도 우선
    if indoor_temp is not None and indoor_temp < TEMP_CRITICAL_LOW:
        return True, _build_device_settings(water_heater=True, heater=True, heater_valve=True), '내부순환', False

    if indoor_temp is not None and indoor_temp > TEMP_CRITICAL_HIGH:
        return True, _build_device_settings(), '배기순환', False

    # 습도
    if indoor_humidity is not None and indoor_humidity < HUMIDITY_CRITICAL_LOW:
        return True, _build_device_settings(water_heater=True, fog=True), '내부순환', False

    if indoor_humidity is not None and indoor_humidity > HUMIDITY_CRITICAL_HIGH:
        return True, _build_device_settings(), '배기순환', False

    # CO2
    if co2 is not None and co2 > CO2_CRITICAL_HIGH:
        return True, _build_device_settings(), '배기순환', False

    # 수온 (물가열기만 제어, 다른 장치 유지)
    if water_temp is not None and water_temp < WATER_TEMP_CRITICAL_LOW:
        return True, {'water_heater_flag': True}, None, True

    if water_temp is not None and water_temp > WATER_TEMP_CRITICAL_HIGH:
        return True, {'water_heater_flag': False}, None, True

    return False, None, None, False


# ═══════════════════════════════════════════════════
# semantic 설정을 relay_*st_flag 16개 딕셔너리로 변환
# ═══════════════════════════════════════════════════
def _build_relay_values(house_id, semantic_settings, current_relay, harvest_mode):
    pin_map = _get_pin_map(house_id)

    relay_values = {f"relay_{i}st_flag": False for i in range(1, RELAY_COUNT + 1)}

    # 배수밸브 상시 ON
    drainage_pin = pin_map.get('drainage_motor_flag')
    if drainage_pin:
        relay_values[drainage_pin] = True

    # 현재 조명/관수 상태 보존
    if current_relay:
        lighting_pin = pin_map.get('lighting_flag')
        irrigation_pin = pin_map.get('irrigation_flag')
        if lighting_pin:
            relay_values[lighting_pin] = bool(current_relay.get(lighting_pin, False))
        if irrigation_pin:
            relay_values[irrigation_pin] = bool(current_relay.get(irrigation_pin, False))

    # 수확기: 관수 강제 OFF
    if harvest_mode:
        irrigation_pin = pin_map.get('irrigation_flag')
        if irrigation_pin:
            relay_values[irrigation_pin] = False

    # semantic 설정 적용
    for name, value in semantic_settings.items():
        pin_key = pin_map.get(name)
        if pin_key:
            relay_values[pin_key] = value

    return relay_values


def _write_relay(farm_id, house_id, relay_values):
    return set_relay_value(farm_id, house_id, relay_values, raw_mode=True)


# ═════════════════════════════════════════════════
# 2단계 릴레이 제어 (댐퍼→15초→팬, 열풍댐퍼→열풍기)
# ═════════════════════════════════════════════════
def _execute_control(
    farm_id,
    house_id,
    device_settings,
    circulation_mode,
    current_relay,
    harvest_mode,
    reason="",
    order_label="",
):
    pin_map = _get_pin_map(house_id)

    circ = CIRCULATION_MODES.get(circulation_mode, CIRCULATION_MODES['내부순환'])

    # 수확기: 배기순환 우선
    if harvest_mode and circulation_mode == '내부순환':
        circulation_mode = '배기순환'
        circ = CIRCULATION_MODES['배기순환']

    heater_on = device_settings.get('indoor_heater_flag', False)
    heater_damper_on = device_settings.get('indoor_heater_valve_flag', False)
    prev_heater_on = _get_current_heater_state(current_relay, pin_map)

    # === Phase 1: 댐퍼 + 장치 (팬/열풍기 시퀀스 대기) ===
    phase1_semantic = {}

    # 순환 댐퍼 설정
    phase1_semantic.update(circ['dampers'])

    # 물가열기, 분사펌프 즉시 적용
    phase1_semantic['water_heater_flag'] = device_settings.get('water_heater_flag', False)
    phase1_semantic['fog_occurs_flag'] = device_settings.get('fog_occurs_flag', False)

    # 열풍기/열풍댐퍼 Phase 1 (장치조작절대지침 준수)
    if heater_on and not prev_heater_on:
        # ON 시퀀스: 열풍댐퍼 ON 먼저, 열풍기는 Phase 2에서 ON
        phase1_semantic['indoor_heater_valve_flag'] = True
        phase1_semantic['indoor_heater_flag'] = False
    elif not heater_on and prev_heater_on:
        # OFF 시퀀스: 열풍기 OFF 먼저, 열풍댐퍼는 Phase 2에서 OFF
        phase1_semantic['indoor_heater_flag'] = False
        phase1_semantic['indoor_heater_valve_flag'] = True
    else:
        # 변화 없음: 최종 상태 즉시 적용
        phase1_semantic['indoor_heater_flag'] = heater_on
        phase1_semantic['indoor_heater_valve_flag'] = heater_damper_on

    # 팬: Phase 1에서는 현재 상태 유지
    if current_relay:
        intake_pin = pin_map.get('intake_fan_flag')
        exhaust_pin = pin_map.get('exhaust_fan_flag')
        phase1_semantic['intake_fan_flag'] = bool(current_relay.get(intake_pin, False)) if intake_pin else False
        phase1_semantic['exhaust_fan_flag'] = bool(current_relay.get(exhaust_pin, False)) if exhaust_pin else False
    else:
        phase1_semantic['intake_fan_flag'] = False
        phase1_semantic['exhaust_fan_flag'] = False

    # Phase 1 쓰기
    logger.debug(f"Phase 1 릴레이 시멘틱 설정: {phase1_semantic}")
    phase1_values = _build_relay_values(house_id, phase1_semantic, current_relay, harvest_mode)
    _write_relay(farm_id, house_id, phase1_values)

    scope = _house_prefix(order_label, farm_id, house_id)
    logger.info(f"{scope}: Phase 1 댐퍼제어 완료 ({reason}, {circulation_mode})")

    # === 15초 대기 (댐퍼→팬, 열풍댐퍼→열풍기 공통) ===
    time.sleep(DAMPER_FAN_DELAY_SEC)

    # === Phase 2: 팬 + 열풍기 최종 상태 ===
    phase2_semantic = dict(phase1_semantic)

    # 팬 최종 설정
    phase2_semantic.update(circ['fans'])

    # 열풍기/열풍댐퍼 최종 상태
    phase2_semantic['indoor_heater_flag'] = heater_on
    phase2_semantic['indoor_heater_valve_flag'] = heater_damper_on

    # Phase 2 쓰기
    logger.debug(f"Phase 2 릴레이 시멘틱 설정: {phase2_semantic}")
    phase2_values = _build_relay_values(house_id, phase2_semantic, current_relay, harvest_mode)
    result = _write_relay(farm_id, house_id, phase2_values)

    # 열풍기 상태 추적
    _update_heater_tracking(farm_id, house_id, heater_on)

    logger.info(f"{scope}: Phase 2 팬  제어 완료 ({reason}, {circulation_mode})")

    return {
        "success": result.get("success", False),
        "reason": reason,
        "circulation": circulation_mode,
        "devices": device_settings,
        "message": f"{reason} → {circulation_mode}",
    }


# ═════════════════════════════════════════════
# 수온 비상 전용 (물가열기만 변경, 나머지 유지)
# ═════════════════════════════════════════════
def _execute_water_temp_emergency(
    farm_id,
    house_id,
    water_heater_on,
    current_relay,
    harvest_mode,
    order_label="",
):
    pin_map = _get_pin_map(house_id)

    relay_values = {f"relay_{i}st_flag": False for i in range(1, RELAY_COUNT + 1)}

    # 현재 상태 전체 복사
    if current_relay:
        for key in relay_values:
            relay_values[key] = bool(current_relay.get(key, False))

    # 물가열기만 변경
    water_heater_pin = pin_map.get('water_heater_flag')
    if water_heater_pin:
        relay_values[water_heater_pin] = water_heater_on

    # 수확기: 관수 강제 OFF
    if harvest_mode:
        irrigation_pin = pin_map.get('irrigation_flag')
        if irrigation_pin:
            relay_values[irrigation_pin] = False

    result = _write_relay(farm_id, house_id, relay_values)

    status = "ON" if water_heater_on else "OFF"
    scope = _house_prefix(order_label, farm_id, house_id)
    logger.info(f"{scope}: 수온 비상 → 물가열기 {status}")

    return {
        "success": result.get("success", False),
        "reason": f"수온비상_물가열기{status}",
        "message": f"수온 비상제어 → 물가열기 {status}",
    }


# ══════════════════════════════════════════════════════════════════
# AI 모드 비상제어 공통 처리
# control_all_manual, control_all_ai 양쪽에서 사용
# Returns: (result, True) if emergency handled, (None, False) if not
# ══════════════════════════════════════════════════════════════════
def _handle_ai_emergency(farm_id, house_id, growth_stage, order_label=""):
    sensor_data = read_current_sensor_info(farm_id, house_id)
    if not sensor_data:
        return None, False

    is_emergency, emergency_devices, emergency_circulation, water_temp_only = _check_emergency(sensor_data)
    if not is_emergency:
        return None, False

    current_relay = read_latest_relay_info(farm_id, house_id)
    harvest_mode = (growth_stage == '수확기')

    if water_temp_only:
        result = _execute_water_temp_emergency(
            farm_id, house_id,
            emergency_devices.get('water_heater_flag', False),
            current_relay, harvest_mode, order_label=order_label
        )
    else:
        if emergency_devices.get('indoor_heater_flag', False):
            _reset_heater_cooldown(farm_id, house_id, order_label=order_label)
        logger.info(f"{order_label}: AI 모드 비상제어 발동")
        result = _execute_control(
            farm_id, house_id, emergency_devices, emergency_circulation,
            current_relay, harvest_mode, reason="AI모드_비상제어", order_label=order_label
        )
    return result, True


# ═══════════════════════════════════════════════════════════════════
# 공통 환경판단 로직
# get_ai_environment_judgment()와 control_manual_environment()가 공유
# ═══════════════════════════════════════════════════════════════════
def _determine_environment_action(sensor_data, growth_stage, farm_id, house_id):
    """센서 데이터 기반으로 장치/순환모드를 결정하고 판단 결과를 반환한다.

    Returns:
        dict: {
            "sensor": str, "growth_stage": str, "reason": str,
            "devices": dict, "circulation": str|None,
            "device_summary": str,
            "is_emergency": bool, "water_temp_only": bool,
            "in_cooldown": bool,
        } 또는 센서 부족 시 None
    """
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    outdoor_temp = sensor_data.get('outdoor_temperature')
    outdoor_humidity = sensor_data.get('outdoor_humidity')
    co2 = sensor_data.get('co2')

    sensor_str = format_sensor_parts(sensor_data)

    # (1) 비상제어 판단
    is_emergency, emergency_devices, emergency_circulation, water_temp_only = _check_emergency(sensor_data)
    if is_emergency:
        if water_temp_only:
            water_on = emergency_devices.get('water_heater_flag', False)
            return {
                "sensor": sensor_str, "growth_stage": growth_stage,
                "reason": f"수온비상_물가열기{'ON' if water_on else 'OFF'}",
                "devices": emergency_devices, "circulation": None,
                "device_summary": format_device_decision(emergency_devices),
                "is_emergency": True, "water_temp_only": True, "in_cooldown": False,
            }
        return {
            "sensor": sensor_str, "growth_stage": growth_stage,
            "reason": "비상제어",
            "devices": emergency_devices, "circulation": emergency_circulation,
            "device_summary": format_device_decision(emergency_devices),
            "is_emergency": True, "water_temp_only": False, "in_cooldown": False,
        }

    # (2) 발이기 판단
    if growth_stage == '발이기':
        if indoor_temp is None:
            return None
        if indoor_temp < BUDDING_TEMP_LOW:
            devices = _build_device_settings(water_heater=True, heater=True, heater_valve=True)
            reason, circ = "발이기_가열", "내부순환"
        elif indoor_temp > BUDDING_TEMP_HIGH:
            devices = _build_device_settings()
            reason, circ = "발이기_냉각", "배기순환"
        else:
            devices = _build_device_settings()
            reason, circ = "발이기_정상", "순환정지"
        return {
            "sensor": sensor_str, "growth_stage": growth_stage, "reason": reason,
            "devices": devices, "circulation": circ,
            "device_summary": format_device_decision(devices),
            "is_emergency": False, "water_temp_only": False, "in_cooldown": False,
        }

    # (3) 외부정상 + 내부비정상 → 외부순환
    if _is_external_normal(outdoor_temp, outdoor_humidity) and _is_internal_abnormal(indoor_temp, indoor_humidity, co2):
        devices = _build_device_settings()
        return {
            "sensor": sensor_str, "growth_stage": growth_stage, "reason": "외부정상+내부비정상",
            "devices": devices, "circulation": "외부순환",
            "device_summary": format_device_decision(devices),
            "is_emergency": False, "water_temp_only": False, "in_cooldown": False,
        }

    # (4) 64케이스
    temp_state = _classify(indoor_temp, TEMP_LOW, TEMP_HIGH)
    humidity_state = _classify(indoor_humidity, HUMIDITY_LOW, HUMIDITY_HIGH)
    co2_state = _classify(co2, CO2_LOW, CO2_HIGH)
    ext_temp_state = 'normal' if (outdoor_temp is not None and TEMP_LOW <= outdoor_temp <= TEMP_HIGH) else 'abnormal'
    ext_humidity_state = 'normal' if (outdoor_humidity is not None and HUMIDITY_LOW <= outdoor_humidity <= HUMIDITY_HIGH) else 'abnormal'
    ext_co2_state = 'normal'

    water_heater, fog_pump, heater, heater_damper = _determine_devices(temp_state, humidity_state)

    heater_available, in_cooldown = _check_heater_cooldown(farm_id, house_id)
    if not heater_available and heater:
        heater = False
        heater_damper = False

    circulation_mode = _determine_circulation(temp_state, ext_temp_state, humidity_state, ext_humidity_state, co2_state, ext_co2_state)

    harvest_mode = (growth_stage == '수확기')
    if harvest_mode and circulation_mode == '내부순환':
        circulation_mode = '배기순환'

    devices = _build_device_settings(water_heater, fog_pump, heater, heater_damper)

    reason = f"64케이스(온도:{temp_state},습도:{humidity_state},CO2:{co2_state})"
    if in_cooldown:
        reason += " [열풍기쿨다운]"

    return {
        "sensor": sensor_str, "growth_stage": growth_stage,
        "reason": reason,
        "devices": devices, "circulation": circulation_mode,
        "device_summary": format_device_decision(devices),
        "is_emergency": False, "water_temp_only": False, "in_cooldown": in_cooldown,
    }


# ══════════════════════════════════════════════════════
# AI 환경 판단 (제어 없이 판단만 수행)
# 수동 릴레이 제어 시 전/후 AI 판단을 제공하기 위한 함수
# ══════════════════════════════════════════════════════
def get_ai_environment_judgment(farm_id, house_id):
    """현재 센서값 기반으로 알고리즘이 판단하는 최적 릴레이 상태를 반환 (실제 제어 없음)."""
    try:
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            return None

        growth_stage = read_current_growth_stage(farm_id, house_id) or '생육기'
        result = _determine_environment_action(sensor_data, growth_stage, farm_id, house_id)
        if not result:
            return None

        return {
            "sensor": result["sensor"],
            "growth_stage": result["growth_stage"],
            "reason": result["reason"],
            "devices": result["devices"],
            "circulation": result["circulation"],
            "device_summary": result["device_summary"],
        }

    except Exception as e:
        logger.error(f"AI 환경 판단 오류: {e}")
        return None


# ══════════════════
# 환경제어 메인 함수
# ══════════════════
def control_manual_environment(farm_id, house_id, growth_stage='생육기', order_label=""):
    try:
        scope = _house_prefix(order_label, farm_id, house_id)
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            logger.info(f"{scope}: 센서 데이터 없음")
            return {"success": False, "message": "센서 데이터 없음"}

        current_relay = read_latest_relay_info(farm_id, house_id)
        harvest_mode = (growth_stage == '수확기')

        # 공통 판단 로직 호출
        action = _determine_environment_action(sensor_data, growth_stage, farm_id, house_id)
        if action:
            logger.debug(f"{scope}: 모드 판단 결과: reason={action['reason']}, circulation={action.get('circulation')}, is_emergency={action['is_emergency']}")
        if not action:
            logger.info(f"{scope}: 판단 불가 (센서 부족)")
            return {"success": False, "message": "판단 불가"}

        # 비상제어 처리
        if action["is_emergency"]:
            if action["water_temp_only"]:
                return _execute_water_temp_emergency(
                    farm_id, house_id,
                    action["devices"].get('water_heater_flag', False),
                    current_relay, harvest_mode, order_label=order_label
                )
            if action["devices"].get('indoor_heater_flag', False):
                _reset_heater_cooldown(farm_id, house_id, order_label=order_label)
            logger.warning(f"{scope}: 비상제어 발동")
            return _execute_control(
                farm_id, house_id, action["devices"], action["circulation"],
                current_relay, harvest_mode, reason="비상제어", order_label=order_label
            )

        # 열풍기 쿨다운 로깅
        if action["in_cooldown"]:
            logger.info(f"{scope}: 열풍기 쿨다운 중 (5분)")
            if action["devices"].get('indoor_heater_flag') is False:
                logger.info(f"{scope}: 열풍기 쿨다운 → 열풍기 제외 제어")

        # 외부순환/64케이스 로깅
        if action["reason"] == "외부정상+내부비정상":
            logger.info(f"{scope}: 외부정상+내부비정상 → 외부순환")

        return _execute_control(
            farm_id, house_id, action["devices"], action["circulation"],
            current_relay, harvest_mode,
            reason=action["reason"], order_label=order_label,
        )

    except Exception as e:
        scope = _house_prefix(order_label, farm_id, house_id)
        logger.error(f"알고리즘 환경제어 오류 ({scope}): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}


# ════════════════════
# 전체 재배사 환경제어
# ════════════════════
def _mode_short_of(h):
    """재배사 레코드에서 짧은 모드명 추출 (control_all_manual 내부 헬퍼)."""
    if not h.get("mnul_ctrl_flag"):
        return "수동제어"
    elif h.get("ctrl_type") == "ai":
        return "인공지능"
    else:
        return "알고리즘"


def _log_house_order_prefix(ordered_houses):
    """재배사 순서 + 모드 접두사 로그 출력."""
    mode_set = set(_mode_short_of(h) for h in ordered_houses if h.get("hous_id") is not None)
    if len(mode_set) == 1:
        all_mode_prefix = mode_set.pop()
        house_order = ", ".join(
            str(h.get("hous_id")) for h in ordered_houses if h.get("hous_id") is not None
        )
    else:
        all_mode_prefix = ""
        house_order = ", ".join(
            f"{h.get('hous_id')}({_mode_short_of(h)})"
            for h in ordered_houses if h.get("hous_id") is not None
        )
    if house_order:
        logger.info(f"{all_mode_prefix} 환경제어 대상 순서: {house_order}")


def _run_schedules_for_house(farm_id, house_id, order_label):
    """재배사별 조명/관수 스케줄 제어 실행 + 로그 출력."""
    logger.info("-")
    light_result = control_lighting_schedule(farm_id, house_id)
    irrigation_result = control_irrigation_schedule(farm_id, house_id)
    sched_parts = [
        f"조명 {light_result.get('status', '-')}",
        f"관수 {irrigation_result.get('status', '-')}",
    ]
    sched_schedules = list(light_result.get("schedules", [])) + list(irrigation_result.get("schedules", []))
    sched_info = f" (스케줄: {', '.join(sched_schedules)})" if sched_schedules else ""
    logger.info(
        f"{order_label} 농장 {farm_id}, 재배사 {house_id}: "
        f"{' / '.join(sched_parts)}{sched_info}"
    )


def _determine_mode_label(house, growth_stage):
    """재배사 설정 + 생육단계로부터 모드 라벨/단축명 결정.
    Returns: (mode_label, mode_short)
    """
    mnul_ctrl_flag = house.get("mnul_ctrl_flag")
    ctrl_type = house.get("ctrl_type", "algorithm")
    if not mnul_ctrl_flag:
        return "사용자 직접입력 모드", "수동제어"
    if ctrl_type == 'ai':
        return "AI 제어 모드", "인공지능"
    if growth_stage == '휴지기':
        return "휴지기", "휴지기"
    return "알고리즘 수동제어", "알고리즘"


def _process_ai_mode_house(farm_id, house_id, growth_stage, order_label):
    """AI 제어 모드 재배사 처리 (비상제어 + 모니터링).
    Returns: (result_dict_or_None, success_delta, fail_delta)
    """
    try:
        import importlib
        _ai_mod = importlib.import_module('agri_ai_core.src.control.ai_control')
        monitor_ai_emergency = _ai_mod.monitor_ai_emergency
        control_ai_environment = _ai_mod.control_ai_environment

        # 1. 비상제어 (하드 리밋 — AI보다 우선)
        result, handled = _handle_ai_emergency(farm_id, house_id, growth_stage, order_label)
        if handled:
            return result, (1 if result.get("success") else 0), (0 if result.get("success") else 1)

        # 2. AI 모니터링 (소프트 긴급: 임계치 근접 / 트렌드 급변)
        needs_intervention = monitor_ai_emergency(farm_id, house_id, order_label)
        if needs_intervention:
            result = control_ai_environment(farm_id, house_id, growth_stage, order_label)
            return result, (1 if result.get("success") else 0), (0 if result.get("success") else 1)
        scope = _house_prefix(order_label, farm_id, house_id)
        logger.info(f"{scope}: 정상 - [AI] 판단: 대기 (LLM 미호출 주기)")
        return None, 0, 0
    except Exception as e:
        logger.error(f"{order_label} AI 제어 예외: {e}")
        return None, 0, 0


def _log_completion_summary(mode_counts, total, success_count, fail_count):
    """전체 환경제어 완료 요약 로그."""
    if len(mode_counts) == 1:
        done_prefix = list(mode_counts.keys())[0]
        logger.info(f"{done_prefix} 환경제어 완료: 총 {total}개 재배사 (성공: {success_count}, 실패: {fail_count})")
    else:
        mode_str = ", ".join(f"{k} {v}" for k, v in mode_counts.items())
        logger.info(f"환경제어 완료: {mode_str} (총 {total}개, 성공: {success_count}, 실패: {fail_count})")
    logger.info("-")


def control_all_manual():
    """전체 재배사 수동/알고리즘/AI 환경제어 실행 (스케줄러 10초 주기)."""
    try:
        with db_session() as database:
            houses = database.fetch_all(
                query=dbQry.GET_HOUSE_NAME,
                vals=(None, None, None, None),
                as_dict=True
            )

            if not houses:
                logger.warning("등록된 재배사가 없습니다")
                return {"success": True, "total": 0, "results": []}

            ordered_houses = _sort_houses(houses)
            _log_house_order_prefix(ordered_houses)

            results = []
            success_count = 0
            fail_count = 0
            mode_counts = {}  # 모드별 재배사 수 집계

            for index, house in enumerate(ordered_houses, start=1):
                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")

                if farm_id is None or house_id is None:
                    continue

                order_label = f"[{index}/{len(ordered_houses)}]"

                # 조명/관수 스케줄 제어
                _run_schedules_for_house(farm_id, house_id, order_label)

                # 생육단계 조회 (모든 재배사 공통)
                growth_stage = read_current_growth_stage(farm_id, house_id)
                if not growth_stage:
                    growth_stage = '생육기'

                # 운용 모드 결정
                mode_label, mode_short = _determine_mode_label(house, growth_stage)
                mode_counts[mode_short] = mode_counts.get(mode_short, 0) + 1

                logger.info(
                    f"{order_label} ──── 농장 {farm_id}, 재배사 {house_id} "
                    f"──── {mode_label} (생육단계: {growth_stage})"
                )

                # AI 제어 모드 (10초 주기: 비상제어 + 모니터링만)
                if mode_label == "AI 제어 모드":
                    ai_result, s, f = _process_ai_mode_house(farm_id, house_id, growth_stage, order_label)
                    if ai_result is not None:
                        results.append({"farm_id": farm_id, "house_id": house_id, "result": ai_result})
                    success_count += s
                    fail_count += f
                    continue

                # 나머지 모드 (사용자 직접입력, 휴지기) → 센서/릴레이 현황만 로깅 후 스킵
                if mode_label != "알고리즘 수동제어":
                    _log_house_status(farm_id, house_id, order_label)
                    continue

                # LLM 제어 잠금 체크
                if is_llm_relay_locked(farm_id, house_id):
                    scope = _house_prefix(order_label, farm_id, house_id)
                    logger.info(f"{scope}: LLM 제어 잠금 활성 → 자동제어 스킵")
                    _log_house_status(farm_id, house_id, order_label)
                    continue

                result = control_manual_environment(
                    farm_id, house_id, growth_stage, order_label=order_label,
                )

                if result.get("success"):
                    success_count += 1
                else:
                    fail_count += 1

                results.append({
                    "farm_id": farm_id,
                    "house_id": house_id,
                    "result": result
                })

            _log_completion_summary(mode_counts, len(results), success_count, fail_count)

            return {
                "success": fail_count == 0,
                "total": len(results),
                "success_count": success_count,
                "fail_count": fail_count,
                "results": results
            }

    except Exception as e:
        logger.error(f"전체 환경제어 오류: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════
# AI 환경제어 순환 루프 (재배사 순환 + 30초 delay)
# 재배사를 ascending 순으로 순환하며 LLM 정기 호출
# 1재배사 제어 → 30초 대기 → 2재배사 → 30초 대기 → ... → 마지막 → 1재배사
# ═══════════════════════════════════════════════════════════════════════
from agri_ai_core.config import AI_CONTROL_LOOP_DELAY_SEC as _AI_LOOP_DELAY_SEC
_ai_loop_running = False
_ai_loop_thread = None


def _ai_control_loop():
    """AI 재배사 순환 제어 루프 (별도 스레드에서 실행)"""
    global _ai_loop_running
    _ai_loop_running = True
    logger.info(f"[AI순환루프] 시작 (재배사 간 {_AI_LOOP_DELAY_SEC}초 대기)")

    while _ai_loop_running:
        try:
            # 매 순환마다 AI 재배사 목록을 새로 조회 (모드 변경 반영)
            with db_session() as database:
                houses = database.fetch_all(
                    query=dbQry.GET_HOUSE_NAME,
                    vals=(None, None, None, None),
                    as_dict=True
                )

            if not houses:
                time.sleep(_AI_LOOP_DELAY_SEC)
                continue

            ordered_houses = _sort_houses(houses)
            ai_houses = [
                h for h in ordered_houses
                if h.get("mnul_ctrl_flag") and h.get("ctrl_type") == "ai"
                and h.get("farm_id") is not None and h.get("hous_id") is not None
            ]

            if not ai_houses:
                time.sleep(_AI_LOOP_DELAY_SEC)
                continue

            ai_order = ", ".join(str(h.get("hous_id")) for h in ai_houses)
            logger.info(f"[AI순환루프] 순환 시작: 대상 재배사 {ai_order} ({len(ai_houses)}개)")

            for index, house in enumerate(ai_houses, start=1):
                if not _ai_loop_running:
                    break

                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")
                order_label = f"[AI {index}/{len(ai_houses)}]"

                growth_stage = read_current_growth_stage(farm_id, house_id) or '생육기'

                try:
                    import importlib
                    _ai_mod = importlib.import_module('agri_ai_core.src.control.ai_control')
                    control_ai_environment = _ai_mod.control_ai_environment

                    # 비상제어 체크 (AI보다 우선)
                    result, handled = _handle_ai_emergency(farm_id, house_id, growth_stage, order_label)
                    if handled:
                        action = result.get("action", result.get("reason", "비상"))
                        logger.info(f"{order_label} 재배사 {house_id}: 비상제어 완료 → {action}")
                    else:
                        # AI LLM 정기 호출
                        result = control_ai_environment(farm_id, house_id, growth_stage, order_label)
                        action = result.get("action", "unknown")
                        logger.info(f"{order_label} 재배사 {house_id}: AI 제어 완료 → {action}")

                except Exception as e:
                    logger.error(f"{order_label} AI 제어 예외: {e}")
                    logger.error(traceback.format_exc())

                # 다음 재배사 전 30초 대기
                if _ai_loop_running:
                    logger.info(f"{order_label} 재배사 {house_id}: 제어 완료, {_AI_LOOP_DELAY_SEC}초 대기 후 다음 재배사")
                    time.sleep(_AI_LOOP_DELAY_SEC)

            # 마지막 재배사 완료 후 다시 1재배사부터 순환
            if _ai_loop_running:
                logger.info(f"[AI순환루프] 전체 순환 완료 ({len(ai_houses)}개 재배사), 다시 처음부터 순환")

        except Exception as e:
            logger.error(f"[AI순환루프] 루프 오류: {e}")
            logger.error(traceback.format_exc())
            if _ai_loop_running:
                time.sleep(_AI_LOOP_DELAY_SEC)

    logger.info("[AI순환루프] 종료")


def start_ai_control_loop():
    """AI 순환 제어 루프를 별도 스레드로 시작"""
    global _ai_loop_thread, _ai_loop_running
    if _ai_loop_thread and _ai_loop_thread.is_alive():
        logger.warning("[AI순환루프] 이미 실행 중")
        return

    import threading
    _ai_loop_running = True
    _ai_loop_thread = threading.Thread(target=_ai_control_loop, daemon=True, name="ai_control_loop")
    _ai_loop_thread.start()
    logger.info("[AI순환루프] 스레드 시작됨")


def stop_ai_control_loop():
    """AI 순환 제어 루프 정지"""
    global _ai_loop_running
    _ai_loop_running = False
    logger.info("[AI순환루프] 정지 요청됨")
