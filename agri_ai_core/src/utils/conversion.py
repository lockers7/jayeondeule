# ════════════════════════════════════════════════════════════════════
# 변환 유틸리티 — 센서/릴레이 데이터 추출, 안전한 숫자 변환.
# DB row(dict) 에서 센서값/릴레이 상태를 일관된 구조로 뽑아내고,
# None/문자열/잘못된 타입을 허용하는 safe_float/safe_int 를 제공.
# --->
# safe_float                : 안전한 float 변환 (실패 시 default)
# safe_int                  : 안전한 int 변환 (실패 시 default)
# _allowed_relay_keys       : STANDARD/E 매핑이 인지하는 모든 키(컬럼+시멘틱) union
# _merge_relay_stats        : relay_stats JSON 파싱하여 relay_data 에 병합
# convert_sensor_relay_data : DB row 에서 센서+릴레이를 한번에 추출
# extract_relay_data        : DB row 에서 릴레이 정보만 추출
# ════════════════════════════════════════════════════════════════════
from agri_ai_core.config import SENSOR_FIELD_MAPPING, RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E
from agri_ai_core.config.mappers import standard_semantic_keys
from agri_ai_core.src.utils.validators import clean_sensor_value, parse_boolean
from agri_ai_core.src.utils.json_utils import safe_json_load


# ────────────────────────────────────────────────────────────────────
# 안전한 float 변환. None/문자열/변환실패 시 default 반환.
# ────────────────────────────────────────────────────────────────────
def safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


# ────────────────────────────────────────────────────────────────────
# 안전한 int 변환. None/문자열/변환실패 시 default 반환.
# ────────────────────────────────────────────────────────────────────
def safe_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


# ────────────────────────────────────────────────────────────────────
# [변경4 · 2026-04-30] STANDARD 5-tuple + E 3-tuple 혼재 흡수.
#   STANDARD : 키=relay_Nst_flag (컬럼명) 만 존재 → 시멘틱 키는 RelayDef.sem 으로 보강
#   E        : 키=시멘틱+컬럼명 혼재 (기존 그대로)
# ────────────────────────────────────────────────────────────────────
def _allowed_relay_keys():
    return (set(RELAY_FIELD_MAPPING)            # STANDARD 컬럼명
            | standard_semantic_keys()          # STANDARD 시멘틱
            | set(RELAY_FIELD_MAPPING_E))       # E 시멘틱+컬럼 혼재


# ────────────────────────────────────────────────────────────────────
# data_item['relay_stats'] JSON 을 파싱하여 relay_data 에 병합.
# 이미 relay_data 에 있는 키는 덮어쓰지 않음 (상위 레벨 우선).
# ────────────────────────────────────────────────────────────────────
def _merge_relay_stats(data_item, relay_data):
    raw = data_item.get("relay_stats")
    if not raw:
        return
    stats = raw if isinstance(raw, dict) else safe_json_load(raw, default={})
    if not isinstance(stats, dict):
        return
    allowed = _allowed_relay_keys()
    for key, value in stats.items():
        if key in allowed and key not in relay_data:
            relay_data[key] = parse_boolean(value)


# ────────────────────────────────────────────────────────────────────
# DB row 에서 센서값과 릴레이 상태를 분리 추출.
# Returns: {"sensor_data": {key: float}, "relay_data": {key: bool}}
# ────────────────────────────────────────────────────────────────────
def convert_sensor_relay_data(data_item):
    result = {"sensor_data": {}, "relay_data": {}}

    for sensor_key in SENSOR_FIELD_MAPPING:
        if sensor_key in data_item:
            result["sensor_data"][sensor_key] = clean_sensor_value(data_item.get(sensor_key))

    for relay_key in _allowed_relay_keys():
        if relay_key in data_item:
            result["relay_data"][relay_key] = parse_boolean(data_item.get(relay_key))

    _merge_relay_stats(data_item, result["relay_data"])
    return result


# ────────────────────────────────────────────────────────────────────
# DB row 에서 릴레이 정보만 dict 로 추출 (센서값 제외).
# 시멘틱(논리) 키만 포함 — relay_Nst_flag 컬럼명은 제외.
# ────────────────────────────────────────────────────────────────────
def extract_relay_data(data_item):
    relay_data = {}

    # STANDARD/E 모두 RelayDef.sem 으로 시멘틱 키 추출 (E는 5-tuple 변경 이후)
    for d in (RELAY_FIELD_MAPPING, RELAY_FIELD_MAPPING_E):
        for r in d.values():
            if r.sem in data_item and r.sem not in relay_data:
                relay_data[r.sem] = parse_boolean(data_item[r.sem])

    _merge_relay_stats(data_item, relay_data)
    return relay_data
