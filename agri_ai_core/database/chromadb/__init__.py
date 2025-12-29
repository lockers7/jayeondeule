# client 모듈 함수들만 먼저 노출 (operations는 client에 의존하므로)
from agri_ai_core.database.chromadb.client import (
    heartbeat,
    get_version,
    list_collections,
    create_collection,
    get_collection,
    get_collection_id_from_name,
    ensure_required_collections_exist
)

__all__ = [
    # client
    "heartbeat",
    "get_version",
    "list_collections",
    "create_collection",
    "get_collection",
    "get_collection_id_from_name",
    "ensure_required_collections_exist",
]


# operations 모듈 함수들은 지연 로드 (lazy import)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Lazy import for operations module functions
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def __getattr__(name):
    operations_funcs = [
        "add_document",
        "get_documents",
        "delete_document",
        "upsert_collection_data",
        "upsert_documents_with_embedding",
        "query_documents",
    ]
    if name in operations_funcs:
        from agri_ai_core.database.chromadb import operations
        return getattr(operations, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
