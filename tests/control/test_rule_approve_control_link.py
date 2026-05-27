# ══════════════════════════════════════════════════════════════════════════════
# test_rule_approve_control_link — 승인 룰 → 제어 LLM 연결 검증
#
# register_approved_rule 은 domain_rule 컬렉션과 함께, 제어 도메인RAG 가
# 소비하는 document_collection(data_type=domain_knowledge) 에도 이중 upsert
# 해야 승인 룰이 제어 LLM 에 반영된다.
#
# 파일 시작 함수 목록:
#   test_approve_upserts_both_collections : 두 컬렉션 모두 upsert + 메타 정합
#   test_doc_id_idempotent_prefix         : doc_id=rule_{rid} 멱등 규칙
#   test_control_rag_save_failure_fails   : 제어RAG 반영 실패 시 승인 실패 반환
#   test_domain_rule_failure_no_doc_save  : 1차(domain_rule) 실패 시 2차 미시도
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

from agri_ai_core.src.control.ai_self_evolve import register_approved_rule


def _run(domain_ok=True, doc_ok=True, rule_id="r1"):
    calls = []

    def fake_upsert(coll, docs):
        calls.append((coll, docs))
        if coll == "domain_rule":
            return {"success": domain_ok}
        return {"success": doc_ok}

    with patch("agri_ai_core.src.chroma.collections.domain_rule_collection",
               return_value="domain_rule"), \
         patch("agri_ai_core.src.chroma.collections.document_collection",
               return_value="document_collection"), \
         patch("agri_ai_core.src.chroma.operations.upsert_documents_with_embedding",
               side_effect=fake_upsert):
        r = register_approved_rule(
            title="테스트룰", content="CO2 2000 초과 시 배기순환",
            rule_id=rule_id, farm_id=1, source="admin_approve",
        )
    return r, calls


def test_approve_upserts_both_collections():
    r, calls = _run()
    assert r["success"] is True and r["rule_id"] == "r1"
    colls = [c[0] for c in calls]
    assert colls == ["domain_rule", "document_collection"]
    # 제어 도메인RAG where 필터와 일치하는 메타
    doc = calls[1][1][0]
    assert doc["metadata"]["data_type"] == "domain_knowledge"
    assert doc["metadata"]["source"] == "admin_approve"


def test_doc_id_idempotent_prefix():
    r, calls = _run(rule_id="learned_abc")
    assert calls[1][1][0]["doc_id"] == "rule_learned_abc"  # 재승인 시 동일 id 로 갱신


def test_control_rag_save_failure_fails():
    r, calls = _run(doc_ok=False)
    assert r["success"] is False
    assert "제어RAG" in r["error"]


def test_domain_rule_failure_no_doc_save():
    r, calls = _run(domain_ok=False)
    assert r["success"] is False
    assert [c[0] for c in calls] == ["domain_rule"]  # 2차 미시도
