"""
AI 스마트팜 컨설턴트 - 설정 모듈
기존 agri_ai_core 환경(.env)을 활용하되, 별도 독립 실행 가능
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ChromaDB 1.5.x 호환: 레거시 환경변수 제거 (기존 .env의 CHROMA_DB_IMPL 충돌 방지)
os.environ.pop("CHROMA_DB_IMPL", None)

# --- Ollama 설정 ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.getenv("MODEL_NAME", "mistral-small3.2:latest")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "bge-m3")

# --- ChromaDB 설정 (로컬 PersistentClient - 기존 DB와 분리) ---
CHROMA_PERSIST_DIR = str(Path(__file__).parent / "chroma_db")

# --- SearXNG 웹검색 ---
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8888")

# --- 에이전트 설정 ---
MAX_TOOL_ITERATIONS = 5
RAG_TOP_K = 5
CHUNK_SIZE = 800
CHUNK_OVERLAP = 200

# --- Streamlit 설정 ---
PAGE_TITLE = "AI 스마트팜 컨설턴트"
PAGE_ICON = "🌱"
