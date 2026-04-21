# ═══════════════════════════════════════════════════════════════════════
# 제어 모듈 공통 상수, 매핑, 유틸리티.
# manual_control, ai_control, relay_manager 등 제어 모듈이 공유하는
# 상수·핀맵·로깅·포맷팅 함수를 제공한다.
# [2026-04-27] 실내히터·히터밸브 전 시스템 미사용 — 모든 매핑/라벨/별칭/쿨다운
# 인프라 제거. relay_9 / relay_15 는 다른 용도로 재배정될 예정.
# --->
# resolve_device_alias: 장치명 또는 한글 별칭을 시멘틱 flag 이름으로 변환
# set_llm_relay_lock / is_llm_relay_locked / clear_llm_relay_lock: LLM 잠금
# get_pin_map / reverse_pin_map: house_id 별 시멘틱↔relay flag 매핑
# format_sensor_parts / format_relay_on_str / format_relay_off_str: 로그 포맷
# format_device_decision: 장치 결정 포맷
# ═══════════════════════════════════════════════════════════════════════
import os


# ══════════════════
# 릴레이 핀 수
# ══════════════════
RELAY_COUNT = 16


# ════════════════════════════════════════════════════════════════════════════
# ⚠ DEPRECATED — 환경 제어 임계값 (직접 사용 금지)
# [2026-04-28 rev2] 사용자 지시: "센서값은 절대 하드코딩 금지. 테이블 컬럼 값만
# 변경하면 되어야 한다."
# 모든 임계값은 SENSOR_M_SETTING 테이블에서 조회되어야 하며, 호출자는
#   from agri_ai_core.src.control.ai_thresholds import get_thresholds
#   ts = get_thresholds(farm_id, house_id)
# 패턴으로 ts.temp_low / ts.temp_critical_high 등을 사용해야 한다.
#
# 본 상수들은 ai_thresholds 의 _LAST_RESORT 폴백과 동일한 값으로 유지되며,
# DB 마이그레이션 전 호환·외부 통합테스트(라즈베리파이 등) 용으로만 남겨둠.
# 신규 코드에서는 import 하지 말 것.
# ════════════════════════════════════════════════════════════════════════════
TEMP_LOW = 27               # @deprecated → ts.temp_low
TEMP_HIGH = 30              # @deprecated → ts.temp_high
TEMP_CRITICAL_LOW = 25      # @deprecated → ts.temp_critical_low
TEMP_CRITICAL_HIGH = 33     # @deprecated → ts.temp_critical_high

HUMIDITY_LOW = 75           # @deprecated → ts.humidity_low
HUMIDITY_HIGH = 85          # @deprecated → ts.humidity_high
HUMIDITY_CRITICAL_LOW = 70  # @deprecated → ts.humidity_critical_low
HUMIDITY_CRITICAL_HIGH = 95 # @deprecated → ts.humidity_critical_high

CO2_LOW = 300               # @deprecated → ts.co2_low
CO2_HIGH = 1200             # @deprecated → ts.co2_high
CO2_CRITICAL_HIGH = 1500    # @deprecated → ts.co2_critical_high

WATER_TEMP_LOW = 40              # @deprecated → ts.water_temp_low
WATER_TEMP_HIGH = 55             # @deprecated → ts.water_temp_high
WATER_TEMP_CRITICAL_LOW = 35     # @deprecated → ts.water_temp_critical_low
WATER_TEMP_CRITICAL_HIGH = 60    # @deprecated → ts.water_temp_critical_high

BUDDING_TEMP_LOW = 29   # @deprecated → ts.budding_temp_low
BUDDING_TEMP_HIGH = 33  # @deprecated → ts.budding_temp_high

# Phase 1(밸브) → Phase 2(팬) 사이 대기 시간 (초).
# 인터록 게이트(interlock.VALVE_FAN_INTERLOCK_SEC = 10) 통과 보장을 위한 여유 +5초.
# 이 값을 VALVE_FAN_INTERLOCK_SEC 미만으로 두면 Phase 2 의 fan ON 이 게이트에
# 차단되어 mode 전환이 실패하므로 반드시 ≥ VALVE_FAN_INTERLOCK_SEC + safety margin.
DAMPER_FAN_DELAY_SEC = 15


