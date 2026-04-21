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
# _apply_fog_coupling: 포그생성 결합 규칙 후처리 (수온히터 ON 또는 수온≥40℃ → fog ON)
# ════════════════════════════════════════════════════════════════════════════════
from agri_ai_core.logs import setup_logger
# [2026-04-28 rev2] 센서 임계값 하드코딩 금지 — control_common 의 임계 상수
# 직접 import 제거. 모든 임계값은 ai_thresholds.get_thresholds() 또는 호출자가
# 전달한 ts 인자로 사용. ts 가 None 이어도 안전하도록 get_global_default() 폴백.
from agri_ai_core.src.control.ai_thresholds import (
    get_global_default as _get_default_ts,
)

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# ts 가 None 이면 get_global_default() 로 폴백.
# ────────────────────────────────────────────────────────────────────
def _ts(ts):
    return ts if ts is not None else _get_default_ts()


# ────────────────────────────────────────────────────────────────────
# 센서값을 low/normal/high 로 분류. None 은 normal 처리.
# ────────────────────────────────────────────────────────────────────
def _classify(value, low, high):
    if value is None:
        logger.debug(f"센서값 None → 'normal' 처리 (범위: {low}~{high})")
        return 'normal'
    if value < low:
        return 'low'
    if value > high:
        return 'high'
    return 'normal'


# ────────────────────────────────────────────────────────────────────
# 외부 온도+습도가 모두 정상 범위인지 판별.
# [2026-04-28 rev2] ts None 이면 ai_thresholds.get_global_default() 폴백.
# ────────────────────────────────────────────────────────────────────
def _is_external_normal(outdoor_temp, outdoor_humidity, ts=None):
    t = _ts(ts)
    temp_ok = outdoor_temp is not None and t.temp_low <= outdoor_temp <= t.temp_high
    hum_ok = outdoor_humidity is not None and t.humidity_low <= outdoor_humidity <= t.humidity_high
    return temp_ok and hum_ok


# ────────────────────────────────────────────────────────────────────
# 내부 온도/습도/CO2 중 하나라도 이상 범위인지 판별.
# ────────────────────────────────────────────────────────────────────
def _is_internal_abnormal(indoor_temp, indoor_humidity, co2, ts=None):
    t = _ts(ts)
    temp_bad = indoor_temp is not None and (indoor_temp < t.temp_low or indoor_temp > t.temp_high)
    hum_bad = indoor_humidity is not None and (indoor_humidity < t.humidity_low or indoor_humidity > t.humidity_high)
    co2_bad = co2 is not None and (co2 < t.co2_low or co2 > t.co2_high)
    return temp_bad or hum_bad or co2_bad


