# ══════════════════════════════════════════════════════════════════════════════
# test_rag_flatten_fix — RAG 이중 평탄화(KeyError 0) 회귀 검증
#
# chroma.operations.query_documents 는 [[...]]→[...] 평탄화해 반환한다.
# 소비자(ai_doc_rag / ai_rag_context)가 추가 [0] 인덱싱(이중 평탄화)을 하면
# metas[0] → KeyError(0) 로 검색이 실패하므로 평탄/중첩 양쪽 파싱을 검증.
#
# 파일 시작 함수 목록:
#   test_doc_rag_flat_shape      : 평탄 형태(실제 반환) 정상 파싱
#   test_doc_rag_nested_shape    : 중첩 형태도 수용(방어)
#   test_similar_flat_shape      : 유사시기 RAG 평탄 형태 정상 파싱
#   test_doc_rag_empty_result    : 빈 결과 안전
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

FLAT = {
    "documents": ["문서A 내용", "문서B 내용"],
    "metadatas": [{"title": "A", "data_type": "domain_knowledge"},
                  {"title": "B", "data_type": "domain_knowledge"}],
    "distances": [0.12, 0.34],
}
NESTED = {
    "documents": [["문서A 내용", "문서B 내용"]],
    "metadatas": [[{"title": "A"}, {"title": "B"}]],
    "distances": [[0.12, 0.34]],
}


def _patches(result, module_coll, coll_name):
    return [
        patch(f"agri_ai_core.src.chroma.collections.{module_coll}", return_value=coll_name),
        patch("agri_ai_core.src.ai.embedder.embed_text", return_value=[0.1] * 8),
        patch("agri_ai_core.src.chroma.operations.query_documents", return_value=result),
    ]


def test_doc_rag_flat_shape():
    from agri_ai_core.src.control.ai_doc_rag import query_domain_knowledge
    ps = _patches(FLAT, "document_collection", "document_collection")
    with ps[0], ps[1], ps[2]:
        out = query_domain_knowledge("수온 관리")
    assert len(out) == 2
    assert out[0]["document"] == "문서A 내용"
    assert out[0]["metadata"]["title"] == "A"
    assert out[0]["distance"] == 0.12


def test_doc_rag_nested_shape():
    from agri_ai_core.src.control.ai_doc_rag import query_domain_knowledge
    ps = _patches(NESTED, "document_collection", "document_collection")
    with ps[0], ps[1], ps[2]:
        out = query_domain_knowledge("수온 관리")
    assert len(out) == 2
    assert out[1]["document"] == "문서B 내용"


def test_similar_flat_shape():
    from agri_ai_core.src.control.ai_rag_context import query_similar_periods
    flat = dict(FLAT)
    flat["metadatas"] = [{"farm_id": "1", "house_id": "2", "data_type": "growth_rag"},
                         {"farm_id": "1", "house_id": "2", "data_type": "growth_rag"}]
    ps = _patches(flat, "farm_knowledge_collection", "farm_knowledge")
    with ps[0], ps[1], ps[2]:
        out = query_similar_periods(1, 2, {"indoor_temperature": 25.0,
                                           "indoor_humidity": 80.0, "co2": 900,
                                           "water_temperature": 20.0})
    assert len(out) == 2
    assert out[0]["document"] == "문서A 내용"
    assert out[0]["distance"] == 0.12


def test_doc_rag_empty_result():
    from agri_ai_core.src.control.ai_doc_rag import query_domain_knowledge
    ps = _patches({"documents": [], "metadatas": [], "distances": []},
                  "document_collection", "document_collection")
    with ps[0], ps[1], ps[2]:
        out = query_domain_knowledge("수온 관리")
    assert out == []
