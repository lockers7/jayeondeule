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
# [2026-05-04 사용자 정의] 계절 자동 판단.
# 저온계절 = (내부 < 적정 하한) AND (외기 < 내부 온도) — 가열 필요한 환경
# 고온계절 = 그 외 — 정상 안 또는 외기가 내부 이상 (가열 불필요/냉각 필요)
# Returns: 'cold' (저온계절) / 'warm' (고온계절). None 입력 시 'warm' 폴백 (보수적).
# ────────────────────────────────────────────────────────────────────
def _determine_season(indoor_temp, outdoor_temp, ts=None):
    t = _ts(ts)
    if indoor_temp is None:
        return 'warm'
    if indoor_temp >= t.temp_low:
        return 'warm'
    if outdoor_temp is None:
        return 'cold'  # 외기 모르면 보수적으로 저온계절(가열 가능)
    return 'cold' if outdoor_temp < indoor_temp else 'warm'


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
#   직접 적용할 기회를 잃음. 본 함수는 비상시 (운용모드 fallback) 안전 폴백 결정만 담당.
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
    #   비상제어(운용모드 fallback) 분기는 _build_device_settings 가 직접 fog 결정하므로 영향 없음.
        devices['fog_occurs_flag'] = False
    return devices


# ════════════════════════════════════════════════════════════════════
# [2026-05-04 사용자 정의] 계절 분기 override.
# 64-케이스 결정 + fog_coupling 후 호출 → 계절별 룰 적용.
#
# 저온계절 (외기 < 내부 AND 내부 < 적정하한):
#   가열 시퀀스 적용 — 기존 64-케이스 결정 유지 (heater ON 등).
#   다만 "실내 ≥ 적정상한" 도달 시 heater OFF (효율).
#
# 고온계절:
#   - heater 절대 OFF (안전 + 가열 불필요)
#   - 내부 > 적정상한: fog ON + drainage ON + 내부순환 (지하수 15℃ 활용 냉각)
#   - 내부 ∈ [적정하한, 적정상한]: keep (장치 변경 없음, 64-케이스도 OFF 유지)
#
# 비상 우선은 호출자에서 apply_emergency_override 로 별도 강제.
# ════════════════════════════════════════════════════════════════════
def _apply_season_override(devices, circulation, season, indoor_temp, ts=None):
    if not isinstance(devices, dict):
        return devices, circulation
    t = _ts(ts)
    devices = dict(devices)
    if season == 'cold':
        # 저온계절 — 기존 결정 보존, 단 실내 ≥ 적정상한 도달 시 heater OFF 효율 룰
        if indoor_temp is not None and indoor_temp >= t.temp_high:
            devices['water_heater_flag'] = False
        return devices, circulation
    # 고온계절 — heater 절대 OFF
    devices['water_heater_flag'] = False
    if indoor_temp is not None and indoor_temp > t.temp_high:
        # 적극 냉각 — 지하수 분사 + 새 지하수 유입
        devices['fog_occurs_flag'] = True
        devices['drainage_motor_flag'] = True
        circulation = '내부순환'
    # 내부 정상범위 안: keep (devices 의 fog/drainage 는 64-케이스 결정 유지하되
    # heater 만 OFF 강제. 다른 장치 변경은 호출자가 keep 처리하도록 위임).
    return devices, circulation


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
    # [2026-05-17] 사용자 정책 — 운용모드 무관 모든 비상제어 skip.
    # 본 함수는 항상 "비상 아님" 반환. 복귀 시 본 early return 만 제거.
    return False, None, None, False
    t = _ts(ts)
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')

    # ────────────────────────────────────────────────────────────────────
    # [2026-05-04] 사용자 정책 #1 저온비상 — 실내+5℃ fog hysteresis.
    # 수온히터는 항상 ON. fog 는 (수온 ≥ 실내+5℃) 일 때만 ON.
    # 매 cycle 마다 수온 vs 실내+5℃ 비교 → 자동 hysteresis 효과 (5초 cycle 자체가
    # 채터링 흡수). drainage 는 가온 위해 OFF (heater ↔ drainage 상호배타).
    # ────────────────────────────────────────────────────────────────────
    if indoor_temp is not None and indoor_temp < t.temp_critical_low:
        # [2026-05-04 사용자 정의] hysteresis 5℃ → 3℃.
        fog_on = (water_temp is not None and water_temp >= indoor_temp + 3.0)
        return True, _build_device_settings(water_heater=True, fog=fog_on), '내부순환', False

    # ────────────────────────────────────────────────────────────────────
    # [2026-05-04] 사용자 정책 #2 고온비상 — 외기 조건 분기.
    # ① 외부온도가 정상 범위 안 → 외부순환 (외기로 자연 냉각, 장치 OFF).
    # ② 외부온도가 정상 범위 밖 → drainage ON + fog ON (탱크의 차가운
    #    지하수를 미스트로 분사하여 능동 냉각).
    # 두 분기 모두 수온히터는 OFF.
    # ────────────────────────────────────────────────────────────────────
    if indoor_temp is not None and indoor_temp > t.temp_critical_high:
        outdoor_temp = sensor_data.get('outdoor_temperature')
        outdoor_normal = (
            outdoor_temp is not None
            and t.temp_low <= outdoor_temp <= t.temp_high
        )
        if outdoor_normal:
            return True, _build_device_settings(), '외부순환', False
        # 외기 부적합 → 능동 냉각
        return True, {
            'water_heater_flag': False,
            'fog_occurs_flag': True,
            'drainage_motor_flag': True,
        }, '배기순환', False

    # 습도 — [2026-05-03] 사용자 정책 #5/#6: 강제 처리 안 함, LLM 자율 판단 위임.
    # 습도 단독 비상은 emergency 분기로 진입하지 않고 LLM 호출로 흘러
    # system_prompt 의 우선순위 룰(온도 > 습도 > CO2) 에 따라 결정.

    # CO2
    if co2 is not None and co2 > t.co2_critical_high:
        return True, _build_device_settings(), '배기순환', False

    # 수온 비상 (수온히터만 제어, 다른 장치 유지)
    # [2026-05-01] drainage_motor_flag 결합 룰 — 수온히터 ON 시 가온 위해 OFF, OFF 시 ON.
    if water_temp is not None and water_temp < t.water_temp_critical_low:
        return True, {'water_heater_flag': True, 'fog_occurs_flag': True,
                      'drainage_motor_flag': False}, None, True

    # [2026-05-04] 수온 과열비상 — 실내 온도 상황에 따라 분기.
    # ① 실내 가열 필요 또는 정상 (indoor_temp ≤ temp_high):
    #    수온히터만 OFF, 포그/배수는 현상유지 (LLM 자율 판단 보존).
    # ② 실내 냉각 필요 (indoor_temp > temp_high):
    #    수온히터 OFF + 배수밸브 ON (탱크에 차가운 새 지하수 주입 → 능동 냉각).
    if water_temp is not None and water_temp > t.water_temp_critical_high:
        if indoor_temp is not None and indoor_temp > t.temp_high:
            # 실내 고온 + 수온 과열 → 능동 냉각
            return True, {'water_heater_flag': False, 'fog_occurs_flag': False,
                          'drainage_motor_flag': True}, None, True
        # 실내 가열 필요/정상 + 수온 과열 → 수온히터만 OFF, 다른 장치 현상유지
        return True, {'water_heater_flag': False, 'fog_occurs_flag': None,
                      'drainage_motor_flag': None}, None, True

    return False, None, None, False


