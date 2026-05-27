# ════════════════════════════════════════════════════════════════════════════════
# 환경 판단 로직 (순수 함수) — 센서값 → 장치 결정 / 순환 모드 / 비상 판단
# L6 계층 모듈. 외부 부작용 없음 (DB/GPIO 호출 없음). 단위 테스트 용이.
# --->
# _classify: 센서값을 low/normal/high로 분류
# _is_external_normal: 외부 온습도가 정상 범위인지 판별
# _is_internal_abnormal: 내부 온습도/CO2 이상 여부 판별
# _build_device_settings: 4대 장치 설정 딕셔너리 생성 헬퍼
# _determine_devices: 64케이스 장치 결정 (온도/습도 → water_heater/fog/heater/damper)
# _determine_circulation: 64케이스 순환모드 결정 (내부/외부/배기순환)
# _check_emergency: 임계값 이탈 시 비상 릴레이 설정 반환 (온도·CO2)
# apply_water_safety: 수온계 안전 4케이스 (혹한 락아웃/온난 히터금지/혹서 냉각/배수=포그 세트)
# ════════════════════════════════════════════════════════════════════════════════
import os

from agri_ai_core.logs import setup_logger
# 센서 임계값 하드코딩 금지 — control_common 의 임계 상수 직접 import 금지.
# 모든 임계값은 ai_thresholds.get_thresholds() 또는 호출자가 전달한 ts 인자로
# 사용. ts 가 None 이어도 안전하도록 get_global_default() 폴백.
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
# 계절 자동 판단 (사용자 정의 룰).
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
# ts None 이면 ai_thresholds.get_global_default() 폴백.
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
# drainage 는 LLM 자율 판단 영역 — 본 함수는 비상시(운용모드 fallback) 안전 폴백
# 결정만 담당. 비상시에도 mappers.py 룰을 지키되, LLM 정상 분기에서는 LLM 이 직접 결정.
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
# 수온계 안전 — 농장주 지정 3케이스 (⛔ 이 3가지 외 수온히터/배수/포그 코드 개입 금지)
#
#   A) 외부 ≤ 1℃ 이고 수온 ≥ 50℃: 수온히터 강제 OFF — 수온 ≤ 30℃ 될 때까지 유지(락아웃)
#   B) 외부 ≥ 10℃: 수온히터 무조건 OFF
#   C) 외부 ≥ 29℃ (여름 냉각 상황): 배수밸브 무조건 ON,
#      수온이 지하수 온도(기본 15℃, 허용오차 +1℃)에 도달하면 포그 ON
#      — 차가운 지하수 미스트로 실내 냉각. 배수 강제는 이 케이스에서만.
#   D) 배수=포그 세트 (농장주 룰): 여름냉각(C)·수온과열이 아닌데 포그 OFF 인 채
#      배수만 ON 이면 배수 OFF — "포그 없는 배수는 지하수 낭비". LLM 자기오답
#      학습으로 프롬프트 룰이 무시되는 것을 물리 룰로 확정 (2026-07-16).
#
# 임계값은 env 로 조정 가능. 그 외 수온계 판단은 전량 LLM 자율 영역.
# devices 를 in-place 수정하고 (devices, corrections) 를 반환한다.
# ═══════════════════════════════════════════════════════════════════════════════
WS_OUTDOOR_FREEZE_C  = float(os.getenv('WS_OUTDOOR_FREEZE_C', '1.0'))
WS_WATER_TRIP_C      = float(os.getenv('WS_WATER_TRIP_C', '50.0'))
WS_WATER_RELEASE_C   = float(os.getenv('WS_WATER_RELEASE_C', '30.0'))
WS_OUTDOOR_WARM_C    = float(os.getenv('WS_OUTDOOR_WARM_C', '10.0'))
WS_OUTDOOR_HOT_C     = float(os.getenv('WS_OUTDOOR_HOT_C', '29.0'))
WS_GROUNDWATER_C     = float(os.getenv('WS_GROUNDWATER_TEMP_C', '15.0'))
WS_GROUNDWATER_TOL_C = float(os.getenv('WS_GROUNDWATER_TOL_C', '1.0'))
_WS_HEATER_LOCKOUT = {}   # "farm:house" → True (케이스 A 락아웃 상태)

