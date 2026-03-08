# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 제어 모듈 공통 상수, 매핑, 유틸리티
# manual_control, ai_control, relay_manager 등 제어 모듈이 공유하는 상수·핀맵·로깅 함수
# --->
# to_sortable_int: 숫자로 변환 가능한 값을 정수로 반환, 실패 시 큰 수 반환
# sort_houses: 재배사 목록을 farm_id, hous_id 순으로 정렬
# house_prefix: 로그 접두사 생성
# get_pin_map: house_id별 릴레이 핀 매핑
# reverse_pin_map: 핀맵 역변환 (relay_*st_flag → 시멘틱명)
# format_sensor_parts: 센서값 포맷 문자열
# _get_relay_names: ON/OFF 상태 릴레이 시멘틱 이름 목록 (공통)
# format_relay_on_str: ON 상태 릴레이 포맷 문자열
# format_relay_off_str: OFF 상태 릴레이 포맷 문자열
# format_device_decision: 장치 결정 ON/OFF 문자열
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os


# ============================================================
# 릴레이 핀 수
# ============================================================
RELAY_COUNT = 16


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

WATER_TEMP_LOW = 40
WATER_TEMP_HIGH = 55
WATER_TEMP_CRITICAL_LOW = 35
WATER_TEMP_CRITICAL_HIGH = 60

BUDDING_TEMP_LOW = 29
BUDDING_TEMP_HIGH = 33

HEATER_MAX_CONTINUOUS_MIN = 30
HEATER_COOLDOWN_MIN = 5

DAMPER_FAN_DELAY_SEC = 15


# ============================================================
# Semantic name → relay_*st_flag 핀 매핑
# ============================================================
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
    'air_intake_valve_flag': 'relay_11st_flag',
    'air_exhaust_valve_flag': 'relay_14st_flag',
    'indoor_heater_valve_flag': 'relay_15st_flag',
}

RELAY_PIN_MAP_E = {
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
    'indoor_heater_valve_flag': 'relay_14st_flag',
}


SEMANTIC_LABELS = {
    'water_heater_flag': '물가열기',
    'fog_occurs_flag': '분사펌프',
    'drainage_motor_flag': '배수밸브',
    'intake_fan_flag': '흡기팬',
    'exhaust_fan_flag': '배기팬',
    'lighting_flag': '조명',
    'irrigation_flag': '관수',
    'indoor_heater_flag': '열풍기',
    'indoor_heater_valve_flag': '열풍댐퍼',
    'air_circulation_valve_flag': '순환댐퍼',
    'air_intake_valve_flag': '흡기댐퍼',
    'air_exhaust_valve_flag': '배기댐퍼',
    'radiator_flag': '라디에이터',
}

# 한글 별칭 → 시멘틱 flag 매핑 (Web UI 이름, 사용자 구어체 등)
DEVICE_ALIASES = {
    # water_heater_flag 별칭
    '수온히터': 'water_heater_flag',
    '물가열기': 'water_heater_flag',
    '칠러': 'water_heater_flag',
    '칠러1': 'water_heater_flag',
    '칠러Ⅰ': 'water_heater_flag',
    # fog_occurs_flag 별칭
    '포그생성': 'fog_occurs_flag',
    '포그': 'fog_occurs_flag',
    '분사펌프': 'fog_occurs_flag',
    '순환모터': 'fog_occurs_flag',
    # drainage_motor_flag 별칭
    '배수밸브': 'drainage_motor_flag',
    '배수': 'drainage_motor_flag',
    # intake_fan_flag 별칭
    '흡입팬': 'intake_fan_flag',
    '흡기팬': 'intake_fan_flag',
    '흡입': 'intake_fan_flag',
    # exhaust_fan_flag 별칭
    '배출팬': 'exhaust_fan_flag',
    '배기팬': 'exhaust_fan_flag',
    '배출': 'exhaust_fan_flag',
    # lighting_flag 별칭
    '조명': 'lighting_flag',
    # irrigation_flag 별칭
    '관수': 'irrigation_flag',
    # indoor_heater_flag 별칭
    '실내히터': 'indoor_heater_flag',
    '열풍기': 'indoor_heater_flag',
    '히터': 'indoor_heater_flag',
    # indoor_heater_valve_flag 별칭
    '히터밸브': 'indoor_heater_valve_flag',
    '열풍댐퍼': 'indoor_heater_valve_flag',
    '히터댐퍼': 'indoor_heater_valve_flag',
    # air_circulation_valve_flag 별칭
    '순환밸브': 'air_circulation_valve_flag',
    '순환댐퍼': 'air_circulation_valve_flag',
    # air_intake_valve_flag 별칭
    '흡입밸브': 'air_intake_valve_flag',
    '흡기밸브': 'air_intake_valve_flag',
    '흡기댐퍼': 'air_intake_valve_flag',
    # air_exhaust_valve_flag 별칭
    '배출밸브': 'air_exhaust_valve_flag',
    '배기밸브': 'air_exhaust_valve_flag',
    '배기댐퍼': 'air_exhaust_valve_flag',
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
# LLM 제어 잠금 (자동제어 스케줄러 충돌 방지)
# LLM이 릴레이를 제어한 후 일정 시간 동안 해당 재배사의 자동제어를 억제
# ============================================================
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


# ============================================================
# 숫자로 변환 가능한 값을 정수로 반환, 실패 시 큰 수 반환
# ============================================================
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


# ============================================================
# 재배사 목록을 farm_id, hous_id 순으로 정렬
# ============================================================
def sort_houses(houses):
    return sorted(
        houses or [],
        key=lambda house: (
            to_sortable_int(house.get("farm_id")),
            to_sortable_int(house.get("hous_id")),
            str(house.get("hous_id") or ""),
        ),
    )


# ============================================================
# 유틸리티 함수
# ============================================================
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


# ============================================================
# 공통 포맷팅 함수
# 센서값을 포맷 문자열로 변환
# ============================================================
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


# ============================================================
# ON/OFF 릴레이 이름 목록 (공통)
# on_state=True: ON 릴레이 (미매핑 핀도 포함)
# on_state=False: OFF 릴레이 (매핑된 핀만)
# ============================================================
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


# ============================================================
# 장치 결정 내용을 ON/OFF 문자열로 변환
# ============================================================
def format_device_decision(devices):
    if not devices:
        return ""
    on_list = [SEMANTIC_LABELS.get(k, k) for k, v in devices.items() if v]
    off_list = [SEMANTIC_LABELS.get(k, k) for k, v in devices.items() if not v]
    on_str = ", ".join(on_list) if on_list else "없음"
    off_str = ", ".join(off_list) if off_list else "없음"
    return f"ON=[{on_str}], OFF=[{off_str}]"