# ════════════════════════════════════════════════════════════════════
# [2026-05-04 Phase A] 사용자 원칙 — "운용모드 결정 후 비상 오버라이드" 구조
# 각 비상 정책의 핵심 강제 항목만 반환. None=운용 결정 보존.
# 호출자: 운용모드 결정 산출 후 본 override 를 위에 덮어쓰기 적용.
# ════════════════════════════════════════════════════════════════════


# ────────────────────────────────────────────────────────────────────
# 비상 가드 오버라이드 — 위반 항목만 강제, 나머지는 운용모드 결정 보존.
# Returns: (is_emergency, devices_override_dict, circulation_override, water_temp_only)
#   · devices_override_dict: 강제 장치만 명시 (예: {'water_heater_flag': False}).
#                            누락된 키 = 운용 결정 보존.
#   · circulation_override:  None=운용 결정 보존 / '문자열'=비상 우선 적용.
#   · water_temp_only:       True=수온 단독 비상 (운용 결정 대부분 유지).
# ────────────────────────────────────────────────────────────────────
def _emergency_override(sensor_data, ts=None):
    # [2026-05-17] 사용자 정책 — 운용모드 무관 모든 비상제어 skip.
    # 본 함수는 항상 "비상 아님" 반환. 복귀 시 본 early return 만 제거.
    return False, None, None, False
    t = _ts(ts)
    indoor_temp = sensor_data.get('indoor_temperature')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')
    outdoor_temp = sensor_data.get('outdoor_temperature')

    # ────────────────────────────────────────────────────────────────
    # 정책 #1 저온비상 — 수온히터 ON 강제. fog/drainage 는 운용 결정 보존
    # (운용모드/LLM 이 hysteresis 결정).
    # ────────────────────────────────────────────────────────────────
    if indoor_temp is not None and indoor_temp < t.temp_critical_low:
        return True, {'water_heater_flag': True}, '내부순환', False

    # ────────────────────────────────────────────────────────────────
    # 정책 #2 고온비상 — 수온히터 OFF 강제 + circulation 오버라이드.
    # 외기 정상 시 외부순환, 부적합 시 배기순환. 다른 장치는 운용 결정 보존
    # (단, 능동 냉각이 필요한 경우 운용모드/LLM 이 fog/drainage 결정).
    # ────────────────────────────────────────────────────────────────
    if indoor_temp is not None and indoor_temp > t.temp_critical_high:
        outdoor_normal = (
            outdoor_temp is not None
            and t.temp_low <= outdoor_temp <= t.temp_high
        )
        if outdoor_normal:
            return True, {'water_heater_flag': False}, '외부순환', False
        return True, {'water_heater_flag': False}, '배기순환', False

    # 정책 #5/#6 습도 — 강제 처리 없음 (사용자 정책)

    # ────────────────────────────────────────────────────────────────
    # 정책 #7 고CO2 — circulation 오버라이드만. 장치는 운용 결정 보존.
    # 외기+내기 정상 시 외부순환(외기 희석), 그 외 배기순환.
    # ────────────────────────────────────────────────────────────────
    if co2 is not None and co2 > t.co2_critical_high:
        outdoor_normal = (
            outdoor_temp is not None
            and t.temp_low <= outdoor_temp <= t.temp_high
        )
        indoor_normal = (
            indoor_temp is not None
            and t.temp_low <= indoor_temp <= t.temp_high
        )
        if outdoor_normal and indoor_normal:
            return True, {}, '외부순환', False
        return True, {}, '배기순환', False

    # ────────────────────────────────────────────────────────────────
    # 정책 #6 수온저하비상 — 수온히터 ON + drainage OFF 강제 (가온 위해 물 가둠).
    # ────────────────────────────────────────────────────────────────
    if water_temp is not None and water_temp < t.water_temp_critical_low:
        return True, {
            'water_heater_flag': True,
            'drainage_motor_flag': False,
        }, None, True

    # ────────────────────────────────────────────────────────────────
    # 정책 #4 수온과열비상 — 실내 온도 상황에 따라 분기.
    # ① 실내 ≤ temp_high (가열 필요/정상): water_heater OFF 만 강제.
    # ② 실내 > temp_high (냉각 필요): water_heater OFF + drainage ON 강제
    #    (탱크 식힘). fog 는 운용 결정 보존 (수온 식기 전 분사하면 위험할 수 있음).
    # ────────────────────────────────────────────────────────────────
    if water_temp is not None and water_temp > t.water_temp_critical_high:
        if indoor_temp is not None and indoor_temp > t.temp_high:
            return True, {
                'water_heater_flag': False,
                'drainage_motor_flag': True,
            }, None, True
        return True, {'water_heater_flag': False}, None, True

    return False, {}, None, False


# ────────────────────────────────────────────────────────────────────
# 운용모드 결정에 비상 오버라이드 적용 — 위반 항목만 덮어쓰고 나머지 보존.
# devices_user/circ_user: 운용모드(수동/알고리즘/AI) 가 산출한 결정.
# 반환: (final_devices, final_circulation, is_emergency).
# 비상 미트립 시 운용 결정 그대로 반환.
# ────────────────────────────────────────────────────────────────────
def apply_emergency_override(devices_user, circ_user, sensor_data, ts=None):
    is_emerg, dev_override, circ_override, _wto = _emergency_override(sensor_data, ts)
    if not is_emerg:
        return dict(devices_user or {}), circ_user, False
    # 운용 결정 위에 비상 위반만 덮어쓰기
    final_devices = dict(devices_user or {})
    final_devices.update(dev_override or {})
    final_circulation = circ_override if circ_override is not None else circ_user
    return final_devices, final_circulation, True