# 저온(비상) 포그 hysteresis — 수온이 (실내 + 이 값) 이상일 때만 포그 ON.
# 정상 경로 프롬프트 §3 와 동일 기준으로 통일(경로별 임계 불일치 방지).
LOWTEMP_FOG_HYST_C = float(os.getenv('LOWTEMP_FOG_HYST_C', '5.0'))


def apply_water_safety(devices, sensor_data, farm_id=None, house_id=None, *, scope=""):
    if not isinstance(devices, dict):
        return devices, []
    s = sensor_data or {}

    def _f(key):
        try:
            v = s.get(key)
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    outdoor = _f('outdoor_temperature')
    water = _f('water_temperature')
    corrections = []
    lock_key = f"{farm_id}:{house_id}"

    # A) 혹한 수온과열 락아웃 — 트립 후 수온 ≤ 30℃ 까지 히터 금지
    if (outdoor is not None and water is not None
            and outdoor <= WS_OUTDOOR_FREEZE_C and water >= WS_WATER_TRIP_C):
        _WS_HEATER_LOCKOUT[lock_key] = True
    if _WS_HEATER_LOCKOUT.get(lock_key):
        if water is not None and water <= WS_WATER_RELEASE_C:
            _WS_HEATER_LOCKOUT.pop(lock_key, None)
        elif devices.get('water_heater_flag'):
            devices['water_heater_flag'] = False
            corrections.append(
                f"[A] 혹한 수온과열 락아웃(수온 {water}℃ > {WS_WATER_RELEASE_C}℃) → 수온히터 OFF")

    # B) 외부 온난 — 수온히터 무조건 OFF
    if (outdoor is not None and outdoor >= WS_OUTDOOR_WARM_C
            and devices.get('water_heater_flag')):
        devices['water_heater_flag'] = False
        corrections.append(
            f"[B] 외부 {outdoor}℃ ≥ {WS_OUTDOOR_WARM_C}℃ → 수온히터 OFF")

    # C) 혹서 냉각 — 배수 강제 ON + 수온이 지하수 온도 도달 시 포그 ON
    if outdoor is not None and outdoor >= WS_OUTDOOR_HOT_C:
        if not devices.get('drainage_motor_flag'):
            devices['drainage_motor_flag'] = True
            corrections.append(
                f"[C] 외부 {outdoor}℃ ≥ {WS_OUTDOOR_HOT_C}℃ → 배수밸브 ON (지하수 냉각)")
        if (water is not None
                and water <= WS_GROUNDWATER_C + WS_GROUNDWATER_TOL_C
                and not devices.get('fog_occurs_flag')):
            devices['fog_occurs_flag'] = True
            corrections.append(
                f"[C] 수온 {water}℃ ≈ 지하수({WS_GROUNDWATER_C}℃) → 포그 ON (냉각 미스트)")

    # D) 배수=포그 세트 — 여름냉각(C)·수온과열이 아닌데 포그 OFF + 배수 ON 이면 배수 OFF.
    #    ("포그 없는 배수는 무의미" 농장주 룰. C 케이스는 위에서 이미 배수를 켰으므로
    #     여기 조건(외부<29℃)에서 배수 ON 은 근거 없는 잔존 → 해제.)
    if (outdoor is not None and outdoor < WS_OUTDOOR_HOT_C
            and not devices.get('fog_occurs_flag')
            and devices.get('drainage_motor_flag')
            and not devices.get('water_heater_flag')):
        _overheat = False
        if water is not None:
            try:
                from agri_ai_core.src.control.ai_thresholds import get_thresholds
                _wth = get_thresholds(farm_id, house_id).water_temp_critical_high
                _overheat = _wth is not None and water >= float(_wth)
            except Exception:
                _overheat = False
        if not _overheat:
            devices['drainage_motor_flag'] = False
            corrections.append(
                f"[D] 포그 OFF·외부 {outdoor}℃<{WS_OUTDOOR_HOT_C}℃·수온정상인데 배수 ON "
                f"→ 배수 OFF (배수는 포그와 세트)")

    for c in corrections:
        logger.warning(f"{scope}[수온계안전] {c}")
    return devices, corrections

