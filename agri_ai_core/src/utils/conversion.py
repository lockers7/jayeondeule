# ═══════════════════════════════════════════════════════════════════════
# 변환 유틸리티 — 센서/릴레이 데이터 추출, 안전한 숫자 변환
# DB row(dict)에서 센서값/릴레이 상태를 일관된 구조로 뽑아내고,
# None/문자열/잘못된 타입을 허용하는 safe_float/safe_int를 제공한다.
# --->
# safe_float: 안전한 float 변환 (실패 시 default)
# safe_int: 안전한 int 변환 (실패 시 default)
# _merge_relay_stats: relay_stats JSON 파싱하여 relay_data에 병합 (내부 헬퍼)
# convert_sensor_relay_data: 데이터 항목에서 센서+릴레이를 한번에 추출
# extract_relay_data: 데이터 항목에서 릴레이 정보만 추출
# ═══════════════════════════════════════════════════════════════════════
from agri_ai_core.config import SENSOR_FIELD_MAPPING, RELAY_FIELD_MAPPING
from agri_ai_core.src.utils.validators import clean_sensor_value, parse_boolean
from agri_ai_core.src.utils.json_utils import safe_json_load


def safe_float(value, default=0.0):
    """안전한 float 변환. None/문자열/변환실패 시 default."""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """안전한 int 변환. None/문자열/변환실패 시 default."""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _merge_relay_stats(data_item, relay_data):
    """data_item['relay_stats'] JSON을 파싱하여 relay_data에 병합.
    이미 relay_data에 있는 키는 덮어쓰지 않음 (상위 레벨 우선)."""
    raw = data_item.get("relay_stats")
    if not raw:
        return
    stats = raw if isinstance(raw, dict) else safe_json_load(raw, default={})
    if not isinstance(stats, dict):
        return
    for key, value in stats.items():
        if key in RELAY_FIELD_MAPPING and key not in relay_data:
            relay_data[key] = parse_boolean(value)


def convert_sensor_relay_data(data_item):
    """DB row에서 센서값과 릴레이 상태를 분리 추출.
    Returns: {"sensor_data": {key: float}, "relay_data": {key: bool}}
    """
    result = {"sensor_data": {}, "relay_data": {}}

    for sensor_key in SENSOR_FIELD_MAPPING:
        if sensor_key in data_item:
            result["sensor_data"][sensor_key] = clean_sensor_value(data_item.get(sensor_key))

    for relay_key in RELAY_FIELD_MAPPING:
        if relay_key in data_item:
            result["relay_data"][relay_key] = parse_boolean(data_item.get(relay_key))

    _merge_relay_stats(data_item, result["relay_data"])
    return result


def extract_relay_data(data_item):
    """DB row에서 릴레이 정보만 dict로 추출 (센서값 제외).
    'relay_' 접두 내부 필드는 건너뛰고 최상위 릴레이 키만 포함한다."""
    relay_data = {}
    for key in RELAY_FIELD_MAPPING:
        if not key.startswith('relay_') and key in data_item:
            relay_data[key] = parse_boolean(data_item[key])

    _merge_relay_stats(data_item, relay_data)
    return relay_data
