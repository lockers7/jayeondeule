# ════════════════════════════════════════════════════════════════
# 도구 실행 공용 유틸 — pure helper 모음.
# ID 정규화, JSON 직렬화 fallback, AI vs 사용자 상태 충돌 비교 등.
# --->
# normalize_id: LLM이 준 ID 문자열에서 순수 숫자만 추출
# json_default: Decimal/datetime 등 json.dumps 미지원 타입 변환
# build_ai_conflict: AI 권장 릴레이 vs 사용자 수동 설정 차이 비교
# parse_positive_int: 양의 정수 파싱 (실패 시 default)
# parse_positive_float: 양의 실수 파싱 (실패 시 default)
# parse_optional_int: 빈 값/None 허용 정수 파싱
# to_chroma_where: 다중 키 dict → ChromaDB $and 형식 변환
# ════════════════════════════════════════════════════════════════
import re
import time
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════════
# 도구별 세션 컨텍스트 자동 주입 명세 (선언형 테이블)
# query_handler_simple._build_default_tool_args 가 이 테이블을 읽어
# 각 도구의 default 인자를 자동 생성한다. 새 도구를 추가할 때 이 표에 한 줄만
# 등록하면 세션의 farm_id/house_id/auth_farm_id 가 자동 주입된다.
#
# 키 → 값 의미
#   "farm_id":       세션 농장 ID 를 도구 default 로 주입
#   "house_id":      세션 재배사 ID 를 도구 default 로 주입
#   "auth_farm_id":  세션 사용자 농장 ID 를 도구 default 로 주입 (권한 검증용)
#   "file_name":     질문에서 감지된 파일명을 도구 default 로 주입 (RAG 전용)
# ══════════════════════════════════════════════════════════════════════════
TOOL_DEFAULT_CONTEXT: Dict[str, Dict[str, bool]] = {
    # RAG 조회/삭제/저장
    "search_farm_knowledge": {"farm_id": True, "house_id": True, "auth_farm_id": True, "file_name": True},
    "save_domain_knowledge": {"farm_id": True, "auth_farm_id": True},
    "delete_farm_knowledge": {"farm_id": True, "auth_farm_id": True, "file_name": True},
    # 센서/릴레이 조회·제어
    "get_farm_realtime_data": {"farm_id": True, "house_id": True},
    "get_weather_forecast":   {"farm_id": True, "house_id": True},
    "control_relay":          {"farm_id": True, "house_id": True, "auth_farm_id": True},
    # 관리 도구
    "set_admin_directive":     {"farm_id": True, "auth_farm_id": True},
    "manage_control_prompt":   {"auth_farm_id": True},
    "manage_external_api":     {"auth_farm_id": True},
    "manage_analysis_lesson":  {"auth_farm_id": True},
    "manage_system_knowledge": {"auth_farm_id": True},
    "db_write_query":          {"auth_farm_id": True},
    "release_admin_directive": {"farm_id": True, "auth_farm_id": True},
    "set_house_control_mode": {"farm_id": True, "auth_farm_id": True},
    "override_ai_thresholds": {"farm_id": True, "auth_farm_id": True},
    "set_growth_stage":       {"farm_id": True, "auth_farm_id": True},
    "set_circulation_mode":   {"farm_id": True, "auth_farm_id": True},
    "set_schedule":           {"farm_id": True, "auth_farm_id": True},
    "get_system_status":      {"farm_id": True},
    # Agent 모니터링
    "schedule_monitor":       {"farm_id": True},
    "set_alert_interval":     {"farm_id": True, "auth_farm_id": True},
    "set_alert_level":        {"auth_farm_id": True},
    # DB 자유조회 — 농장관리자 세션은 자기 농장만 (tools_db._check_farm_scope)
    "db_read_query":          {"auth_farm_id": True},
}


# ────────────────────────────────────────────────────────────────────
# 세션 컨텍스트 → 도구별 default 인자 dict 자동 생성.
# TOOL_DEFAULT_CONTEXT 명세에 선언된 키만 주입한다. (알 수 없는 도구는 빈 dict)
# 값이 None 이면 해당 키는 주입하지 않는다 (LLM 이 명시 지정 기회 보장).
# ────────────────────────────────────────────────────────────────────
def build_default_tool_args(farm_id=None, house_id=None, auth_farm_id=None,
                             file_name=None) -> Dict[str, Dict[str, Any]]:
    session = {
        "farm_id": (str(farm_id) if farm_id not in (None, "") else None),
        "house_id": (str(house_id) if house_id not in (None, "") else None),
        "auth_farm_id": (str(auth_farm_id) if auth_farm_id not in (None, "") else None),
        "file_name": file_name,
    }
    out: Dict[str, Dict[str, Any]] = {}
    for tool_name, keyspec in TOOL_DEFAULT_CONTEXT.items():
        entry: Dict[str, Any] = {}
        for key, enabled in keyspec.items():
            if not enabled:
                continue
            val = session.get(key)
            if val is not None:
                entry[key] = val
        out[tool_name] = entry
    return out


# 농장별 재배사 ID 목록 캐시 — 짧은 TTL (기본 60초).
# 재배사 추가/삭제는 드물고, 센서 조회 fan-out 마다 DB 왕복하면 부담이므로 메모이제이션.
_HOUSE_IDS_CACHE: Dict[str, tuple] = {}   # farm_id(str) → (expire_ts, [hous_id, ...])
_HOUSE_IDS_CACHE_LOCK = threading.Lock()
_HOUSE_IDS_TTL = 60.0  # 초


