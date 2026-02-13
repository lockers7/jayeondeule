# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ChromaDB Configuration Module
# ChromaDB 연결 설정 및 상수 정의
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from agri_ai_core.shared_modules.config.settings import settings

# ChromaDB HTTP 연결 설정
CHROMA_HOST = settings.vector.http_host or "127.0.0.1"
CHROMA_PORT = settings.vector.http_port or 8000

# ChromaDB API 엔드포인트 설정
TENANT = "default_tenant"
DATABASE = "default_database"
CHROMA_API_BASE = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2/tenants/{TENANT}/databases/{DATABASE}"

# 컬렉션 ID 캐시 (성능 최적화)
_COLLECTION_ID_MAP = {
    "farm_collection": "farm_collection",
    "source_collection": "source_collection",
    "stats_collection": "stats_collection",
    "optimal_collection": "optimal_collection",
    "learned_collection": "learned_collection",
    "setting_collection": "setting_collection",
    "document_collection": "document_collection",
    "last_learned_date": "last_learned_date",
    "self_learned_collection": "self_learned_collection",
    "learning_pattern_collection": "learning_pattern_collection",
}

__all__ = [
    "CHROMA_HOST",
    "CHROMA_PORT",
    "TENANT",
    "DATABASE",
    "CHROMA_API_BASE",
    "_COLLECTION_ID_MAP",
]
