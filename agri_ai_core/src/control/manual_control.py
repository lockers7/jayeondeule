# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 수동 환경제어 모듈
# 센서값 기반 릴레이 자동 제어 알고리즘 (온도/습도/CO2)
# 생육단계별 제어, 비상제어, 열풍기 쿨다운, 외부순환 최적화, 64케이스 분기 포함
# --->
# control_manual_environment: 단일 재배사 수동 환경제어
# control_all_manual: 전체 재배사 수동 환경제어
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import time
import traceback
from datetime import datetime, timedelta

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql import queries as dbQry
from agri_ai_core.src.postgresql.reader import read_current_sensor_info, read_latest_relay_info, read_current_growth_stage
from agri_ai_core.src.control.relay_manager import set_relay_value

logger = setup_logger(__name__)


def _house_prefix(order_label="", farm_id=None, house_id=None):
    prefix = f"{order_label} " if order_label else ""
    if farm_id is None or house_id is None:
        return prefix.strip()
    return f"{prefix}농장 {farm_id}, 재배사 {house_id}"


def _to_sortable_int(value):
    try:
        return int(value)
    except Exception:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except Exception:
                pass
    return 10**9


def _sort_houses(houses):
    return sorted(
        houses or [],
        key=lambda house: (
            _to_sortable_int(house.get("farm_id")),
            _to_sortable_int(house.get("hous_id")),
            str(house.get("hous_id") or ""),
        ),
    )


# ============================================================
# 환경 제어 임계값
# ============================================================
TEMP_LOW = 27
TEMP_HIGH = 30
TEMP_CRITICAL_LOW = 25
TEMP_CRITICAL_HIGH = 33

HUMIDITY_LOW = 75
HUMIDITY_HIGH = 85
HUMIDITY_CRITICAL_LOW = 70
HUMIDITY_CRITICAL_HIGH = 95

CO2_LOW = 300
CO2_HIGH = 1200
CO2_CRITICAL_HIGH = 1500

WATER_TEMP_CRITICAL_LOW = 35
WATER_TEMP_CRITICAL_HIGH = 60

BUDDING_TEMP_LOW = 29
BUDDING_TEMP_HIGH = 33

HEATER_MAX_CONTINUOUS_MIN = 30
HEATER_COOLDOWN_MIN = 5

DAMPER_FAN_DELAY_SEC = 15
HEATER_DAMPER_DELAY_SEC = 10


# ============================================================
# Semantic name → relay_*st_flag 핀 매핑
# ============================================================
_RELAY_PIN_MAP_STANDARD = {
    'water_heater_flag': 'relay_1st_flag',
    'fog_occurs_flag': 'relay_2st_flag',
    'drainage_motor_flag': 'relay_3st_flag',
    'intake_fan_flag': 'relay_5st_flag',
    'exhaust_fan_flag': 'relay_6st_flag',
    'lighting_flag': 'relay_7st_flag',
    'irrigation_flag': 'relay_8st_flag',
    'indoor_heater_flag': 'relay_9st_flag',
    'air_circulation_valve_flag': 'relay_10st_flag',
    'air_intake_valve_flag': 'relay_11st_flag',
    'air_exhaust_valve_flag': 'relay_14st_flag',
    'indoor_heater2_flag': 'relay_15st_flag',
}

_RELAY_PIN_MAP_E = {
    'water_heater_flag': 'relay_1st_flag',
    'fog_occurs_flag': 'relay_2st_flag',
    'radiator_flag': 'relay_3st_flag',
    'lighting_flag': 'relay_5st_flag',
    'irrigation_flag': 'relay_6st_flag',
    'intake_fan_flag': 'relay_7st_flag',
    'exhaust_fan_flag': 'relay_8st_flag',
    'air_circulation_valve_flag': 'relay_9st_flag',
    'air_intake_valve_flag': 'relay_10st_flag',
    'air_exhaust_valve_flag': 'relay_11st_flag',
    'drainage_motor_flag': 'relay_12st_flag',
    'indoor_heater_flag': 'relay_13st_flag',
    'indoor_heater2_flag': 'relay_14st_flag',
}


