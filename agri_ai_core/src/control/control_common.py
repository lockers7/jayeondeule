# ═══════════════════════════════════════════════════════════════════════
# 제어 모듈 공통 상수, 매핑, 유틸리티.
# manual_control, ai_control, relay_manager 등 제어 모듈이 공유하는
# 상수·핀맵·로깅·포맷팅 함수를 제공한다.
# --->
# check_heater_cooldown: 히터 연속 가동 체크
# update_heater_tracking: 히터 ON/OFF 상태 추적 업데이트
# reset_heater_state: 히터 상태 초기화
# resolve_device_alias: 장치명 또는 한글 별칭을 시멘틱 flag 이름으로 변환
# set_llm_relay_lock: set llm relay lock
# is_llm_relay_locked: is llm relay locked
# clear_llm_relay_lock: clear llm relay lock
# to_sortable_int: to sortable int
# sort_houses: sort houses
# house_prefix: house prefix
# get_pin_map: get pin map
# reverse_pin_map: reverse pin map
# format_sensor_parts: format sensor parts
# _get_relay_names: get relay names
# format_relay_on_str: format relay on str
# format_relay_off_str: format relay off str
# format_device_decision: format device decision
# ═══════════════════════════════════════════════════════════════════════
import os


# ══════════════════
# 릴레이 핀 수
# ══════════════════
RELAY_COUNT = 16


# ══════════════════
# 환경 제어 임계값
# ══════════════════
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

WATER_TEMP_LOW = 40
WATER_TEMP_HIGH = 55
WATER_TEMP_CRITICAL_LOW = 35
WATER_TEMP_CRITICAL_HIGH = 60

BUDDING_TEMP_LOW = 29
BUDDING_TEMP_HIGH = 33

HEATER_MAX_CONTINUOUS_MIN = 30
HEATER_COOLDOWN_MIN = 5

DAMPER_FAN_DELAY_SEC = 15


# ════════════════════════════════════════════════════════
# 히터 쿨다운 상태 관리 (ai_control ↔ manual_control 공유)
# ════════════════════════════════════════════════════════
from datetime import datetime, timedelta

_heater_state = {}


def check_heater_cooldown(farm_id, house_id):
    """히터 연속 가동 체크. Returns (사용가능, 쿨다운중)."""
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


def update_heater_tracking(farm_id, house_id, heater_on):
    """히터 ON/OFF 상태 추적 업데이트."""
    key = (farm_id, int(house_id))
    state = _heater_state.get(key, {})

    if state.get('cooling_until'):
        return

    if heater_on:
        if 'on_since' not in state:
            _heater_state[key] = {'on_since': datetime.now()}
    else:
        _heater_state[key] = {}


def reset_heater_state(farm_id, house_id):
    """히터 상태 초기화."""
    _heater_state[(farm_id, int(house_id))] = {}


# ══════════════════════════════════════
# Semantic name → relay_*st_flag 핀 매핑
# ══════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# [변경2 · 2026-04-19] 1/3호 STANDARD — 웹 UI/현장 배선 기준으로 11↔14 교환
#   원본: air_intake_valve_flag → relay_11, air_exhaust_valve_flag → relay_14
#   변경 후: air_intake → relay_14, air_exhaust → relay_11
# ══════════════════════════════════════════════════════════════════════════════
RELAY_PIN_MAP_STANDARD = {
    'water_heater_flag': 'relay_1st_flag',
    'fog_occurs_flag': 'relay_2st_flag',
    'drainage_motor_flag': 'relay_3st_flag',
    'intake_fan_flag': 'relay_5st_flag',
    'exhaust_fan_flag': 'relay_6st_flag',
    'lighting_flag': 'relay_7st_flag',
    'irrigation_flag': 'relay_8st_flag',
    'indoor_heater_flag': 'relay_9st_flag',
    'air_circulation_valve_flag': 'relay_10st_flag',
    'air_intake_valve_flag':   'relay_14st_flag',  # [변경2] 11 → 14
    'air_exhaust_valve_flag':  'relay_11st_flag',  # [변경2] 14 → 11
    'indoor_heater_valve_flag': 'relay_15st_flag',
}

