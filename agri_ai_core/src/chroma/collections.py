# ════════════════════════════════════════════════════════════════════
# ChromaDB 컬렉션 이름 게터 — settings.collections 의 6개 컬렉션 별칭.
# --->
# farm_knowledge_collection : 농장 지식 RAG 컬렉션 이름
# document_collection       : 업로드된 문서 RAG 컬렉션 이름
# conversation_collection   : 대화 요약 RAG 컬렉션 (농장주별 관심/패턴)
# web_knowledge_collection  : 웹 검색 누적 + LLM 지식 캐시 컬렉션
# prompt_chunk_collection   : [프롬프트 자동화] 시스템/유저/분석/답변 프롬프트 chunk
# domain_rule_collection    : [프롬프트 자동화] 결합 규칙·안전 룰·사용자 학습 룰
# ════════════════════════════════════════════════════════════════════
from agri_ai_core.config import settings


# ────────────────────────────────────────────────────────────────────
# 농장 지식 RAG 컬렉션 이름 반환.
# ────────────────────────────────────────────────────────────────────
def farm_knowledge_collection():
    return settings.collections.farm_knowledge or ''


# ────────────────────────────────────────────────────────────────────
# 업로드된 문서 RAG 컬렉션 이름 반환.
# ────────────────────────────────────────────────────────────────────
def document_collection():
    return settings.collections.document or ''


# ────────────────────────────────────────────────────────────────────
# 대화 요약 RAG 컬렉션 이름 반환 (농장주별 관심/패턴).
# ────────────────────────────────────────────────────────────────────
def conversation_collection():
    return settings.collections.conversation or ''


# ────────────────────────────────────────────────────────────────────
# 웹 검색 누적 + LLM 지식 캐시 컬렉션 이름 반환.
# ────────────────────────────────────────────────────────────────────
def web_knowledge_collection():
    return settings.collections.web_knowledge or ''


# ────────────────────────────────────────────────────────────────────
# [프롬프트 자동화] 시스템/유저/분석/답변 프롬프트 chunk 컬렉션 이름 반환.
# 학습 진화 가능 — chunk 추가/수정 시 다음 LLM 호출부터 자동 반영.
# ────────────────────────────────────────────────────────────────────
def prompt_chunk_collection():
    return settings.collections.prompt_chunk or 'prompt_chunk'


# ────────────────────────────────────────────────────────────────────
# [프롬프트 자동화] 결합 규칙·안전 룰·사용자 학습 룰 컬렉션 이름 반환.
# 사용자가 채팅으로 가르친 룰 + 시스템 결합 룰 통합 저장. 의미 검색.
# ────────────────────────────────────────────────────────────────────
def domain_rule_collection():
    return settings.collections.domain_rule or 'domain_rule'
