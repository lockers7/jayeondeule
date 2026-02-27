# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 클라이언트 모듈
# 벡터 데이터베이스 연결 및 기본 API 통신을 담당하며,
# heartbeat, 컬렉션 관리 등의 기본 기능을 제공합니다.
# --->
# get_chroma_url: ChromaDB API URL 생성
# heartbeat: ChromaDB 서버 상태 확인
# get_collection_id_from_name: 컬렉션 이름으로 ID 조회
# get_collection: 컬렉션 정보 조회 (없으면 생성)
# list_collections: 모든 컬렉션 목록 조회
# create_collection: 컬렉션 생성
# ensure_required_collections_exist: 필수 컬렉션 존재 확인 및 생성
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import time
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import settings
from agri_ai_core.src.ai.mcp_client import mcp_http_request
from agri_ai_core.src.chroma.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    TENANT,
    DATABASE,
    CHROMA_API_BASE,
    _COLLECTION_ID_MAP,
    _COLLECTION_ID_TIMESTAMPS,
    _COLLECTION_CACHE_TTL,
)

logger = setup_logger(__name__)


def _http_request(method: str, url: str, payload=None, timeout: int = 10):
    normalized_method = (method or "GET").upper()
    return mcp_http_request(
        method=normalized_method,
        url=url,
        json_body=payload,
        timeout=timeout,
    )


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB API URL 생성
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_chroma_url(endpoint: str, collection_id: str = None):
    base = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2"
    if collection_id:
        return f"{base}/collections/{collection_id}/{endpoint}"
    return f"{base}/{endpoint}"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 서버 연결 확인 (heartbeat)
# --->
# ChromaDB 서버 상태 확인
# Returns:
# dict: 상태 정보 또는 에러
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def heartbeat():
    try:
        url = get_chroma_url("heartbeat")
        status_code, data, text = _http_request("GET", url, timeout=5)
        if status_code == 200:
            if isinstance(data, dict):
                return data
            return {}
        else:
            logger.warning(f"서버 상태 확인 실패: 상태 코드 {status_code}")
            return {"error": f"서버 상태 확인 실패: {status_code} {text}"}
    except Exception as e:
        logger.error(f"서버 상태 확인 중 오류: {e}")
        return {"error": f"서버 상태 확인 중 오류: {e}"}



# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컬렉션 이름으로 ID 조회
# --->
# 컬렉션 이름으로 ID 조회
# Args:
# collection_name: 컬렉션 이름
# Returns:
# str: 컬렉션 ID 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _is_valid_uuid(value):
    """UUID 형식인지 확인 (하이픈 포함 36자 또는 하이픈 포함 문자열)"""
    return isinstance(value, str) and ("-" in value or len(value) == 36)


def _refresh_collection_ids():
    """list_collections()를 호출하여 모든 컬렉션 ID를 캐시에 갱신"""
    now = time.time()
    collections = list_collections().get("collections", [])
    for col in collections:
        _COLLECTION_ID_MAP[col["name"]] = col["id"]
        _COLLECTION_ID_TIMESTAMPS[col["name"]] = now


def get_collection_id_from_name(collection_name):
    cached = _COLLECTION_ID_MAP.get(collection_name)
    ts = _COLLECTION_ID_TIMESTAMPS.get(collection_name, 0)
    now = time.time()

    # UUID가 유효하고 TTL 이내면 바로 반환 (heartbeat 스킵)
    if cached and _is_valid_uuid(cached) and (now - ts < _COLLECTION_CACHE_TTL):
        return cached

    # TTL 만료 또는 캐시 미스 → heartbeat + refresh
    status = heartbeat()
    if "error" in status:
        logger.error("ChromaDB 연결 실패. 캐시 초기화 불가")
        return None

    _refresh_collection_ids()
    return _COLLECTION_ID_MAP.get(collection_name)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컬렉션 조회
# --->
# 컬렉션 정보 조회 (없으면 생성)
# Args:
# collection_name: 컬렉션 이름
# Returns:
# dict: 컬렉션 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_collection(collection_name):
    try:
        collections = list_collections()

        collection_id = None

        if "collections" in collections:
            for collection in collections["collections"]:
                if collection.get("name") == collection_name:
                    _COLLECTION_ID_MAP[collection_name] = collection.get("id")
                    collection_id = collection.get("id")
                    break

        if not collection_id:
            collection_id = _COLLECTION_ID_MAP.get(collection_name)

        if collection_id:
            url = f"{CHROMA_API_BASE}/collections/{collection_id}"
            status_code, data, _ = _http_request("GET", url, timeout=10)
            if status_code == 200 and isinstance(data, dict):
                return data

        return create_collection(collection_name)
    except Exception as e:
        logger.error(f" 컬렉션 '{collection_name}' 조회 실패: {e}")

        collection_id = _COLLECTION_ID_MAP.get(collection_name)
        if collection_id:
            return {"id": collection_id, "name": collection_name}

        return {"error": str(e)}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컬렉션 목록 조회
