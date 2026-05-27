# ══════════════════════════════════════════════════════════════════════════════
# test_knowledge_scope — 도메인 지식의 권한 귀속·농장 스코프 검증 (농장주 명세)
#
# 명세: 농장관리자의 지식 저장은 자기 농장으로 자동 귀속(타 농장/전역 지정 무시),
#       admin 은 지정값(전역 '0' 포함) 허용. 제어 LLM 의 지식 검색은
#       [해당 농장 ∨ 전역(0)] 만 매칭 — 타 농장 지식이 제어에 새지 않아야 함.
#
# 파일 시작 함수 목록:
#   test_save_farmer_forced_to_own_farm : 농장관리자 → 자기 농장 강제(+안내문)
#   test_save_admin_scope_choice        : admin → 지정값(0/1/2) 그대로
#   test_query_farm_scope_where         : 검색 where 가 [농장 ∨ 0] 구조
#   test_query_live_farm_isolation      : 실데이터 — farm1 은 조회, farm2 는 0건
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.control import ai_doc_rag


def _mock_add(monkeypatch, saved):
    def fake_add(collection_name, doc_id, text, metadata, embedding=None):
        saved.update(meta=metadata)
        return {"success": True}
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document", fake_add)
    monkeypatch.setattr("agri_ai_core.src.chroma.operations._build_embedding_from_text",
                        lambda t: [0.1] * 8)


def test_save_farmer_forced_to_own_farm(monkeypatch):
    saved = {}
    _mock_add(monkeypatch, saved)
    r = ai_doc_rag.save_domain_knowledge("테스트 룰", "본문", farm_id="2", auth_farm_id="1")
    assert r["success"] and saved["meta"]["farm_id"] == "1"
    assert "본인 농장" in r["message"]            # 강제 귀속 안내 포함
    r2 = ai_doc_rag.save_domain_knowledge("테스트 룰2", "본문", farm_id="0", auth_farm_id="1")
    assert saved["meta"]["farm_id"] == "1"         # 전역(0) 지정도 자기 농장 강제
    r3 = ai_doc_rag.save_domain_knowledge("테스트 룰3", "본문", auth_farm_id="1")
    assert saved["meta"]["farm_id"] == "1" and "본인 농장" not in r3["message"]


def test_save_admin_scope_choice(monkeypatch):
    saved = {}
    _mock_add(monkeypatch, saved)
    ai_doc_rag.save_domain_knowledge("전역 룰", "본문", farm_id="0", auth_farm_id=None)
    assert saved["meta"]["farm_id"] == "0"         # admin 전역 저장 허용
    ai_doc_rag.save_domain_knowledge("고흥 룰", "본문", farm_id="2", auth_farm_id=None)
    assert saved["meta"]["farm_id"] == "2"         # admin 타 농장 선택 허용


def test_query_farm_scope_where(monkeypatch):
    captured = {}
    def fake_query(coll, query_embeddings=None, n_results=5, where=None, include=None, **kw):
        captured["where"] = where
        return {"documents": [], "metadatas": [], "distances": []}
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.query_documents", fake_query)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 8)

    ai_doc_rag.query_domain_knowledge("수온 룰", farm_id="1")
    w = captured["where"]
    assert "$and" in w and {"farm_id": {"$eq": "1"}} in w["$and"][1]["$or"]
    assert {"farm_id": {"$eq": "0"}} in w["$and"][1]["$or"]
    ai_doc_rag.query_domain_knowledge("수온 룰")     # 미지정 — 기존 호환(전체)
    assert captured["where"] == {"data_type": "domain_knowledge"}


def test_query_live_farm_isolation():
    # 실데이터 불변식: farm2 검색 결과에 farm1 전용 지식이 섞이면 안 됨 (전역 0 은 허용)
    r1 = ai_doc_rag.query_domain_knowledge("배출밸브 배기순환 CO2", farm_id="1")
    r2 = ai_doc_rag.query_domain_knowledge("배출밸브 배기순환 CO2", farm_id="2")
    assert len(r1) >= 1
    assert all(str((d.get("metadata") or {}).get("farm_id")) in ("2", "0") for d in r2)
