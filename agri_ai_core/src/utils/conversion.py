# ══════════════════════════════════════════════════════════
# 변환 유틸리티 모듈 - 센서/릴레이 데이터 추출, safe_float/safe_int 변환.
# ══════════════════════════════════════════════════════════
import json

from agri_ai_core.config import SENSOR_FIELD_MAPPING, RELAY_FIELD_MAPPING
from agri_ai_core.src.utils.validators import clean_sensor_value, parse_boolean


# 안전한 float 변환 (실패 시 기본값 반환)
# ══════════════════════════════════════════════════════════
def safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


# 안전한 int 변환 (실패 시 기본값 반환)
# ══════════════════════════════════════════════════════════
def safe_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


# relay_stats JSON을 파싱하여 relay_data에 병합 (공통 헬퍼)
# ══════════════════════════════════════════════════════════
def _merge_relay_stats(data_item, relay_data):
    if "relay_stats" not in data_item:
        return
    try:
        raw = data_item["relay_stats"]
        stats = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        for key, value in stats.items():
            if key in RELAY_FIELD_MAPPING and key not in relay_data:
                relay_data[key] = parse_boolean(value)
    except Exception:
        pass


# 데이터 항목에서 센서와 릴레이 정보를 한번에 추출
# ══════════════════════════════════════════════════════════
def convert_sensor_relay_data(data_item):
    result = {
        "sensor_data": {},
        "relay_data": {}
    }

    for sensor_key in SENSOR_FIELD_MAPPING:
        if sensor_key in data_item:
            result["sensor_data"][sensor_key] = clean_sensor_value(data_item.get(sensor_key))

    for relay_key in RELAY_FIELD_MAPPING:
        if relay_key in data_item:
            result["relay_data"][relay_key] = parse_boolean(data_item.get(relay_key))

    _merge_relay_stats(data_item, result["relay_data"])
    return result


# 데이터 항목에서 릴레이 관련 정보 추출
# ══════════════════════════════════════════════════════════
def extract_relay_data(data_item):
    relay_data = {}
    for key in RELAY_FIELD_MAPPING:
        if not key.startswith('relay_') and key in data_item:
            relay_data[key] = parse_boolean(data_item[key])

    _merge_relay_stats(data_item, relay_data)
    return relay_data