# ══════════════════════════════════════
# Semantic name → relay_*st_flag 핀 매핑
# ══════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# [변경2 · 2026-04-19] 1/3호 STANDARD — 웹 UI/현장 배선 기준으로 11↔14 교환
#   원본: air_intake_valve_flag → relay_11, air_exhaust_valve_flag → relay_14
#   변경 후: air_intake → relay_14, air_exhaust → relay_11
# ──────────────────────────────────────────────────────────────────────────────
# [변경4 · 2026-04-30] STANDARD 핀맵을 RELAY_FIELD_MAPPING (5-tuple) 에서 자동 생성.
#   하드코딩 제거 — 매핑 테이블이 단일 진실 원천. 핀 변경 시 mappers.py 만 수정.
# [2026-04-27] relay_9 (구 실내히터) / relay_15 (구 히터밸브) 매핑 제거 — 전 재배사
# 에서 미연결, 다른 용도로 사용 예정. RELAY_FIELD_MAPPING 에서 제외되어 자동
# 누락되므로 어떤 모드에서도 ON 불가.
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.config.mappers import standard_pin_map as _standard_pin_map

RELAY_PIN_MAP_STANDARD = _standard_pin_map()

# ══════════════════════════════════════════════════════════════════════════════
# [변경1 · 2026-04-19] 2호 전용 +1 shift — 웹 UI/DB 컬럼 번호와 장비 의미 일치화
#   원본: air_circulation_valve_flag → relay_9st_flag, ..., indoor_heater_valve_flag → relay_14st_flag
#   변경 후: 순환 valve 이후 모든 플래그가 +1 shift
# ──────────────────────────────────────────────────────────────────────────────
# [변경5 · 2026-04-30] E 핀맵을 RELAY_FIELD_MAPPING_E (5-tuple) 에서 자동 생성.
#   하드코딩 제거 — 매핑 테이블이 단일 진실 원천. 핀 변경 시 mappers.py 만 수정.
# [2026-04-27] relay_15 (구 히터밸브) 매핑 제거 — 전 재배사 미연결/타용도 예정.
# RELAY_FIELD_MAPPING_E 에서 제외되어 자동 누락되므로 어떤 모드에서도 ON 불가.
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.config.mappers import (
    e_pin_map as _e_pin_map,
    semantic_labels as _semantic_labels,
    device_aliases as _device_aliases,
)

RELAY_PIN_MAP_E = _e_pin_map()


# ══════════════════════════════════════════════════════════════════════════════
# [변경3] 웹 UI(RelayDashboard) 라벨 용어로 전 시스템 통일
# [변경5 · 2026-04-30] mappers.semantic_labels() 자동 생성 — STANDARD/E 머지.
# ══════════════════════════════════════════════════════════════════════════════
SEMANTIC_LABELS = _semantic_labels()

# ──────────────────────────────────────────────────────────────────────────────
# 한글 별칭 → 시멘틱 flag 매핑 (Web UI 이름 기준)
# [변경3] 전 시스템 용어 통일 — 웹 UI 표시 용어와 축약형만 유지.
# [변경5 · 2026-04-30] mappers.device_aliases() 자동 생성 — STANDARD/E 매핑의
# ──────────────────────────────────────────────────────────────────────────────
DEVICE_ALIASES = _device_aliases()

# ────────────────────────────────────────────────────────────────────
# 장치명 또는 한글 별칭을 시멘틱 flag 이름으로 변환.
# 이미 flag 이름이면 그대로 반환, 한글이면 DEVICE_ALIASES 에서 조회.
# ────────────────────────────────────────────────────────────────────
def resolve_device_alias(name):
    if not name:
        return name
    if name in SEMANTIC_LABELS:
        return name
    return DEVICE_ALIASES.get(name, name)


# ════════════════════════════════════
# 순환 모드 정의 (밸브 → 15초 후 → 팬)
# [변경7 · 2026-04-30] 'effect' 메타 추가 — LLM 프롬프트 자동 생성 시 모드별 효과
# 설명도 함께 노출 (mappers.circulation_modes_text 가 본 dict 를 SSOT 로 사용).
# ════════════════════════════════════
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
        'effect': '모든 흐름 정지 (밸브는 모두 ON, 팬만 OFF)',
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
        'effect': '내부 공기 순환, 온습도 유지 (외부 격리)',
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
        'effect': '내부공기를 외부공기로 대체 (전면 환기)',
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
        'effect': '외부공기 유입으로 CO2 하락 (양압)',
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
        'effect': '내부공기 배출로 CO2 하락 (음압)',
    },
}