# ══════════════════════════════════════════════════════════════════════════════
# [변경1 · 2026-04-19] 2호 전용 +1 shift — 웹 UI/DB 컬럼 번호와 장비 의미 일치화
#   원본: air_circulation_valve_flag → relay_9st_flag, ..., indoor_heater_valve_flag → relay_14st_flag
#   변경 후: 순환 valve 이후 모든 플래그가 +1 shift
# ══════════════════════════════════════════════════════════════════════════════
RELAY_PIN_MAP_E = {
    'water_heater_flag': 'relay_1st_flag',
    'fog_occurs_flag': 'relay_2st_flag',
    'radiator_flag': 'relay_3st_flag',
    'lighting_flag': 'relay_5st_flag',
    'irrigation_flag': 'relay_6st_flag',
    'intake_fan_flag': 'relay_7st_flag',
    'exhaust_fan_flag': 'relay_8st_flag',
    'air_circulation_valve_flag': 'relay_10st_flag',  # [변경1] 9 → 10
    'air_intake_valve_flag':      'relay_11st_flag',  # [변경1] 10 → 11
    'air_exhaust_valve_flag':     'relay_12st_flag',  # [변경1] 11 → 12
    'drainage_motor_flag':        'relay_13st_flag',  # [변경1] 12 → 13
    # [변경4 · 2026-04-20] 2호 relay_14 는 현장 배선 미연결 → 미정의(제어 skip).
    #   기존 indoor_heater_flag → relay_14 매핑 제거. E타입엔 실내히터 없음.
    #   environment_logic 이 indoor_heater_flag=True 를 결정해도 set_relay_value에서
    #   핀맵 miss 로 조용히 skip 됨 (relay_manager.py:110 경고 로그만).
    'indoor_heater_valve_flag':   'relay_15st_flag',  # [변경1] 14 → 15
}


# [변경3] 웹 UI(RelayDashboard) 라벨 용어로 전 시스템 통일
SEMANTIC_LABELS = {
    'water_heater_flag':          '수온히터',
    'fog_occurs_flag':            '포그생성',
    'drainage_motor_flag':        '배수밸브',
    'intake_fan_flag':            '흡입팬',
    'exhaust_fan_flag':           '배출팬',
    'lighting_flag':              '조명',
    'irrigation_flag':            '관수',
    'indoor_heater_flag':         '실내히터',
    'indoor_heater_valve_flag':   '히터밸브',
    'air_circulation_valve_flag': '순환밸브',
    'air_intake_valve_flag':      '흡입밸브',
    'air_exhaust_valve_flag':     '배출밸브',
    'radiator_flag':              '라디에이터',
}

# 한글 별칭 → 시멘틱 flag 매핑 (Web UI 이름 기준)
# [변경3] 전 시스템 용어 통일 — 웹 UI 표시 용어와 축약형만 유지.
DEVICE_ALIASES = {
    # water_heater_flag
    '수온히터': 'water_heater_flag',
    '칠러': 'water_heater_flag',
    '칠러1': 'water_heater_flag',
    '칠러Ⅰ': 'water_heater_flag',
    # fog_occurs_flag
    '포그생성': 'fog_occurs_flag',
    '포그': 'fog_occurs_flag',
    # drainage_motor_flag
    '배수밸브': 'drainage_motor_flag',
    '배수': 'drainage_motor_flag',
    # intake_fan_flag
    '흡입팬': 'intake_fan_flag',
    '흡입': 'intake_fan_flag',
    # exhaust_fan_flag
    '배출팬': 'exhaust_fan_flag',
    '배출': 'exhaust_fan_flag',
    # lighting_flag
    '조명': 'lighting_flag',
    'light': 'lighting_flag',
    'lighting': 'lighting_flag',
    # irrigation_flag
    '관수': 'irrigation_flag',
    'irrigation': 'irrigation_flag',
    # indoor_heater_flag
    '실내히터': 'indoor_heater_flag',
    '히터': 'indoor_heater_flag',
    # indoor_heater_valve_flag
    '히터밸브': 'indoor_heater_valve_flag',
    # air_circulation_valve_flag
    '순환밸브': 'air_circulation_valve_flag',
    # air_intake_valve_flag
    '흡입밸브': 'air_intake_valve_flag',
    # air_exhaust_valve_flag
    '배출밸브': 'air_exhaust_valve_flag',
    # radiator_flag 별칭
    '라디에이터': 'radiator_flag',
}

