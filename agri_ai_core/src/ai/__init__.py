"""AI Module - LLM, RAG, and Learning"""

# LLM
from agri_ai_core.src.ai.llm_client import (
    get_llm_response,
    get_llm_streaming_response,
    initialize_background_warmup,
)

# Query Handling
from agri_ai_core.src.ai.query_handler import query_llm_unified, process_llm_query_simple

# RAG
from agri_ai_core.src.ai.rag import embed_text, llm_document_process

# Learning
from agri_ai_core.src.ai.learning import verify_chroma_connection, update_ollama_model

# MCP Integration
from agri_ai_core.src.ai.mcp_client import search_web, get_current_weather

__all__ = [
    # LLM
    "get_llm_response",
    "get_llm_streaming_response",
    "initialize_background_warmup",
    # Query
    "query_llm_unified",
    "process_llm_query_simple",
    # RAG
    "embed_text",
    "llm_document_process",
    # Learning
    "verify_chroma_connection",
    "update_ollama_model",
    # MCP
    "search_web",
    "get_current_weather",
]
