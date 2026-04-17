# ════════════════════════════════════════════════════════════════════════════════
# 환경 판단 로직 (순수 함수) — 센서값 → 장치 결정 / 순환 모드 / 비상 판단
# manual_control.py에서 분리된 L6 계층 모듈. 외부 부작용 없음 (DB/GPIO 호출 없음).
# 단위 테스트 용이.
# --->
# _classify: 센서값을 low/normal/high로 분류
# _is_external_normal: 외부 온습도가 정상 범위인지 판별
# _is_internal_abnormal: 내부 온습도/CO2 이상 여부 판별
# _build_device_settings: 4대 장치 설정 딕셔너리 생성 헬퍼
# _determine_devices: 64케이스 장치 결정 (온도/습도 → water_heater/fog/heater/damper)
# _determine_circulation: 64케이스 순환모드 결정 (내부/외부/배기순환)
# _check_emergency: 임계값 이탈 시 비상 릴레이 설정 반환
# ════════════════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.control_common import (
    TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
    HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
    CO2_LOW, CO2_HIGH, CO2_CRITICAL_HIGH,
    WATER_TEMP_CRITICAL_LOW, WATER_TEMP_CRITICAL_HIGH,
)

logger = setup_logger(__name__)


def _classify(value, low, high):
    """센서값을 low/normal/high로 분류. None은 normal 처리."""
    if value is None:
        logger.debug(f"센서값 None → 'normal' 처리 (범위: {low}~{high})")
        return 'normal'
    if value < low:
        return 'low'
    if value > high:
        return 'high'
    return 'normal'


def _is_external_normal(outdoor_temp, outdoor_humidity):
    """외부 온도+습도가 모두 정상 범위인지 판별."""
    temp_ok = outdoor_temp is not None and TEMP_LOW <= outdoor_temp <= TEMP_HIGH
    hum_ok = outdoor_humidity is not None and HUMIDITY_LOW <= outdoor_humidity <= HUMIDITY_HIGH
    return temp_ok and hum_ok


def _is_internal_abnormal(indoor_temp, indoor_humidity, co2):
    """내부 온도/습도/CO2 중 하나라도 이상 범위인지 판별."""
    temp_bad = indoor_temp is not None and (indoor_temp < TEMP_LOW or indoor_temp > TEMP_HIGH)
    hum_bad = indoor_humidity is not None and (indoor_humidity < HUMIDITY_LOW or indoor_humidity > HUMIDITY_HIGH)
    co2_bad = co2 is not None and (co2 < CO2_LOW or co2 > CO2_HIGH)
    return temp_bad or hum_bad or co2_bad


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
# Returns: (is_emergency, device_settings, circulation_mode, water_temp_only)
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
