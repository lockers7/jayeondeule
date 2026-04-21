# ════════════════════════════════════════════════════════════════════
# 농장/재배사 이름 캐시 — farm_id → farm_name, (farm_id,house_id) → house_name.
# tools_executor / llm_client / llm_response 등에서 공유. 프로세스 시작 후
# 최초 1회 DB 조회, 이후 캐시 재사용.
# 라벨 일관성 핵심: 데이터 라벨(`[상황버섯1호재배사]`)이 시스템 프롬프트의
# 재배사 목록과 정확히 일치해야 LLM 표 매핑 오류(빈 행/뒤섞임)가 발생하지 않음.
# --->
# _ensure_loaded       : 최초 1회 DB 조회로 farm 캐시 채우기
# _ensure_house_loaded : 최초 1회 DB 조회로 house 캐시 채우기
# get_farm_name        : farm_id → farm_name (캐시 + DB 자동 조회)
# get_farm_id_by_name  : farm_name → farm_id (역방향 조회)
# get_all_farm_names   : 전체 farm 캐시 dict (읽기 전용 사본)
# get_house_name       : (farm_id, house_id) → house_name (미존재 시 'N호재배사' 폴백)
# is_cache_loaded      : farm 캐시 로드 완료 여부
# ════════════════════════════════════════════════════════════════════
from typing import Dict, Optional, Tuple

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_farm_name_cache: Dict[str, str] = {}
_farm_name_cache_loaded = False

_house_name_cache: Dict[Tuple[str, str], str] = {}
_house_name_cache_loaded = False


# ────────────────────────────────────────────────────────────────────
# 최초 1회 DB 조회로 farm 캐시 채우기.
# ────────────────────────────────────────────────────────────────────
def _ensure_loaded():
    global _farm_name_cache, _farm_name_cache_loaded
    if _farm_name_cache_loaded:
        return
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_LIST_FARM
        with db_session() as database:
            rows = database.fetch_all(query=GET_LIST_FARM, vals=(), as_dict=True)
        _farm_name_cache = {str(r["farm_id"]): r["farm_name"] for r in (rows or [])}
        _farm_name_cache_loaded = True
    except Exception as e:
        logger.warning(f"[farm_name 캐시] DB 조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# 최초 1회 DB 조회로 house 캐시 채우기 — GET_HOUSE_NAME(farm_id NULL, house_id NULL)
# = 모든 농장×재배사 (farm_id, house_id) → house_name 일괄 조회.
# ────────────────────────────────────────────────────────────────────
def _ensure_house_loaded():
    global _house_name_cache, _house_name_cache_loaded
    if _house_name_cache_loaded:
        return
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_HOUSE_NAME
        with db_session() as database:
            rows = database.fetch_all(
                query=GET_HOUSE_NAME, vals=(None, None, None, None), as_dict=True
            )
        _house_name_cache = {
            (str(r["farm_id"]), str(r["hous_id"])): r["hous_name"]
            for r in (rows or [])
            if r.get("hous_name")
        }
        _house_name_cache_loaded = True
        logger.info(f"[house_name 캐시] 로드 완료: {len(_house_name_cache)}건")
    except Exception as e:
        logger.warning(f"[house_name 캐시] DB 조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# farm_id에 해당하는 farm_name 반환. 미존재 시 farm_id 그대로.
# ────────────────────────────────────────────────────────────────────
def get_farm_name(farm_id: str) -> str:
    _ensure_loaded()
    return _farm_name_cache.get(farm_id, farm_id)


# ────────────────────────────────────────────────────────────────────
# farm_name으로 farm_id 역방향 조회. 없으면 None.
# ────────────────────────────────────────────────────────────────────
def get_farm_id_by_name(farm_name: str) -> Optional[str]:
    _ensure_loaded()
    for fid, fname in _farm_name_cache.items():
        if fname == farm_name:
            return fid
    return None


# ────────────────────────────────────────────────────────────────────
# 전체 farm_id→farm_name 캐시 사본 반환 (읽기 전용 용도).
# ────────────────────────────────────────────────────────────────────
def get_all_farm_names() -> Dict[str, str]:
    _ensure_loaded()
    return dict(_farm_name_cache)


# ────────────────────────────────────────────────────────────────────
# (farm_id, house_id) → house_name 반환.
# 캐시 미존재/조회 실패 시 'N호재배사' 폴백 — 라벨이 비지 않도록 보장.
# ────────────────────────────────────────────────────────────────────
def get_house_name(farm_id, house_id) -> str:
    _ensure_house_loaded()
    fid = str(farm_id) if farm_id is not None else ""
    hid = str(house_id) if house_id is not None else ""
    name = _house_name_cache.get((fid, hid))
    if name:
        return name
    return f"{hid}호재배사" if hid else "재배사"


# ────────────────────────────────────────────────────────────────────
# 캐시가 로드 완료됐는지.
# ────────────────────────────────────────────────────────────────────
def is_cache_loaded() -> bool:
    return _farm_name_cache_loaded