# ============================================================
# 순환 모드 정의 (댐퍼 → 15초 후 → 팬)
# ============================================================
CIRCULATION_MODES = {
    '순환정지': {
        'dampers': {
            'air_circulation_valve_flag': True,
            'air_intake_valve_flag': True,
            'air_exhaust_valve_flag': True,
        },
        'fans': {
            'intake_fan_flag': False,
            'exhaust_fan_flag': False,
        },
    },
    '내부순환': {
        'dampers': {
            'air_circulation_valve_flag': True,
            'air_intake_valve_flag': False,
            'air_exhaust_valve_flag': False,
        },
        'fans': {
            'intake_fan_flag': True,
            'exhaust_fan_flag': True,
        },
    },
    '외부순환': {
        'dampers': {
            'air_circulation_valve_flag': False,
            'air_intake_valve_flag': True,
            'air_exhaust_valve_flag': True,
        },
        'fans': {
            'intake_fan_flag': True,
            'exhaust_fan_flag': True,
        },
    },
    '흡입순환': {
        'dampers': {
            'air_circulation_valve_flag': False,
            'air_intake_valve_flag': True,
            'air_exhaust_valve_flag': False,
        },
        'fans': {
            'intake_fan_flag': True,
            'exhaust_fan_flag': False,
        },
    },
    '배기순환': {
        'dampers': {
            'air_circulation_valve_flag': False,
            'air_intake_valve_flag': False,
            'air_exhaust_valve_flag': True,
        },
        'fans': {
            'intake_fan_flag': False,
            'exhaust_fan_flag': True,
        },
    },
}


# ============================================================
# 열풍기 상태 추적 (인메모리)
# ============================================================
_heater_state = {}


# ============================================================
# 헬퍼 함수
# ============================================================
def _get_pin_map(house_id):
    if int(house_id) == 2:
        return _RELAY_PIN_MAP_E
    return _RELAY_PIN_MAP_STANDARD


def _classify(value, low, high):
    if value is None:
        logger.warning(f"센서값 None → 'normal' 처리 (범위: {low}~{high})")
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


def _check_heater_cooldown(farm_id, house_id):
    key = (farm_id, int(house_id))
    state = _heater_state.get(key)
    now = datetime.now()

    if not state:
        return True, False

    cooling_until = state.get('cooling_until')
    if cooling_until:
        if now < cooling_until:
            return False, True
        _heater_state[key] = {}
        return True, False

    on_since = state.get('on_since')
    if on_since:
        elapsed_min = (now - on_since).total_seconds() / 60
        if elapsed_min >= HEATER_MAX_CONTINUOUS_MIN:
            _heater_state[key] = {'cooling_until': now + timedelta(minutes=HEATER_COOLDOWN_MIN)}
            return False, True

    return True, False


def _update_heater_tracking(farm_id, house_id, heater_on):
    key = (farm_id, int(house_id))
    state = _heater_state.get(key, {})

    if state.get('cooling_until'):
        return

    if heater_on:
        if 'on_since' not in state:
            _heater_state[key] = {'on_since': datetime.now()}
    else:
        _heater_state[key] = {}


def _reset_heater_cooldown(farm_id, house_id, order_label=""):
    key = (farm_id, int(house_id))
    _heater_state[key] = {}
    scope = _house_prefix(order_label, farm_id, house_id)
    logger.info(f"{scope}: 비상제어 → 열풍기 쿨다운 초기화")


def _get_current_heater_state(current_relay, pin_map):
    if not current_relay:
        return False
    heater_pin = pin_map.get('indoor_heater_flag')
    if heater_pin:
        return bool(current_relay.get(heater_pin, False))
    return False