# ────────────────────────────────────────────────────────────────────
# 장치 설정 딕셔너리 생성 (rule-based 비상제어 전용).
# [2026-04-27] 실내히터·히터밸브 미사용으로 인자 제거.
# [2026-05-01 rev1] 수온히터·배수밸브 상호배타 결합 룰 추가.
# [2026-05-01 rev2] drainage 자동결정 제거 — LLM 자율 판단 영역.
#   비상제어가 자동으로 drainage 까지 결정하면 LLM 이 mappers.py 의 의존성 룰을
#   직접 적용할 기회를 잃음. 본 함수는 비상시(LLM SKIP) 안전 폴백 결정만 담당.
#   비상시에도 mappers.py 룰을 지키되, LLM 정상 분기에서는 LLM 이 직접 결정.
# ────────────────────────────────────────────────────────────────────
def _build_device_settings(water_heater=False, fog=False):
    # 비상 폴백: 수온히터 ON 시 배수밸브 OFF (mappers.py 안전 룰 — 비상에서만 자동).
    # LLM 정상 분기는 본 함수 거치지 않으므로 자율성 영향 없음.
    return {
        'water_heater_flag': water_heater,
        'fog_occurs_flag': fog,
        'drainage_motor_flag': not water_heater,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# [2026-04-28 rev2] 포그생성 결합 규칙 — 단일화
#
# 핵심 원칙 (사용자 명시): "재배사 온도가 적정 범위 이하이면 수온히터를 ON 해서
# 수온이 정상범위 하한(ts.water_temp_low) 이상에 도달해야 포그를 ON 한다."
#
# 결정 규칙 (모든 임계값은 ts/DB 동적 — 하드코딩 없음):
#   1) 수온 > ts.water_temp_critical_high  → 포그 OFF (안전 — 뜨거운 물 분사 방지)
#   2) 실내온도 > ts.temp_critical_high     → 결합 보류 (실내 추가 가열 방지)
#   3) 수온 ≥ ts.water_temp_low             → 포그 ON (가열된 수온의 열기 유입)
#   4) 그 외 (수온 < ts.water_temp_low)     → 포그 OFF (차가운 안개 무의미)
#
# devices 를 in-place 수정하고 동일 객체를 반환한다.
# ═══════════════════════════════════════════════════════════════════════════════
def _apply_fog_coupling(devices, sensor_data, *, scope="", ts=None):
    if not isinstance(devices, dict):
        return devices

    t = _ts(ts)
    indoor_temp = sensor_data.get('indoor_temperature') if sensor_data else None
    water_temp = sensor_data.get('water_temperature') if sensor_data else None
    prev = devices.get('fog_occurs_flag')

    # (1) 안전 — 수온과열: 뜨거운 물 분사 방지 (절대 안전 가드, 유지)
    if water_temp is not None and water_temp > t.water_temp_critical_high:
        if prev:
            logger.warning(
                f"{scope}[안전가드] 수온과열({water_temp}℃ > {t.water_temp_critical_high}) → "
                f"포그생성 강제 OFF"
            )
        devices['fog_occurs_flag'] = False
        return devices

    # (2) 안전 — 실내 고온비상: 호출자 결정 보존 (절대 안전 가드, 유지)
    if indoor_temp is not None and indoor_temp > t.temp_critical_high:
        return devices

    # [2026-05-01] 효율 룰 (3)·(4) 제거 — LLM 자율 판단 영역.
    # 사유:
    #   기존: 수온 ≥ low → 포그 ON 강제 / 수온 < low → 포그 OFF 강제.
    #   문제: 임계값 0.5℃ 미달이라도 무조건 OFF — LLM 이 "곧 도달, 가열 보조 위해
    #         미리 ON" 같은 컨텍스트 판단을 못함. 사용자 자율성 요구에 반함.
    #   변경: 수온과열·실내고온 안전 가드만 남기고 효율은 LLM(_call_llm) 결정에 위임.
    #   비상제어(LLM SKIP) 분기는 _build_device_settings 가 직접 fog 결정하므로 영향 없음.
        devices['fog_occurs_flag'] = False
    return devices


# ═══════════════════════════════════════════════════════════════════════════════
# 64케이스 장치 결정: 온도/습도 → (water_heater, fog_pump)
# [2026-04-27] 실내히터·히터밸브 미사용 — 저온 케이스에서도 수온히터만 ON.
# [2026-04-28] 수온히터 ON 시 포그생성도 항상 동반 ON — 가열된 탱크 수온의 열기를
#   재배사로 유입시키는 매개체가 포그. 온도가 실내습도보다 우선이므로, 저온+고습
#   조합이라도 포그를 ON 으로 유지(포그 자체는 가습이지만 가열 효과가 우선).
# ═══════════════════════════════════════════════════════════════════════════════
def _determine_devices(temp_state, humidity_state):
    if temp_state == 'low':
        return True, True

    elif temp_state == 'high':
        if humidity_state == 'low':
            return False, True
        else:
            return False, False

    else:
        if humidity_state == 'low':
            return False, True
        else:
            return False, False


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
# ────────────────────────────────────────────────────────────────────
# [2026-04-28 rev2] ts 의 동적 임계값으로 비상 판단. ts None 이면 폴백.
# Returns: (is_emergency, device_settings, circulation_mode, water_temp_only)
# ────────────────────────────────────────────────────────────────────
def _check_emergency(sensor_data, ts=None):
    t = _ts(ts)
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')

    # 온도 우선 — 저온비상은 수온히터+포그 ON 후 _apply_fog_coupling 후처리로 정정
    if indoor_temp is not None and indoor_temp < t.temp_critical_low:
        return True, _build_device_settings(water_heater=True, fog=True), '내부순환', False

    if indoor_temp is not None and indoor_temp > t.temp_critical_high:
        return True, _build_device_settings(), '배기순환', False

    # 습도
    if indoor_humidity is not None and indoor_humidity < t.humidity_critical_low:
        return True, _build_device_settings(water_heater=True, fog=True), '내부순환', False

    if indoor_humidity is not None and indoor_humidity > t.humidity_critical_high:
        return True, _build_device_settings(), '배기순환', False

    # CO2
    if co2 is not None and co2 > t.co2_critical_high:
        return True, _build_device_settings(), '배기순환', False

    # 수온 비상 (수온히터만 제어, 다른 장치 유지)
    # [2026-05-01] drainage_motor_flag 결합 룰 — 수온히터 ON 시 가온 위해 OFF, OFF 시 ON.
    if water_temp is not None and water_temp < t.water_temp_critical_low:
        return True, {'water_heater_flag': True, 'fog_occurs_flag': True,
                      'drainage_motor_flag': False}, None, True

    if water_temp is not None and water_temp > t.water_temp_critical_high:
        return True, {'water_heater_flag': False, 'fog_occurs_flag': False,
                      'drainage_motor_flag': True}, None, True

    return False, None, None, False