# ────────────────────────────────────────────────────────────────────
# 농장의 실제 운영 재배사 ID 목록을 DB에서 동적 조회하여 반환한다.
# 
# - farm_id: 농장 ID (문자/숫자 모두 허용)
# - include_zero: True 시 hous_id=0(공통/통합정보재배사) 포함. 기본 False.
# - ttl: 캐시 유효 시간(초).
# 
# 재배사 구성은 농장별로 다르며 가변적이므로 하드코딩 ['1','2','3'] 금지.
# 실패·결과 없음 시 빈 리스트 반환 (호출자가 스스로 동작 결정).
# ────────────────────────────────────────────────────────────────────
def get_farm_house_ids(farm_id: Any, include_zero: bool = False, ttl: float = _HOUSE_IDS_TTL) -> List[str]:
    fid = normalize_id(farm_id) or str(farm_id or "").strip() or "1"
    # 시스템 농장(farm_id=0)은 실제 운영 재배사가 없으므로 항상 빈 목록 반환
    if fid == "0":
        return []
    cache_key = f"{fid}:{int(bool(include_zero))}"

    now = time.time()
    with _HOUSE_IDS_CACHE_LOCK:
        entry = _HOUSE_IDS_CACHE.get(cache_key)
        if entry and entry[0] > now:
            return list(entry[1])

    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            q = ("SELECT hous_id FROM farmhouse_m_info "
                 "WHERE farm_id=%s AND COALESCE(dlte_yn,'N')<>'Y' "
                 + ("" if include_zero else "AND hous_id>0 ")
                 + "ORDER BY hous_id")
            rows = db.fetch_all(query=q, vals=(fid,), as_dict=True)
        ids = [str(int(r["hous_id"])) for r in (rows or [])]
    except Exception:
        ids = []

    with _HOUSE_IDS_CACHE_LOCK:
        _HOUSE_IDS_CACHE[cache_key] = (now + ttl, list(ids))
    return ids


# ────────────────────────────────────────────────────────────────────
# 재배사 추가/삭제 후 캐시 무효화. farm_id 생략 시 전체 클리어.
# ────────────────────────────────────────────────────────────────────
def invalidate_farm_house_ids_cache(farm_id: Any = None) -> None:
    with _HOUSE_IDS_CACHE_LOCK:
        if farm_id is None:
            _HOUSE_IDS_CACHE.clear()
            return
        fid = normalize_id(farm_id) or str(farm_id or "").strip()
        for key in list(_HOUSE_IDS_CACHE.keys()):
            if key.startswith(f"{fid}:"):
                _HOUSE_IDS_CACHE.pop(key, None)


# ────────────────────────────────────────────────────────────────────
# LLM이 전달한 ID에서 숫자만 추출. 숫자가 없으면 None.
# 예: '자연들에 농장' → None, '1' → '1', '상황버섯1호재배사' → '1'
# ────────────────────────────────────────────────────────────────────
def normalize_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    # 이미 순수 숫자면 그대로
    try:
        int(s)
        return s
    except (ValueError, TypeError):
        pass
    # 한글 등이 섞여 있으면 첫 숫자만 추출
    digits = re.findall(r'\d+', s)
    return digits[0] if digits else None


# ────────────────────────────────────────────────────────────────────
# json.dumps의 default 인자로 사용. Decimal/datetime 타입 변환.
# ────────────────────────────────────────────────────────────────────
def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return str(value)
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


# ────────────────────────────────────────────────────────────────────
# AI 권장 릴레이 상태와 사용자 수동 제어의 차이점을 한국어 문자열 리스트로 반환.
# 차이 없거나 입력 부족 시 None 반환.
# ────────────────────────────────────────────────────────────────────
def build_ai_conflict(ai_judgment: Optional[Dict[str, Any]],
                      user_relay_settings: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    if not ai_judgment or not user_relay_settings:
        return None
    ai_devices = ai_judgment.get("devices") or {}
    if not ai_devices:
        return None

    from agri_ai_core.src.control.control_common import SEMANTIC_LABELS
    conflicts = []
    for device_name, user_value in user_relay_settings.items():
        if device_name in ai_devices:
            ai_value = ai_devices[device_name]
            if bool(user_value) != bool(ai_value):
                label = SEMANTIC_LABELS.get(device_name, device_name)
                user_str = "ON" if user_value else "OFF"
                ai_str = "ON" if ai_value else "OFF"
                conflicts.append(f"{label}: 수동={user_str}, AI권장={ai_str}")

    return conflicts or None


# ────────────────────────────────────────────────────────────────────
# 양의 정수 파싱. 실패하거나 0 이하면 default 반환.
# ────────────────────────────────────────────────────────────────────
def parse_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (ValueError, TypeError):
        return default


# ────────────────────────────────────────────────────────────────────
# 양의 실수 파싱. 실패하거나 0 이하면 default 반환.
# ────────────────────────────────────────────────────────────────────
def parse_positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except (ValueError, TypeError):
        return default


# ────────────────────────────────────────────────────────────────────
# 빈 값/None 허용 정수 파싱. 실패/빈값 시 None.
# ────────────────────────────────────────────────────────────────────
def parse_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


# ────────────────────────────────────────────────────────────────────
# 다중 키 where 딕셔너리를 ChromaDB $and 형식으로 변환.
# ────────────────────────────────────────────────────────────────────
def to_chroma_where(where_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not where_dict:
        return None
    if len(where_dict) == 1:
        k, v = next(iter(where_dict.items()))
        return {k: {"$eq": v}} if not isinstance(v, dict) else where_dict
    conditions = []
    for k, v in where_dict.items():
        if isinstance(v, dict):
            conditions.append({k: v})
        else:
            conditions.append({k: {"$eq": v}})
    return {"$and": conditions}
