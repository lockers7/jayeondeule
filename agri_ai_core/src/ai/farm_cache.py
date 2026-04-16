# ════════════════════════════════════════════════════════════
# 농장 이름 캐시 — farm_id → farm_name 매핑 (프로세스 수명)
# tools_executor와 llm_client 양쪽에서 사용되는 공유 상태.
# 프로세스 시작 후 최초 1회 DB 조회, 이후 캐시 재사용.
# --->
# get_farm_name: farm_id → farm_name (캐시 + DB 자동 조회)
# get_farm_id_by_name: farm_name → farm_id (역방향 조회)
# get_all_farm_names: 전체 캐시 dict (읽기 전용 사본)
# is_cache_loaded: 캐시 로드 완료 여부
# ════════════════════════════════════════════════════════════
from typing import Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_farm_name_cache: Dict[str, str] = {}
_farm_name_cache_loaded = False


def _ensure_loaded():
    """최초 1회 DB 조회로 캐시 채우기."""
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


def get_farm_name(farm_id: str) -> str:
    """farm_id에 해당하는 farm_name 반환. 미존재 시 farm_id 그대로."""
    _ensure_loaded()
    return _farm_name_cache.get(farm_id, farm_id)


def get_farm_id_by_name(farm_name: str) -> Optional[str]:
    """farm_name으로 farm_id 역방향 조회. 없으면 None."""
    _ensure_loaded()
    for fid, fname in _farm_name_cache.items():
        if fname == farm_name:
            return fid
    return None


def get_all_farm_names() -> Dict[str, str]:
    """전체 farm_id→farm_name 캐시 사본 반환 (읽기 전용 용도)."""
    _ensure_loaded()
    return dict(_farm_name_cache)


def is_cache_loaded() -> bool:
    """캐시가 로드 완료됐는지."""
    return _farm_name_cache_loaded
