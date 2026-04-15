# ═══════════════════
# RAG 모듈 공통 상수 (하위 호환 re-export)
# 실제 정의는 document_processor.py 로 이동됨.
# 기존 import 경로(agri_ai_core.src.ai.rag.constants)는 계속 유효.
# ═══════════════════
from agri_ai_core.src.ai.rag.document_processor import DOC_TYPE_LABELS

__all__ = ["DOC_TYPE_LABELS"]
