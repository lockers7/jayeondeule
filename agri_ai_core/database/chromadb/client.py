# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 클라이언트 모듈
# 벡터 데이터베이스 연결 및 기본 API 통신을 담당하며,
# heartbeat, 컬렉션 관리 등의 기본 기능을 제공합니다.
# --->
# get_chroma_url: ChromaDB API URL 생성
# heartbeat: ChromaDB 서버 상태 확인
# get_version: ChromaDB 서버 버전 확인
# get_collection_id_from_name: 컬렉션 이름으로 ID 조회
# get_collection: 컬렉션 정보 조회 (없으면 생성)
# list_collections: 모든 컬렉션 목록 조회
# create_collection: 컬렉션 생성
# ensure_required_collections_exist: 필수 컬렉션 존재 확인 및 생성
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import requests
from datetime import datetime

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.shared_modules.config.settings import settings

logger = setup_logger(__name__)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Chroma API 기본 경로 설정 (v2 엔드포인트 기준)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
CHROMA_HOST = settings.vector.http_host or "127.0.0.1"
CHROMA_PORT = settings.vector.http_port or 8000

TENANT = "default_tenant"
DATABASE = "default_database"
CHROMA_API_BASE = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2/tenants/{TENANT}/databases/{DATABASE}"

# 컬렉션 ID 캐시
_COLLECTION_ID_MAP = {
    "farm_collection": "farm_collection",
    "source_collection": "source_collection",
    "stats_collection": "stats_collection",
    "optimal_collection": "optimal_collection",
    "learned_collection": "learned_collection",
    "setting_collection": "setting_collection",
    "document_collection": "document_collection",
    "last_learned_date": "last_learned_date",
}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 임베딩 차원 반환
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _embedding_dim() -> int:
    return settings.embedding_dim


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
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json()
        else:
            logger.warning(f"서버 상태 확인 실패: 상태 코드 {res.status_code}")
            return {"error": f"서버 상태 확인 실패: {res.status_code}"}
    except Exception as e:
        logger.error(f"서버 상태 확인 중 오류: {e}")
        return {"error": f"서버 상태 확인 중 오류: {e}"}


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB 버전 확인
# --->
# ChromaDB 서버 버전 확인
# Returns:
# str: 버전 정보
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_version():
    try:
        url = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2/version"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            version = res.json() if res.headers.get("content-type") == "application/json" else res.text
            logger.info(f" ChromaDB 서버 버전 정보 확인 완료 버젼: {version}")
            return version
        else:
            logger.warning(f" 버전 확인 실패: {res.status_code}")
            return "unknown"
    except Exception as e:
        logger.exception(f" 버전 조회 예외 발생: {e}")
        return "error"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 컬렉션 이름으로 ID 조회
# --->
# 컬렉션 이름으로 ID 조회
# Args:
# collection_name: 컬렉션 이름
# Returns:
# str: 컬렉션 ID 또는 None
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_collection_id_from_name(collection_name):
    status = heartbeat()
    if "error" in status:
        logger.error("ChromaDB 연결 실패. 캐시 초기화 불가")
        return None

    cached = _COLLECTION_ID_MAP.get(collection_name)
    if cached:
        if isinstance(cached, str) and ("-" in cached or len(cached) == 36):
            return cached
        try:
            collections = list_collections().get("collections", [])
            for col in collections:
                _COLLECTION_ID_MAP[col["name"]] = col["id"]
            refreshed = _COLLECTION_ID_MAP.get(collection_name)
            if refreshed:
                return refreshed
        except Exception:
            pass

    collections = list_collections().get("collections", [])
    for col in collections:
        _COLLECTION_ID_MAP[col["name"]] = col["id"]

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
            res = requests.get(url)
            if res.status_code == 200:
                return res.json()

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
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        collections_json = res.json()

        if isinstance(collections_json, list):
            for collection in collections_json:
                if isinstance(collection, dict) and "name" in collection and "id" in collection:
                    _COLLECTION_ID_MAP[collection["name"]] = collection["id"]
            return {"collections": collections_json}

        if isinstance(collections_json, dict) and "collections" in collections_json:
            for collection in collections_json.get("collections", []):
                if isinstance(collection, dict) and "name" in collection and "id" in collection:
                    _COLLECTION_ID_MAP[collection["name"]] = collection["id"]
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
    from agri_ai_core.database.chromadb.operations import _sanitize_for_json

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
        res = requests.post(url, json=payload)
        if res.status_code in [200, 201]:
            result = res.json()
            _COLLECTION_ID_MAP[collection_name] = result.get("id")
            logger.info(f" 컬렉션 '{collection_name}' 생성 성공 (dim={_embedding_dim()}): {result}")
            return result
        else:
            logger.error(f" 컬렉션 '{collection_name}' 생성 실패: {res.status_code} - {res.text}")

            collection_id = _COLLECTION_ID_MAP.get(collection_name)
            if collection_id:
                return {"id": collection_id, "name": collection_name}

            return {"error": f"컬렉션 생성 실패: {res.status_code} {res.text}"}
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
            settings.collections.farm or '',
            settings.collections.source or '',
            settings.collections.stats or '',
            settings.collections.optimal or '',
            settings.collections.learned or '',
            settings.collections.setting or '',
            settings.collections.docs_learned or '',
            settings.collections.last_learned or '',
            settings.collections.self_learned or '',
            settings.collections.pattern_learned or '',
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