# ═══════════════════════════════════════════════════════════════════════════════
# 고습 → 포그 강제 OFF (농장주 절대룰). ⛔ 포그는 습도를 높이므로 냉각 상황이 아닌
# 고습(습도 ≥ 적정상한)에는 어떤 제어자(Agent/AI/수동)도 포그를 켠 채로 둘 수 없다.
# relay_manager 최종 관문(모든 모드 공통)에서 강제 → 비정합 상태 자체가 기록 불가.
#   냉각 예외(포그가 냉각 목적일 수 있어 건드리지 않음):
#     · 고온: 실내온도 > 온도 상한   · 여름: 외부온도 ≥ WS_OUTDOOR_HOT_C(29℃)
# relay_values 는 pin(relay_*st_flag) 키. (relay_values, corrections) 반환.
# ═══════════════════════════════════════════════════════════════════════════════
def apply_humidity_fog_guard(relay_values, sensor_data, ts, pin_map):
    corrections = []
    try:
        fog_pin = (pin_map or {}).get('fog_occurs_flag')
        if not fog_pin or fog_pin not in relay_values or not relay_values.get(fog_pin):
            return relay_values, corrections   # 포그 이미 OFF → 무관

        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        s = sensor_data or {}
        hum = _f(s.get('indoor_humidity'))
        it = _f(s.get('indoor_temperature'))
        ot = _f(s.get('outdoor_temperature'))
        hum_high = _f(getattr(ts, 'humidity_high', None))
        temp_high = _f(getattr(ts, 'temp_high', None))

        if hum is None or hum_high is None or hum < hum_high:
            return relay_values, corrections   # 고습 아님
        if it is not None and temp_high is not None and it > temp_high:
            return relay_values, corrections   # 고온 냉각 — 포그 유지
        if ot is not None and ot >= WS_OUTDOOR_HOT_C:
            return relay_values, corrections   # 여름 냉각 — 포그 유지

        relay_values[fog_pin] = False
        corrections.append(f"고습 {hum}%(>={hum_high}%) + 냉각상황 아님 -> 포그({fog_pin}) 강제 OFF")
    except Exception as e:
        corrections.append(f"습도-포그 가드 오류: {e}")
    return relay_values, corrections



# ════════════════════════════════════════════════════════════════════
# 계절 분기 override (사용자 정의 룰).
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
# 실내히터·히터밸브 미사용 — 저온 케이스에서도 수온히터만 ON.
# 수온히터 ON 시 포그생성도 항상 동반 ON — 가열된 탱크 수온의 열기를
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
# ts 의 동적 임계값으로 비상 판단. ts None 이면 폴백.
# Returns: (is_emergency, device_settings, circulation_mode, water_temp_only)
# ────────────────────────────────────────────────────────────────────
def _check_emergency(sensor_data, ts=None):
    t = _ts(ts)
    indoor_temp = sensor_data.get('indoor_temperature')
    indoor_humidity = sensor_data.get('indoor_humidity')
    co2 = sensor_data.get('co2')
    water_temp = sensor_data.get('water_temperature')

    # 저온비상 — 수온히터 ON. fog 는 수온 ≥ (실내 + LOWTEMP_FOG_HYST_C) 일 때만 ON
    # (정상 경로 프롬프트 §3 hysteresis 와 동일 기준). drainage 는 가온 위해 OFF.
    if indoor_temp is not None and indoor_temp < t.temp_critical_low:
        fog_on = (water_temp is not None and water_temp >= indoor_temp + LOWTEMP_FOG_HYST_C)
        return True, _build_device_settings(water_heater=True, fog=fog_on), '내부순환', False

    # ────────────────────────────────────────────────────────────────────
    # 사용자 정책 #2 고온비상 — 외기 조건 분기.
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

    # 습도 — 사용자 정책 #5/#6: 강제 처리 안 함, LLM 자율 판단 위임.
    # 습도 단독 비상은 emergency 분기로 진입하지 않고 LLM 호출로 흘러
    # system_prompt 의 우선순위 룰(온도 > 습도 > CO2) 에 따라 결정.

    # CO2
    if co2 is not None and co2 > t.co2_critical_high:
        return True, _build_device_settings(), '배기순환', False

    # 수온계(수온히터/배수/포그)는 비상 분기 없음 — apply_water_safety 3케이스 전담.

    return False, None, None, False


# ════════════════════════════════════════════════════════════════════
# 사용자 원칙 — "운용모드 결정 후 비상 오버라이드" 구조
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

    # 수온계(수온히터/배수/포그)는 비상 오버라이드 없음 — apply_water_safety 3케이스 전담.

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