# ============================================================
# 64케이스 장치 결정
# ============================================================

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 온도/습도 상태 → (water_heater, fog_pump, heater, heater_damper)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ============================================================
# 64케이스 순환모드 결정
# ============================================================

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 64케이스 센서 조건 → 순환모드 문자열
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ============================================================
# 비상제어 체크
# ============================================================

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 임계값 이탈 시 비상 릴레이 설정 반환
# Returns: (is_emergency, device_settings, circulation_mode, water_temp_only)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _check_emergency(sensor_data):
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')

    # 온도 우선
    if indoor_temp is not None and indoor_temp < TEMP_CRITICAL_LOW:
        return True, {
            'water_heater_flag': True,
            'fog_occurs_flag': False,
            'indoor_heater_flag': True,
            'indoor_heater2_flag': True,
        }, '내부순환', False

    if indoor_temp is not None and indoor_temp > TEMP_CRITICAL_HIGH:
        return True, {
            'water_heater_flag': False,
            'fog_occurs_flag': False,
            'indoor_heater_flag': False,
            'indoor_heater2_flag': False,
        }, '배기순환', False

    # 습도
    if indoor_humidity is not None and indoor_humidity < HUMIDITY_CRITICAL_LOW:
        return True, {
            'water_heater_flag': True,
            'fog_occurs_flag': True,
            'indoor_heater_flag': False,
            'indoor_heater2_flag': False,
        }, '내부순환', False

    if indoor_humidity is not None and indoor_humidity > HUMIDITY_CRITICAL_HIGH:
        return True, {
            'water_heater_flag': False,
            'fog_occurs_flag': False,
            'indoor_heater_flag': False,
            'indoor_heater2_flag': False,
        }, '배기순환', False

    # CO2
    if co2 is not None and co2 > CO2_CRITICAL_HIGH:
        return True, {
            'water_heater_flag': False,
            'fog_occurs_flag': False,
            'indoor_heater_flag': False,
            'indoor_heater2_flag': False,
        }, '배기순환', False

    # 수온 (물가열기만 제어, 다른 장치 유지)
    if water_temp is not None and water_temp < WATER_TEMP_CRITICAL_LOW:
        return True, {'water_heater_flag': True}, None, True

    if water_temp is not None and water_temp > WATER_TEMP_CRITICAL_HIGH:
        return True, {'water_heater_flag': False}, None, True

    return False, None, None, False


# ============================================================
# 릴레이 쓰기 헬퍼
# ============================================================

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# semantic 설정을 relay_*st_flag 16개 딕셔너리로 변환
# 조명/관수/배수밸브는 현재 상태 보존
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _build_relay_values(house_id, semantic_settings, current_relay, harvest_mode):
    pin_map = _get_pin_map(house_id)

    relay_values = {f"relay_{i}st_flag": False for i in range(1, 17)}

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


# ============================================================
# 2단계 제어 실행 (댐퍼→15초→팬, 열풍댐퍼→열풍기)
# ============================================================

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 장치조작절대지침 준수 2단계 릴레이 제어
# Phase 1: 댐퍼 + 장치 설정 (팬/열풍기 대기)
# Phase 2: 15초 후 팬 + 열풍기 최종 설정
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
    heater_damper_on = device_settings.get('indoor_heater2_flag', False)
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
        phase1_semantic['indoor_heater2_flag'] = True
        phase1_semantic['indoor_heater_flag'] = False
    elif not heater_on and prev_heater_on:
        # OFF 시퀀스: 열풍기 OFF 먼저, 열풍댐퍼는 Phase 2에서 OFF
        phase1_semantic['indoor_heater_flag'] = False
        phase1_semantic['indoor_heater2_flag'] = True
    else:
        # 변화 없음: 최종 상태 즉시 적용
        phase1_semantic['indoor_heater_flag'] = heater_on
        phase1_semantic['indoor_heater2_flag'] = heater_damper_on

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
    phase2_semantic['indoor_heater2_flag'] = heater_damper_on

    # Phase 2 쓰기
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


# ============================================================
# 수온 비상 전용 (물가열기만 변경, 나머지 유지)
# ============================================================
def _execute_water_temp_emergency(
    farm_id,
    house_id,
    water_heater_on,
    current_relay,
    harvest_mode,
    order_label="",
):
    pin_map = _get_pin_map(house_id)

    relay_values = {f"relay_{i}st_flag": False for i in range(1, 17)}

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


# ============================================================
# 발이기 제어
# ============================================================
def _control_budding(farm_id, house_id, indoor_temp, current_relay, order_label=""):
    if indoor_temp is None:
        scope = _house_prefix(order_label, farm_id, house_id)
        logger.info(f"{scope}: 발이기 - 온도 데이터 없음")
        return {"success": False, "message": "발이기: 온도 데이터 없음"}

    if indoor_temp < BUDDING_TEMP_LOW:
        # 온도 < 29: 가열
        device_settings = {
            'water_heater_flag': True,
            'fog_occurs_flag': False,
            'indoor_heater_flag': True,
            'indoor_heater2_flag': True,
        }
        return _execute_control(
            farm_id, house_id, device_settings, '내부순환',
            current_relay, harvest_mode=False, reason="발이기_가열", order_label=order_label
        )

    if indoor_temp > BUDDING_TEMP_HIGH:
        # 온도 > 33: 냉각
        device_settings = {
            'water_heater_flag': False,
            'fog_occurs_flag': False,
            'indoor_heater_flag': False,
            'indoor_heater2_flag': False,
        }
        return _execute_control(
            farm_id, house_id, device_settings, '배기순환',
            current_relay, harvest_mode=False, reason="발이기_냉각", order_label=order_label
        )

    # 온도 정상 (29~33): 제어 없음 → 순환 정지
    device_settings = {
        'water_heater_flag': False,
        'fog_occurs_flag': False,
        'indoor_heater_flag': False,
        'indoor_heater2_flag': False,
    }
    return _execute_control(
        farm_id, house_id, device_settings, '순환정지',
        current_relay, harvest_mode=False, reason="발이기_정상", order_label=order_label
    )