# --->
# 모든 컬렉션 목록 조회
# Returns:
# dict: {"collections": [...]}
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def list_collections():
    try:
        url = f"{CHROMA_API_BASE}/collections"
        status_code, collections_json, text = _http_request("GET", url, timeout=10)
        if status_code != 200:
            return {"error": f"컬렉션 목록 조회 실패: {status_code} {text}"}

        now = time.time()

        if isinstance(collections_json, list):
            for collection in collections_json:
                if isinstance(collection, dict) and "name" in collection and "id" in collection:
                    _COLLECTION_ID_MAP[collection["name"]] = collection["id"]
                    _COLLECTION_ID_TIMESTAMPS[collection["name"]] = now
            return {"collections": collections_json}

        if isinstance(collections_json, dict) and "collections" in collections_json:
            for collection in collections_json.get("collections", []):
                if isinstance(collection, dict) and "name" in collection and "id" in collection:
                    _COLLECTION_ID_MAP[collection["name"]] = collection["id"]
                    _COLLECTION_ID_TIMESTAMPS[collection["name"]] = now
            return {"collections": collections_json.get("collections", [])}

        return {"collections": []}
    except Exception as e:
        logger.error(f" 컬렉션 목록 조회 실패: {e}")
        return {"error": str(e)}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컬렉션 생성
# --->
# 컬렉션 생성
# Args:
# collection_name: 컬렉션 이름
# metadata: 메타데이터
# Returns:
# dict: 생성된 컬렉션 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def create_collection(collection_name=None, metadata=None):
    from agri_ai_core.src.chroma.utils import _sanitize_for_json, _embedding_dim

    try:
        collections = list_collections()
        if "collections" in collections:
            for col in collections["collections"]:
                if col.get("name") == collection_name:
                    _COLLECTION_ID_MAP[collection_name] = col.get("id")
                    return {"id": col.get("id"), "name": collection_name}

        payload_metadata = metadata or {
            "description": "자동 생성된 컬렉션입니다.",
            "created_at": datetime.now().isoformat()
        }
        payload = {
            "name": collection_name,
            "metadata": _sanitize_for_json(payload_metadata)
        }

        url = f"{CHROMA_API_BASE}/collections"
        status_code, result, text = _http_request("POST", url, payload=payload, timeout=10)
        if status_code in [200, 201]:
            if not isinstance(result, dict):
                result = {"name": collection_name}
            _COLLECTION_ID_MAP[collection_name] = result.get("id")
            logger.info(f" 컬렉션 '{collection_name}' 생성 성공 (dim={_embedding_dim()}): {result}")
            return result
        else:
            logger.error(f" 컬렉션 '{collection_name}' 생성 실패: {status_code} - {text}")

            collection_id = _COLLECTION_ID_MAP.get(collection_name)
            if collection_id:
                return {"id": collection_id, "name": collection_name}

            return {"error": f"컬렉션 생성 실패: {status_code} {text}"}
    except Exception as e:
        logger.error(f" 컬렉션 '{collection_name}' 생성 실패: {e}")

        collection_id = _COLLECTION_ID_MAP.get(collection_name)
        if collection_id:
            return {"id": collection_id, "name": collection_name}

        return {"error": str(e)}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 필수 컬렉션 존재 확인 및 생성
# --->
# 필수 컬렉션 존재 확인 및 생성
# Returns:
# bool: 성공 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def ensure_required_collections_exist():
    try:
        names = [
            settings.collections.farm_knowledge or '',
            settings.collections.document or '',
            settings.collections.conversation or '',
            settings.collections.web_knowledge or '',
        ]
        for name in [n for n in names if n]:
            result = create_collection(name)
            if "error" in result and "already exists" not in result.get("message", ""):
                logger.error(f"[ensure_required_collections_exist] 컬렉션 생성 실패: {name} → {result}")

        existing_result = list_collections()
        if "error" in existing_result:
            logger.error(f" 컬렉션 목록 조회 실패: {existing_result['error']}")
            return False
        if "collections" not in existing_result:
            logger.error(" 컬렉션 목록 응답에 'collections' 키가 없음")
            return False

        existing_names = [col["name"] for col in existing_result["collections"]]
        expected_names = list(_COLLECTION_ID_MAP.keys())

        missing = set(expected_names) - set(existing_names)
        if missing:
            logger.warning(f" 누락된 컬렉션: {missing}")
            for name in missing:
                metadata = {
                    "created_by": "ensure_required_collections_exist",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                result = create_collection(name, metadata=metadata)
                if "error" in result:
                    logger.error(f"[ensure_required_collections_exist] 컬렉션 생성 실패 - '{name}': {result['error']}")
                    return False

        logger.info(" 모든 필수 컬렉션 존재 여부 확인 완료 - 정상")
        return True
    except Exception as e:
        logger.error(f" ensure_required_collections_exist 예외 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