# ═════════════════════════════════════════════════════════════════════
# LLM 제어 잠금 (자동제어 스케줄러 충돌 방지)
# LLM이 릴레이를 제어한 후 일정 시간 동안 해당 재배사의 자동제어를 억제
# ═════════════════════════════════════════════════════════════════════
import threading
from datetime import datetime, timedelta

_LLM_LOCK_DURATION_SEC = int(os.environ.get("LLM_RELAY_LOCK_SEC", "60"))
_llm_relay_locks = {}  # key: (farm_id, house_id) → value: datetime (잠금 만료 시각)
_llm_lock_mutex = threading.Lock()


# ────────────────────────────────────────────────────────────────────
# LLM 제어 잠금 설정 — 자동제어 스케줄러 충돌 방지용 만료시각 기록.
# ────────────────────────────────────────────────────────────────────
def set_llm_relay_lock(farm_id, house_id, duration_sec=None):
    if duration_sec is None:
        duration_sec = _LLM_LOCK_DURATION_SEC
    key = (str(farm_id), str(house_id))
    with _llm_lock_mutex:
        _llm_relay_locks[key] = datetime.now() + timedelta(seconds=duration_sec)


# ────────────────────────────────────────────────────────────────────
# LLM 제어 잠금 활성 여부 — 만료된 잠금은 자동 제거 후 False.
# ────────────────────────────────────────────────────────────────────
def is_llm_relay_locked(farm_id, house_id):
    key = (str(farm_id), str(house_id))
    with _llm_lock_mutex:
        expire = _llm_relay_locks.get(key)
        if expire and datetime.now() < expire:
            return True
        if expire:
            del _llm_relay_locks[key]
        return False


# ────────────────────────────────────────────────────────────────────
# LLM 제어 잠금 해제 — 즉시 자동제어 재개.
# ────────────────────────────────────────────────────────────────────
def clear_llm_relay_lock(farm_id, house_id):
    key = (str(farm_id), str(house_id))
    with _llm_lock_mutex:
        _llm_relay_locks.pop(key, None)


# ═══════════════════════════════════════════════════════
# 숫자로 변환 가능한 값을 정수로 반환, 실패 시 큰 수 반환
# ═══════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 숫자로 변환 가능한 값을 정수로 반환. 실패 시 큰 수(10^9) 반환 — 정렬용.
# ────────────────────────────────────────────────────────────────────
def to_sortable_int(value):
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


# ══════════════════════════════════════════
# 재배사 목록을 farm_id, hous_id 순으로 정렬
# ══════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 재배사 목록을 farm_id, hous_id 순으로 정렬.
# ────────────────────────────────────────────────────────────────────
def sort_houses(houses):
    return sorted(
        houses or [],
        key=lambda house: (
            to_sortable_int(house.get("farm_id")),
            to_sortable_int(house.get("hous_id")),
            str(house.get("hous_id") or ""),
        ),
    )


# ══════════════════
# 유틸리티 함수
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# [2026-04-28] 로그 식별자 형식: "0-99" (농장 0 · 재배사 99).
# 가독성·정렬·검색 편의 — order_label 이 있으면 그 앞에 붙는다.
# ────────────────────────────────────────────────────────────────────
def house_prefix(order_label="", farm_id=None, house_id=None):
    prefix = f"{order_label} " if order_label else ""
    if farm_id is None or house_id is None:
        return prefix.strip()
    return f"{prefix}{farm_id}-{house_id}"


# ────────────────────────────────────────────────────────────────────
# house_id 별 시멘틱 → relay 핀 dict 반환. 2호는 E타입, 그 외는 STANDARD.
# ────────────────────────────────────────────────────────────────────
def get_pin_map(house_id):
    if int(house_id) == 2:
        return RELAY_PIN_MAP_E
    return RELAY_PIN_MAP_STANDARD


# ────────────────────────────────────────────────────────────────────
# 핀 → 시멘틱 역매핑 dict 반환 (relay_*st_flag → semantic).
# ────────────────────────────────────────────────────────────────────
def reverse_pin_map(house_id):
    return {v: k for k, v in get_pin_map(house_id).items()}


