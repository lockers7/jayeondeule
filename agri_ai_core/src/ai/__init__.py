"""AI Module - LLM, RAG, Learning, MCP"""

__all__ = [
    "get_llm_response_with_tools",
    "initialize_background_warmup",
    "query_llm_simple",
    "embed_text",
    "llm_document_process",
    "verify_chroma_connection",
    "update_ollama_model",
    "search_web",
    "get_current_weather",
]


def __getattr__(name):
    # LLM
    if name in {"get_llm_response_with_tools", "initialize_background_warmup"}:
        from agri_ai_core.src.ai.llm_client import (
            get_llm_response_with_tools,
            initialize_background_warmup,
        )
        return locals()[name]

    # Query handling
    if name == "query_llm_simple":
        from agri_ai_core.src.ai.query_handler_simple import query_llm_simple
        return query_llm_simple

    # RAG
    if name in {"embed_text", "llm_document_process"}:
        from agri_ai_core.src.ai.rag import embed_text, llm_document_process
        return locals()[name]

    # Learning
    if name in {"verify_chroma_connection", "update_ollama_model"}:
        from agri_ai_core.src.ai.learning import verify_chroma_connection, update_ollama_model
        return locals()[name]

    # MCP
    if name in {"search_web", "get_current_weather"}:
        from agri_ai_core.src.ai.mcp_client import search_web, get_current_weather
        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
