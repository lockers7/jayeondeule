# ═══════════════════════════════════════════════════════════════════════════
# 단위테스트 — RAG 무캐시(매 호출 실시간 조회) 정책 검증.
#
# 검증:
#   1) ai_rag_context.query_similar_periods 가 매 호출마다 embed_text 호출
#   2) ai_doc_rag.query_domain_knowledge 가 매 호출마다 embed_text 호출
#   3) chroma 컬렉션 비활성/실패 시 빈 list 반환
#   4) 임베딩 실패 시 빈 list 반환
#   5) 검색 결과 정상 평탄화
# ═══════════════════════════════════════════════════════════════════════════
from unittest.mock import MagicMock

import pytest

import agri_ai_core.src.control.ai_rag_context as rag_ctx
import agri_ai_core.src.control.ai_doc_rag as doc_rag


# ════════════════════════════════════════════════════════════════════
# 1) ai_rag_context — 매 호출마다 embed_text 호출 (캐시 없음)
# ════════════════════════════════════════════════════════════════════
def test_rag_context_no_cache_calls_embed_each_time(monkeypatch):
    embed_calls = {'count': 0}

    def _fake_embed(text):
        embed_calls['count'] += 1
        return [0.1] * 16

    monkeypatch.setattr('agri_ai_core.src.ai.embedder.embed_text', _fake_embed)
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.collections.farm_knowledge_collection',
        lambda: 'farm_knowledge')
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.operations.query_documents',
        lambda *a, **k: {
            'documents': [['doc1']],
            'metadatas': [[{'crop_level': '생육기'}]],
            'distances': [[0.1]],
        })

    sensor = {'indoor_temperature': 25.0}
    rag_ctx.query_similar_periods(1, 1, sensor)
    rag_ctx.query_similar_periods(1, 1, sensor)
    rag_ctx.query_similar_periods(1, 1, sensor)
    assert embed_calls['count'] == 3, "캐시가 살아있음 — embed_text 호출 횟수 부족"


# ════════════════════════════════════════════════════════════════════
# 2) ai_doc_rag — 매 호출마다 embed_text 호출
# ════════════════════════════════════════════════════════════════════
def test_doc_rag_no_cache_calls_embed_each_time(monkeypatch):
    embed_calls = {'count': 0}

    def _fake_embed(text):
        embed_calls['count'] += 1
        return [0.2] * 16

    monkeypatch.setattr('agri_ai_core.src.ai.embedder.embed_text', _fake_embed)
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.collections.document_collection',
        lambda: 'document_collection')
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.operations.query_documents',
        lambda *a, **k: {
            'documents': [['doc1']],
            'metadatas': [[{'category': '운영노하우'}]],
            'distances': [[0.05]],
        })

    doc_rag.query_domain_knowledge('수온히터 동작 원리')
    doc_rag.query_domain_knowledge('수온히터 동작 원리')   # 동일 query 도 재호출
    doc_rag.query_domain_knowledge('포그생성 임계값')
    assert embed_calls['count'] == 3, "캐시가 살아있음 — 동일 query 재호출 시 embed 안 됨"


# ════════════════════════════════════════════════════════════════════
# 3) ai_rag_context — 컬렉션 None → 빈 list, embed 호출 X
# ════════════════════════════════════════════════════════════════════
def test_rag_context_no_collection_returns_empty(monkeypatch):
    embed_calls = {'count': 0}

    def _fake_embed(text):
        embed_calls['count'] += 1
        return [0.1] * 16

    monkeypatch.setattr('agri_ai_core.src.ai.embedder.embed_text', _fake_embed)
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.collections.farm_knowledge_collection',
        lambda: None)

    out = rag_ctx.query_similar_periods(1, 1, {'indoor_temperature': 25.0})
    assert out == []
    assert embed_calls['count'] == 0


# ════════════════════════════════════════════════════════════════════
# 4) ai_doc_rag — 임베딩 실패(None) → 빈 list
# ════════════════════════════════════════════════════════════════════
def test_doc_rag_embed_failure_returns_empty(monkeypatch):
    monkeypatch.setattr('agri_ai_core.src.ai.embedder.embed_text', lambda t: None)
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.collections.document_collection',
        lambda: 'doc_coll')

    out = doc_rag.query_domain_knowledge('test')
    assert out == []


# ════════════════════════════════════════════════════════════════════
# 5) 검색 결과 평탄화 — documents/metadatas/distances 정상 매핑
# ════════════════════════════════════════════════════════════════════
def test_rag_context_result_flattening(monkeypatch):
    monkeypatch.setattr('agri_ai_core.src.ai.embedder.embed_text', lambda t: [0.1])
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.collections.farm_knowledge_collection',
        lambda: 'farm_knowledge')
    monkeypatch.setattr(
        'agri_ai_core.src.chroma.operations.query_documents',
        lambda *a, **k: {
            'documents': [['DOC-A', 'DOC-B']],
            'metadatas': [[{'season': '봄'}, {'season': '여름'}]],
            'distances': [[0.1, 0.2]],
        })

    out = rag_ctx.query_similar_periods(1, 1, {'indoor_temperature': 25.0}, top_k=2)
    assert len(out) == 2
    assert out[0]['document'] == 'DOC-A'
    assert out[0]['metadata']['season'] == '봄'
    assert out[0]['distance'] == 0.1
    assert out[1]['document'] == 'DOC-B'


# ════════════════════════════════════════════════════════════════════
# 6) 캐시 변수가 더 이상 모듈에 없어야 함 (회귀 방지)
# ════════════════════════════════════════════════════════════════════
def test_no_cache_vars_remaining():
    assert not hasattr(rag_ctx, '_RAG_CACHE'), \
        "ai_rag_context._RAG_CACHE 가 남아있음 — 캐시 제거 누락"
    assert not hasattr(rag_ctx, '_RAG_CACHE_TTL_SEC'), \
        "ai_rag_context._RAG_CACHE_TTL_SEC 가 남아있음 — 캐시 제거 누락"
    assert not hasattr(doc_rag, '_DOC_RAG_CACHE'), \
        "ai_doc_rag._DOC_RAG_CACHE 가 남아있음 — 캐시 제거 누락"
    assert not hasattr(doc_rag, '_DOC_RAG_CACHE_TTL_SEC'), \
        "ai_doc_rag._DOC_RAG_CACHE_TTL_SEC 가 남아있음 — 캐시 제거 누락"