# ══════════════════════════════════════════════════════════════════════════
# 미매핑 릴레이 강제 OFF — 핀맵에 등록되지 않은 relay_*st_flag 는 어떤 모드의
# raw_mode 쓰기에도 절대 ON 으로 남지 않도록 보정. 핀맵에서 시멘틱이 제거된
# 릴레이(예: relay_9, relay_15) 는 자동으로 이 필터에 의해 OFF 가 강제됨.
# [2026-04-27] DISABLED_SEMANTIC_FLAGS / apply_disabled_devices 인프라 제거 —
# 핀맵 자체에서 indoor_heater 매핑을 빼서 근본 차단 + 본 헬퍼로 raw_mode 보호.
# ══════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 핀맵에 없는 relay_*st_flag 를 False 로 강제. 반환: 강제 OFF 된 핀 리스트.
# relay_values 는 in-place 변경.
# ────────────────────────────────────────────────────────────────────
def force_off_unmapped_relays(house_id, relay_values):
    if not relay_values:
        return []
    mapped_pins = set(reverse_pin_map(house_id).keys())
    forced = []
    for i in range(1, RELAY_COUNT + 1):
        pin = f"relay_{i}st_flag"
        if pin in mapped_pins:
            continue
        if bool(relay_values.get(pin, False)):
            forced.append(pin)
        relay_values[pin] = False
    return forced


# ═══════════════════════════
# 공통 포맷팅 함수
# 센서값을 포맷 문자열로 변환
# ═══════════════════════════
# ────────────────────────────────────────────────────────────────────
# 센서 dict → "온도 25℃, 습도 80%, ..." 콤마 구분 문자열.
# include_outdoor=True 면 외부온/습 추가.
# ────────────────────────────────────────────────────────────────────
def format_sensor_parts(sensor_data, include_outdoor=False):
    if not sensor_data:
        return None

    fields = [
        ('indoor_temperature', '온도', '℃'),
        ('indoor_humidity', '습도', '%'),
        ('co2', 'CO2', 'ppm'),
        ('water_temperature', '수온', '℃'),
    ]
    if include_outdoor:
        fields.extend([
            ('outdoor_temperature', '외부온도', '℃'),
            ('outdoor_humidity', '외부습도', '%'),
        ])

    parts = []
    for key, label, unit in fields:
        v = sensor_data.get(key)
        parts.append(f"{label} {v}{unit}" if v is not None else f"{label} -")
    return ", ".join(parts)


# ═══════════════════════════════════════════
# ON/OFF 릴레이 이름 목록 (공통)
# on_state=True: ON 릴레이 (미매핑 핀도 포함)
# on_state=False: OFF 릴레이 (매핑된 핀만)
# ═══════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# ON/OFF 릴레이의 한글 라벨 list 반환 (공통 헬퍼).
# on_state=True: ON 릴레이 (미매핑 핀도 포함).
# on_state=False: OFF 릴레이 (매핑된 핀만).
# ────────────────────────────────────────────────────────────────────
def _get_relay_names(relay_data, house_id, on_state=True):
    if not relay_data:
        return []
    reverse = reverse_pin_map(house_id)
    names = []
    for i in range(1, RELAY_COUNT + 1):
        pin = f"relay_{i}st_flag"
        is_on = bool(relay_data.get(pin))
        if is_on == on_state:
            semantic = reverse.get(pin)
            if on_state or semantic:
                names.append(SEMANTIC_LABELS.get(semantic, pin))
    return names


# ────────────────────────────────────────────────────────────────────
# ON 상태 릴레이 한글 라벨 콤마 문자열. 모두 OFF 면 "전체 OFF".
# ────────────────────────────────────────────────────────────────────
def format_relay_on_str(relay_data, house_id):
    names = _get_relay_names(relay_data, house_id, on_state=True)
    return ", ".join(names) if names else "전체 OFF"


# ────────────────────────────────────────────────────────────────────
# OFF 상태 릴레이 한글 라벨 콤마 문자열. 모두 ON 이면 "전체 ON".
# ────────────────────────────────────────────────────────────────────
def format_relay_off_str(relay_data, house_id):
    names = _get_relay_names(relay_data, house_id, on_state=False)
    return ", ".join(names) if names else "전체 ON"


# ═════════════════════════════════════
# 장치 결정 내용을 ON/OFF 문자열로 변환
# ═════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 장치 결정 dict → "ON=[...], OFF=[...]" 한글 문자열.
# ────────────────────────────────────────────────────────────────────
def format_device_decision(devices):
    if not devices:
        return ""
    on_list = [SEMANTIC_LABELS.get(k, k) for k, v in devices.items() if v]
    off_list = [SEMANTIC_LABELS.get(k, k) for k, v in devices.items() if not v]
    on_str = ", ".join(on_list) if on_list else "없음"
    off_str = ", ".join(off_list) if off_list else "없음"
    return f"ON=[{on_str}], OFF=[{off_str}]"
