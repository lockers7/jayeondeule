# ════════════════════════════════════════════════════════════════════
# ChromaDB 클라이언트 계층
# REST API(v2) 통신, 컬렉션 ID 캐시, heartbeat, 컬렉션 생성/조회 관리.
# MCP 클라이언트를 통해 HTTP 통신하며, 컬렉션 ID는 TTL 캐시로 성능 최적화.
# --->
# _http_request: MCP 기반 HTTP 통신 래퍼 (GET/POST 등)
# get_chroma_url: API URL 생성 (collection_id 유무에 따라 분기)
# heartbeat: ChromaDB 서버 생존 확인
# _is_valid_uuid: UUID 형태의 컬렉션 ID 유효성 검사
# _refresh_collection_ids: 전체 컬렉션 ID 캐시 재조회
# get_collection_id_from_name: 이름으로 컬렉션 ID 조회 (TTL 캐시 활용)
# get_collection: 이름으로 컬렉션 조회, 없으면 생성 반환
# list_collections: 전체 컬렉션 목록 조회 + 캐시 갱신
# create_collection: 컬렉션 생성 (중복 시 기존 ID 반환)
# ensure_required_collections_exist: 설정에 정의된 필수 컬렉션 존재 보장
# ════════════════════════════════════════════════════════════════════
import time
from datetime import datetime

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import settings
from agri_ai_core.src.utils.http_client import http_json_request
from agri_ai_core.src.chroma.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    CHROMA_API_BASE,
    _COLLECTION_ID_MAP,
    _COLLECTION_ID_TIMESTAMPS,
    _COLLECTION_CACHE_TTL,
)

logger = setup_logger(__name__)


def _http_request(method: str, url: str, payload=None, timeout: int = 10):
    """ChromaDB REST API로 HTTP 요청. Returns: (status_code, data, raw_text)."""
    normalized_method = (method or "GET").upper()
    logger.debug(f"[ChromaDB-{normalized_method}] url={url}, payload={payload}, timeout={timeout}")
    status_code, data, text = http_json_request(
        method=normalized_method,
        url=url,
        json_body=payload,
        timeout=timeout,
    )
    logger.debug(f"[ChromaDB-{normalized_method}] 응답: status={status_code}, data_type={type(data).__name__}")
    return status_code, data, text


# ═════════════════════
# ChromaDB API URL 생성
# ═════════════════════
def get_chroma_url(endpoint: str, collection_id: str = None):
    """API v2 URL 빌더. collection_id가 있으면 컬렉션별 엔드포인트 생성."""
    base = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2"
    if collection_id:
        return f"{base}/collections/{collection_id}/{endpoint}"
    return f"{base}/{endpoint}"


# ══════════════════════════
# 서버 연결 확인 (heartbeat)
# ══════════════════════════
def heartbeat():
    """ChromaDB 서버 생존 확인. 성공 시 서버 정보 dict, 실패 시 {'error': ...}."""
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



# ═══════════════════════
# 컬렉션 이름으로 ID 조회
# ═══════════════════════
def _is_valid_uuid(value):
    """간이 UUID 형식 검사 (하이픈 포함 또는 36자)."""
    return isinstance(value, str) and ("-" in value or len(value) == 36)


# ══════════════════════════════════════════════════════════
# list_collections()를 호출하여 모든 컬렉션 ID를 캐시에 갱신
# ══════════════════════════════════════════════════════════
def _refresh_collection_ids():
    """전체 컬렉션 목록을 조회하여 이름↔ID 매핑 캐시를 갱신한다."""
    logger.debug("[_refresh_collection_ids] 컬렉션 ID 캐시 갱신 시작")
    now = time.time()
    collections = list_collections().get("collections", [])
    for col in collections:
        _COLLECTION_ID_MAP[col["name"]] = col["id"]
        _COLLECTION_ID_TIMESTAMPS[col["name"]] = now
    logger.debug(f"[_refresh_collection_ids] 컬렉션 ID 캐시 갱신 완료: {len(collections)}건")


def get_collection_id_from_name(collection_name):
    """이름으로 컬렉션 UUID 조회. TTL 캐시 적중 시 heartbeat 생략 (성능 최적화)."""
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


# ══════════════════
# 컬렉션 조회
# ══════════════════
def get_collection(collection_name):
    """컬렉션 메타데이터 조회. 존재하지 않으면 자동 생성."""
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


# ══════════════════
# 컬렉션 목록 조회
# ══════════════════
def list_collections():
    """전체 컬렉션 목록 조회 + 이름↔ID 캐시 자동 갱신."""
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


# ══════════════════
# 컬렉션 생성
# ══════════════════
def create_collection(collection_name=None, metadata=None):
    """컬렉션 생성 (이미 존재하면 기존 ID 반환, 실제 재생성 안 함)."""
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


# ═════════════════════════════
# 필수 컬렉션 존재 확인 및 생성
# ═════════════════════════════
def ensure_required_collections_exist():
    """설정(settings.collections)에 정의된 필수 컬렉션들이 모두 존재하도록 보장.
    시스템 기동 시 1회 호출 (startup.py). 반환: True=정상, False=오류."""
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
            logger.error(f" 누락된 컬렉션: {missing}")
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