# ============================================================
# 메인 제어 함수
# ============================================================

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 수동 환경제어 메인 함수
# 제어 흐름:
# 1. 센서 데이터 조회
# 2. 비상제어 체크 (모든 생육단계 공통 최우선)
# 3. 생육단계 분기 (발이기 → 별도 제어)
# 4. 열풍기 쿨다운 체크
# 5. 외부정상+내부비정상 → 외부순환
# 6. 64케이스 진입
# 7. 2단계 릴레이 쓰기 (댐퍼→15초→팬)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def control_manual_environment(farm_id, house_id, growth_stage='생육기', order_label=""):
    try:
        scope = _house_prefix(order_label, farm_id, house_id)
        # 센서 데이터 조회
        sensor_data = read_current_sensor_info(farm_id, house_id)
        if not sensor_data:
            logger.info(f"{scope}: 센서 데이터 없음")
            return {"success": False, "message": "센서 데이터 없음"}

        # 현재 릴레이 상태 조회 (조명/관수 보존용)
        current_relay = read_latest_relay_info(farm_id, house_id)

        # 센서값 추출
        indoor_temp = sensor_data.get('indoor_temperature')
        indoor_humidity = sensor_data.get('indoor_humidity')
        outdoor_temp = sensor_data.get('outdoor_temperature')
        outdoor_humidity = sensor_data.get('outdoor_humidity')
        co2 = sensor_data.get('co2')

        # ================================================================
        # (1) 비상제어 (임계값 이탈) - 모든 생육단계 공통 최우선
        # ================================================================
        is_emergency, emergency_devices, emergency_circulation, water_temp_only = _check_emergency(sensor_data)

        harvest_mode = (growth_stage == '수확기')

        if is_emergency:
            if water_temp_only:
                return _execute_water_temp_emergency(
                    farm_id, house_id,
                    emergency_devices.get('water_heater_flag', False),
                    current_relay, harvest_mode, order_label=order_label
                )
            # 비상제어 시 열풍기 쿨다운 상태 초기화 (비상이 쿨다운보다 우선)
            if emergency_devices.get('indoor_heater_flag', False):
                _reset_heater_cooldown(farm_id, house_id, order_label=order_label)
            logger.info(f"{scope}: 비상제어 발동")
            return _execute_control(
                farm_id, house_id, emergency_devices, emergency_circulation,
                current_relay, harvest_mode, reason="비상제어", order_label=order_label
            )

        # ================================================================
        # (2) 생육단계 분기 (발이기)
        # ================================================================
        if growth_stage == '발이기':
            return _control_budding(farm_id, house_id, indoor_temp, current_relay, order_label=order_label)

        # ================================================================
        # (3) 열풍기 쿨다운 체크
        # ================================================================
        heater_available, in_cooldown = _check_heater_cooldown(farm_id, house_id)
        if in_cooldown:
            logger.info(f"{scope}: 열풍기 쿨다운 중 (5분)")

        # ================================================================
        # (4) 외부정상 + 내부비정상 → 외부순환
        # ================================================================
        if _is_external_normal(outdoor_temp, outdoor_humidity) and \
           _is_internal_abnormal(indoor_temp, indoor_humidity, co2):
            logger.info(f"{scope}: 외부정상+내부비정상 → 외부순환")
            return _execute_control(
                farm_id, house_id,
                {
                    'water_heater_flag': False,
                    'fog_occurs_flag': False,
                    'indoor_heater_flag': False,
                    'indoor_heater2_flag': False,
                },
                '외부순환', current_relay, harvest_mode,
                reason="외부정상+내부비정상", order_label=order_label
            )

        # ================================================================
        # (5) 64케이스
        # ================================================================
        # 센서 상태 분류
        temp_state = _classify(indoor_temp, TEMP_LOW, TEMP_HIGH)
        humidity_state = _classify(indoor_humidity, HUMIDITY_LOW, HUMIDITY_HIGH)
        co2_state = _classify(co2, CO2_LOW, CO2_HIGH)

        # 외부 센서 상태 (정상/비정상)
        ext_temp_state = 'normal' if (outdoor_temp is not None and TEMP_LOW <= outdoor_temp <= TEMP_HIGH) else 'abnormal'
        ext_humidity_state = 'normal' if (outdoor_humidity is not None and HUMIDITY_LOW <= outdoor_humidity <= HUMIDITY_HIGH) else 'abnormal'
        # 외부 CO2 센서: 현재 DB에 별도 컬럼 없음 → 정상으로 기본 처리
        ext_co2_state = 'normal'

        # 장치 결정
        water_heater, fog_pump, heater, heater_damper = _determine_devices(temp_state, humidity_state)

        # 열풍기 쿨다운 중이면 열풍기 제외
        if not heater_available and heater:
            heater = False
            heater_damper = False
            logger.info(f"{scope}: 열풍기 쿨다운 → 열풍기 제외 제어")

        # 순환모드 결정
        circulation_mode = _determine_circulation(
            temp_state, ext_temp_state,
            humidity_state, ext_humidity_state,
            co2_state, ext_co2_state
        )

        device_settings = {
            'water_heater_flag': water_heater,
            'fog_occurs_flag': fog_pump,
            'indoor_heater_flag': heater,
            'indoor_heater2_flag': heater_damper,
        }

        return _execute_control(
            farm_id, house_id, device_settings, circulation_mode,
            current_relay, harvest_mode,
            reason=f"64케이스(온도:{temp_state},습도:{humidity_state},CO2:{co2_state})",
            order_label=order_label,
        )

    except Exception as e:
        scope = _house_prefix(order_label, farm_id, house_id)
        logger.error(f"수동 환경제어 오류 ({scope}): {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}


# ============================================================
# 전체 재배사 수동 환경제어
# ============================================================
def control_all_manual():
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
            house_order = ", ".join(
                str(house.get("hous_id"))
                for house in ordered_houses
                if house.get("hous_id") is not None
            )
            if house_order:
                logger.info(f"수동 환경제어 대상 순서: {house_order}")

            results = []
            success_count = 0
            fail_count = 0

            for index, house in enumerate(ordered_houses, start=1):
                farm_id = house.get("farm_id")
                house_id = house.get("hous_id")

                if farm_id is None or house_id is None:
                    continue

                # 제어 모드 확인
                mnul_ctrl_flag = house.get("mnul_ctrl_flag")
                ctrl_type = house.get("ctrl_type", "algorithm")

                if not mnul_ctrl_flag:
                    # 사용자 직접 입력 모드 → 환경제어 스킵
                    logger.debug(f"농장 {farm_id}, 재배사 {house_id}: 사용자 입력 모드 (mnul_ctrl_flag=false) → 환경제어 스킵")
                    continue

                if ctrl_type == 'ai':
                    # AI 제어 모드 → AI가 별도로 제어 (여기서는 스킵)
                    logger.debug(f"농장 {farm_id}, 재배사 {house_id}: AI 제어 모드 → 알고리즘 환경제어 스킵")
                    continue

                # 알고리즘 수동제어 모드 (ctrl_type == 'algorithm')
                # crop_lvel 조회하여 생육단계 결정
                growth_stage = read_current_growth_stage(farm_id, house_id)
                if not growth_stage:
                    logger.warning(f"농장 {farm_id}, 재배사 {house_id}: 생육단계 조회 실패, 기본값 '생육기' 적용")
                    growth_stage = '생육기'

                if growth_stage == '휴지기':
                    logger.debug(f"농장 {farm_id}, 재배사 {house_id}: 휴지기 → 환경제어 스킵")
                    continue

                order_label = f"[{index}/{len(ordered_houses)}]"
                logger.info(
                    f"{order_label} ──── 농장 {farm_id}, 재배사 {house_id} "
                    f"──── 알고리즘 수동제어 (생육단계: {growth_stage})"
                )
                result = control_manual_environment(
                    farm_id,
                    house_id,
                    growth_stage,
                    order_label=order_label,
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

            logger.info(f"수동 환경제어 완료: 총 {len(results)}개 재배사 (성공: {success_count}, 실패: {fail_count})")

            return {
                "success": fail_count == 0,
                "total": len(results),
                "success_count": success_count,
                "fail_count": fail_count,
                "results": results
            }

    except Exception as e:
        logger.error(f"전체 수동 환경제어 오류: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"오류 발생: {str(e)}"}
