# ═══════════════════════
# ChromaDB 연결 설정 및 상수 정의.
# ═══════════════════════
from agri_ai_core.config import settings

# ChromaDB HTTP 연결 설정
CHROMA_HOST = settings.vector.http_host or "127.0.0.1"
CHROMA_PORT = settings.vector.http_port or 8000

# ChromaDB API 엔드포인트 설정
TENANT = "default_tenant"
DATABASE = "default_database"
CHROMA_API_BASE = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2/tenants/{TENANT}/databases/{DATABASE}"

# 컬렉션 ID 캐시 (성능 최적화)
_COLLECTION_ID_MAP = {
    "farm_knowledge": "farm_knowledge",
    "document_collection": "document_collection",
    "conversation_collection": "conversation_collection",
    "web_knowledge": "web_knowledge",
}

# 컬렉션 ID 캐시 타임스탬프 (TTL 지원)
_COLLECTION_ID_TIMESTAMPS = {}
_COLLECTION_CACHE_TTL = 300  # 초 (5분)

__all__ = [
    "CHROMA_HOST",
    "CHROMA_PORT",
    "TENANT",
    "DATABASE",
    "CHROMA_API_BASE",
    "_COLLECTION_ID_MAP",
    "_COLLECTION_ID_TIMESTAMPS",
    "_COLLECTION_CACHE_TTL",
]
