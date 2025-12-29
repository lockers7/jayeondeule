# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 단위 변환 유틸리티 모듈
# 온도, 습도 등의 단위 변환 및 데이터 타입 변환 등
# 다양한 변환 함수를 제공합니다.
# --->
# convert_sensor_relay_data: 데이터 항목에서 센서와 릴레이 정보를 추출
# extract_relay_data: 데이터 항목에서 릴레이 관련 정보 추출
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
from datetime import datetime
from decimal import Decimal

from agri_ai_core.shared_modules.common.mappers import SENSOR_FIELD_MAPPING, RELAY_FIELD_MAPPING
from agri_ai_core.shared_modules.common.validators import clean_sensor_value, parse_boolean


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 데이터 항목에서 센서와 릴레이 정보를 한번에 추출하는 공통 함수
# --->
# 데이터 항목에서 센서와 릴레이 정보를 추출
# Args:
# data_item: 원본 데이터 딕셔너리
# Returns:
# dict: {"sensor_data": {...}, "relay_data": {...}}
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def convert_sensor_relay_data(data_item):
    result = {
        "sensor_data": {},
        "relay_data": {}
    }

    for sensor_key, sensor_info in SENSOR_FIELD_MAPPING.items():
        if sensor_key in data_item:
            result["sensor_data"][sensor_key] = clean_sensor_value(data_item.get(sensor_key))

    for relay_key in RELAY_FIELD_MAPPING.keys():
        if relay_key in data_item:
            result["relay_data"][relay_key] = parse_boolean(data_item.get(relay_key))

    if "relay_stats" in data_item:
        try:
            relay_stats_str = data_item["relay_stats"]
            if isinstance(relay_stats_str, dict):
                relay_stats = relay_stats_str
            elif relay_stats_str:
                relay_stats = json.loads(relay_stats_str)
            else:
                relay_stats = {}

            for stats_key, value in relay_stats.items():
                if stats_key in RELAY_FIELD_MAPPING and stats_key not in result["relay_data"]:
                    result["relay_data"][stats_key] = parse_boolean(value)
        except Exception:
            pass

    return result


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 데이터 항목에서 릴레이 관련 정보 추출
# --->
# 데이터 항목에서 릴레이 관련 정보 추출
# Args:
# data_item: 원본 데이터 딕셔너리
# Returns:
# dict: 릴레이 데이터
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def extract_relay_data(data_item):
    relay_data = {}
    source_relay_keys = [k for k in RELAY_FIELD_MAPPING.keys() if not k.startswith('relay_')]

    for key in source_relay_keys:
        if key in data_item:
            relay_data[key] = data_item[key]

    if "relay_stats" in data_item:
        try:
            relay_stats = json.loads(data_item["relay_stats"]) if isinstance(data_item["relay_stats"], str) else data_item["relay_stats"]

            for stats_key, value in relay_stats.items():
                source_key = RELAY_FIELD_MAPPING.get(stats_key)
                if source_key and source_key not in relay_data:
                    relay_data[source_key] = value
        except Exception:
            pass

    return relay_data


