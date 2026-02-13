"""ChromaDB vector store module"""
from agri_ai_core.src.chroma.client import heartbeat, get_collection, list_collections, ensure_required_collections_exist
from agri_ai_core.src.chroma.operations import add_document, get_documents, query_documents, upsert_documents_with_embedding

__all__ = [
    "heartbeat",
    "get_collection",
    "list_collections",
    "ensure_required_collections_exist",
    "add_document",
    "get_documents",
    "query_documents",
    "upsert_documents_with_embedding",
    "update_learned_last_status",
    "get_unlearned_data",
    "search_similar_data",
]


# Lazy imports to avoid circular import with loader
def __getattr__(name):
    if name in ("update_learned_last_status", "get_unlearned_data", "search_similar_data"):
        from agri_ai_core.src.chroma.loader import update_learned_last_status, get_unlearned_data, search_similar_data
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
