# ════════════════════════════════════════════════════════════════════
# 농장/재배사 이름 — 매 호출 DB 조회 (Phase 4 · 2026-05-09).
# tools_executor / llm_client / llm_response 등에서 공유.
# 시작 1회 로드 폐기 — web UI 에서 농장/재배사 추가 즉시 반영.
# DB 실패 시 마지막 성공 결과 fallback (운영 안정).
# --->
# _refresh_farm_cache  : DB 조회 + fallback 캐시 갱신 (성공 시) → dict 반환
# _refresh_house_cache : DB 조회 + fallback 캐시 갱신 (성공 시) → dict 반환
# get_farm_name        : farm_id → farm_name (매 호출 DB)
# get_farm_id_by_name  : farm_name → farm_id (역방향)
# get_all_farm_names   : 전체 farm dict (매 호출 DB)
# get_house_name       : (farm_id, house_id) → house_name (매 호출 DB, 미존재 시 'N호재배사')
# is_cache_loaded      : fallback 캐시 채워졌는지 (1회 이상 성공 조회)
# ════════════════════════════════════════════════════════════════════
from typing import Dict, Optional, Tuple

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# fallback 캐시 — DB 조회 실패 시에만 사용. 일반 호출은 매번 DB 조회.
_farm_name_cache: Dict[str, str] = {}
_house_name_cache: Dict[Tuple[str, str], str] = {}


# ────────────────────────────────────────────────────────────────────
# DB 에서 farm 목록 조회 → fallback 캐시 갱신 (성공 시).
# 실패 시 None 반환 — 호출자는 fallback 캐시 사용.
# ────────────────────────────────────────────────────────────────────
def _refresh_farm_cache() -> Optional[Dict[str, str]]:
    global _farm_name_cache
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_LIST_FARM
        with db_session() as database:
            rows = database.fetch_all(query=GET_LIST_FARM, vals=(), as_dict=True)
        d = {str(r["farm_id"]): r["farm_name"] for r in (rows or [])}
        _farm_name_cache = d   # fallback 갱신
        return d
    except Exception as e:
        logger.debug(f"[farm_name] DB 조회 실패 (캐시 fallback): {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# DB 에서 house 목록 조회 → fallback 캐시 갱신.
# ────────────────────────────────────────────────────────────────────
def _refresh_house_cache() -> Optional[Dict[Tuple[str, str], str]]:
    global _house_name_cache
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        from agri_ai_core.src.postgresql.queries import GET_HOUSE_NAME
        with db_session() as database:
            rows = database.fetch_all(
                query=GET_HOUSE_NAME, vals=(None, None, None, None), as_dict=True
            )
        d = {
            (str(r["farm_id"]), str(r["hous_id"])): r["hous_name"]
            for r in (rows or [])
            if r.get("hous_name")
        }
        _house_name_cache = d   # fallback 갱신
        return d
    except Exception as e:
        logger.debug(f"[house_name] DB 조회 실패 (캐시 fallback): {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# farm_id → farm_name (매 호출 DB).
# DB 실패 + fallback 캐시 미존재 시 farm_id 그대로 반환.
# ────────────────────────────────────────────────────────────────────
def get_farm_name(farm_id) -> str:
    fid = str(farm_id)
    d = _refresh_farm_cache() or _farm_name_cache
    return d.get(fid, fid)


# ────────────────────────────────────────────────────────────────────
# farm_name → farm_id (역방향). 없으면 None.
# ────────────────────────────────────────────────────────────────────
def get_farm_id_by_name(farm_name: str) -> Optional[str]:
    d = _refresh_farm_cache() or _farm_name_cache
    for fid, fname in d.items():
        if fname == farm_name:
            return fid
    return None


# ────────────────────────────────────────────────────────────────────
# 전체 farm_id→farm_name 사본 (매 호출 DB).
# ────────────────────────────────────────────────────────────────────
def get_all_farm_names() -> Dict[str, str]:
    return dict(_refresh_farm_cache() or _farm_name_cache)


# ────────────────────────────────────────────────────────────────────
# (farm_id, house_id) → house_name (매 호출 DB).
# 미존재 시 'N호재배사' 폴백 — 라벨이 비지 않도록 보장.
# ────────────────────────────────────────────────────────────────────
def get_house_name(farm_id, house_id) -> str:
    fid = str(farm_id) if farm_id is not None else ""
    hid = str(house_id) if house_id is not None else ""
    d = _refresh_house_cache() or _house_name_cache
    name = d.get((fid, hid))
    if name:
        return name
    return f"{hid}호재배사" if hid else "재배사"


# ────────────────────────────────────────────────────────────────────
# fallback 캐시가 1회 이상 채워졌는지 (운영 진단용).
# ────────────────────────────────────────────────────────────────────
def is_cache_loaded() -> bool:
    return bool(_farm_name_cache)