def resolve_device_alias(name):
    """장치명 또는 한글 별칭을 시멘틱 flag 이름으로 변환.
    이미 flag 이름이면 그대로 반환, 한글이면 DEVICE_ALIASES에서 조회."""
    if not name:
        return name
    if name in SEMANTIC_LABELS:
        return name
    return DEVICE_ALIASES.get(name, name)


# ════════════════════════════════════
# 순환 모드 정의 (밸브 → 15초 후 → 팬)
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


# ═════════════════════════════════════════════════════════════════════
# LLM 제어 잠금 (자동제어 스케줄러 충돌 방지)
# LLM이 릴레이를 제어한 후 일정 시간 동안 해당 재배사의 자동제어를 억제
# ═════════════════════════════════════════════════════════════════════
import threading
from datetime import datetime, timedelta

_LLM_LOCK_DURATION_SEC = int(os.environ.get("LLM_RELAY_LOCK_SEC", "60"))
_llm_relay_locks = {}  # key: (farm_id, house_id) → value: datetime (잠금 만료 시각)
_llm_lock_mutex = threading.Lock()


def set_llm_relay_lock(farm_id, house_id, duration_sec=None):
    if duration_sec is None:
        duration_sec = _LLM_LOCK_DURATION_SEC
    key = (str(farm_id), str(house_id))
    with _llm_lock_mutex:
        _llm_relay_locks[key] = datetime.now() + timedelta(seconds=duration_sec)


def is_llm_relay_locked(farm_id, house_id):
    key = (str(farm_id), str(house_id))
    with _llm_lock_mutex:
        expire = _llm_relay_locks.get(key)
        if expire and datetime.now() < expire:
            return True
        if expire:
            del _llm_relay_locks[key]
        return False


def clear_llm_relay_lock(farm_id, house_id):
    key = (str(farm_id), str(house_id))
    with _llm_lock_mutex:
        _llm_relay_locks.pop(key, None)


# ═══════════════════════════════════════════════════════
# 숫자로 변환 가능한 값을 정수로 반환, 실패 시 큰 수 반환
# ═══════════════════════════════════════════════════════
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
def house_prefix(order_label="", farm_id=None, house_id=None):
    prefix = f"{order_label} " if order_label else ""
    if farm_id is None or house_id is None:
        return prefix.strip()
    return f"{prefix}농장 {farm_id}, 재배사 {house_id}"


def get_pin_map(house_id):
    if int(house_id) == 2:
        return RELAY_PIN_MAP_E
    return RELAY_PIN_MAP_STANDARD


def reverse_pin_map(house_id):
    return {v: k for k, v in get_pin_map(house_id).items()}


# ═══════════════════════════
# 공통 포맷팅 함수
# 센서값을 포맷 문자열로 변환
# ═══════════════════════════
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


def format_relay_on_str(relay_data, house_id):
    names = _get_relay_names(relay_data, house_id, on_state=True)
    return ", ".join(names) if names else "전체 OFF"


def format_relay_off_str(relay_data, house_id):
    names = _get_relay_names(relay_data, house_id, on_state=False)
    return ", ".join(names) if names else "전체 ON"


# ═════════════════════════════════════
# 장치 결정 내용을 ON/OFF 문자열로 변환
# ═════════════════════════════════════
def format_device_decision(devices):
    if not devices:
        return ""
    on_list = [SEMANTIC_LABELS.get(k, k) for k, v in devices.items() if v]
    off_list = [SEMANTIC_LABELS.get(k, k) for k, v in devices.items() if not v]
    on_str = ", ".join(on_list) if on_list else "없음"
    off_str = ", ".join(off_list) if off_list else "없음"
    return f"ON=[{on_str}], OFF=[{off_str}]"
