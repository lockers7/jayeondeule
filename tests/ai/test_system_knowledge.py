# ══════════════════════════════════════════════════════════════════════════════
# test_system_knowledge — 시스템 자기지식 RAG + 자동 회상 + 자가학습 도구 검증
#
# 배경: 로컬 AI 가 로그/소스/DB 도구를 가졌으나 "무엇이 어디에" 를 몰라 오라우팅·
#   컬럼 환각을 냈다. 시스템 지식을 저장·회상해 도구 선택/SQL 컬럼을 사실에 맞춘다.
#   대화 모드 전용(제어 사이클 미개입) — analysis_lesson 루프와 동형.
#
# 파일 시작 함수 목록:
#   test_save_payload             : 저장 페이로드(임베딩·메타·카테고리·절단·key교체)
#   test_recall_format_and_filter : 회상 블록 형식 + 거리필터 + 스니펫 상한
#   test_recall_failsafe          : 임베더 다운 시 빈 블록(흐름 보존)
#   test_manage_tool_actions      : learn/list/delete/오액션 + 삭제 권한 가드
#   test_seed_uses_real_columns   : 시드가 실제 DB 컬럼을 반영(환각 차단)
#   test_registered_five_places   : 5중 등록(코드4 + DB) 무결성
#   test_analyzer_injects_sysknow : ANALYZER 가 시스템지식 블록을 시스템 메시지로 주입
# ══════════════════════════════════════════════════════════════════════════════
import inspect

from agri_ai_core.src.ai import system_knowledge as sk


def test_save_payload(monkeypatch):
    saved = {}
    deleted = []

    def fake_add(collection_name, doc_id, text, metadata, embedding=None):
        saved.update(doc_id=doc_id, text=text, meta=metadata, emb=embedding)
        return {"success": True}

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document", fake_add)
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.delete_document",
                        lambda c, ids=None: deleted.append(ids))
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)

    # 카테고리 검증 + key 고정 id(재저장=교체) + 절단
    r = sk.save_system_knowledge("릴레이 값은 relay_l_recording DB 에 있다 " + "x" * 900,
                                 category="db_schema", source="seed", key="db_relay")
    assert r["success"] and r["knowledge_id"] == "sysk_db_relay"
    assert saved["meta"]["data_type"] == "system_knowledge"
    assert saved["meta"]["category"] == "db_schema"
    assert saved["emb"] is not None                      # 0벡터 저장 방지
    assert len(saved["text"]) == sk._MAX_LEN             # 절단
    assert deleted == [["sysk_db_relay"]]               # key 지정 → 기존 교체

    # 잘못된 카테고리 → general 폴백
    r2 = sk.save_system_knowledge("유효한 길이의 시스템 사실입니다", category="엉뚱")
    assert r2["success"] and r2["category"] == "general"

    # 너무 짧음
    assert not sk.save_system_knowledge("짧음")["success"]


def test_recall_format_and_filter(monkeypatch):
    def fake_query(collection_name, query_embeddings=None, n_results=4, where=None,
                   include=None, **kw):
        return {
            "documents": ["릴레이 값은 relay_l_recording DB, db_read_query 로 조회", "X" * 500],
            "metadatas": [{"category": "db_schema"}, {"category": "logs"}],
            "distances": [0.2, 0.99],           # 두번째는 _RECALL_MAX_DIST 초과
        }

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.query_documents", fake_query)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)

    seen = {}
    real_query = fake_query

    def capture(collection_name, query_embeddings=None, n_results=4, where=None, include=None, **kw):
        seen["where"] = where
        return real_query(collection_name, query_embeddings, n_results, where, include, **kw)

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.query_documents", capture)
    block = sk.recall_system_knowledge("릴레이 제어상태 로그 분석")
    assert "시스템 자기지식" in block
    assert "[db_schema]" in block and "relay_l_recording" in block
    assert "[logs]" not in block                # 거리 초과 항목 제외
    assert seen["where"] == {"data_type": {"$eq": "system_knowledge"}}   # 시스템지식만 회수


def test_recall_failsafe(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: None)
    assert sk.recall_system_knowledge("아무 질문") == ""       # 임베더 다운 → 빈 블록


def test_manage_tool_actions(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document",
                        lambda *a, **k: {"success": True})
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.delete_document",
                        lambda *a, **k: None)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)
    monkeypatch.setattr(sk, "list_system_knowledge", lambda: [{"knowledge_id": "sysk_x"}])

    assert sk.manage_system_knowledge("learn", text="유효한 시스템 사실 문장", category="logs")["success"]
    assert sk.manage_system_knowledge("list")["count"] == 1
    # 삭제: 시스템관리자(auth_farm_id=None) 허용
    assert sk.manage_system_knowledge("delete", knowledge_id="sysk_x")["success"]
    # 삭제: 일반 농장주(auth_farm_id 지정) 차단
    assert not sk.manage_system_knowledge("delete", knowledge_id="sysk_x", auth_farm_id="1")["success"]
    # 잘못된 id
    assert not sk.manage_system_knowledge("delete", knowledge_id="bad")["success"]
    # 미지원 action
    assert not sk.manage_system_knowledge("nope")["success"]


def test_seed_uses_real_columns(monkeypatch):
    calls = []
    monkeypatch.setattr(sk, "save_system_knowledge",
                        lambda text, **k: (calls.append((text, k)), {"success": True})[1])
    monkeypatch.setattr(sk, "_real_columns",
                        lambda tbl: ["farm_id", "hous_id", "recd_dttm"] if tbl == "relay_l_recording" else ["a"])

    r = sk.seed_system_knowledge()
    assert r["success"] and r["seeded"] >= 12
    # relay 테이블 시드에 실제 컬럼이 박혔는가(환각 차단)
    relay_doc = next(t for t, k in calls if "relay_l_recording" in t)
    assert "hous_id" in relay_doc and "recd_dttm" in relay_doc
    # 라우팅 맵 시드 존재
    assert any(k.get("category") == "tool_routing" for _, k in calls)


def test_registered_five_places():
    # (1) 코드 도구정의  (2) executor 디스패치  (3) 권한  (4) ANALYZER 화이트리스트
    from agri_ai_core.src.ai import tools_definition, tools_executor, tools_utils
    from agri_ai_core.src.ai.pipeline import question_analyzer

    defs = inspect.getsource(tools_definition)
    assert '"name": "manage_system_knowledge"' in defs
    assert 'manage_system_knowledge' in inspect.getsource(tools_executor.execute_tool)
    assert "manage_system_knowledge" in tools_utils.TOOL_AUTH_INJECT if hasattr(tools_utils, "TOOL_AUTH_INJECT") \
        else "manage_system_knowledge" in inspect.getsource(tools_utils)
    assert "manage_system_knowledge" in inspect.getsource(question_analyzer)

    # (5) DB tool_definition_m (USE_DB_TOOLS 1순위 소스)
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        row = d.fetch_one(
            "SELECT active_yn FROM tool_definition_m WHERE tool_id='manage_system_knowledge'", ())
    assert row and dict(row)["active_yn"] == "Y"


def test_analyzer_injects_sysknow(monkeypatch):
    # ANALYZER 가 recall_system_knowledge 블록을 시스템 메시지로 주입하는지(소스 대조)
    from agri_ai_core.src.ai.pipeline import question_analyzer
    src = inspect.getsource(question_analyzer)
    assert "recall_system_knowledge" in src
    assert "시스템지식" in src            # 주입 로그 문구


# ── 자율 감사(GAP4) ──
def test_parse_learned_cols():
    t = "[DB테이블 relay_l_recording] 실제 컬럼(자가학습): farm_id, hous_id, recd_dttm. 이 테이블…"
    assert sk._parse_learned_cols(t) == ["farm_id", "hous_id", "recd_dttm"]
    assert sk._parse_learned_cols("마커 없는 문장") is None


def test_audit_refreshes_and_removes(monkeypatch):
    # 저장 지식: relay(cols_ 존재, 드리프트) + gone(테이블 소멸)
    items = [
        {"knowledge_id": "sysk_cols_relay_l_recording",
         "text": "[DB테이블 relay_l_recording] 실제 컬럼(자가학습): farm_id, hous_id. 끝.",
         "category": "db_schema", "source": "auto_selfheal"},
        {"knowledge_id": "sysk_cols_gone_table",
         "text": "[DB테이블 gone_table] 실제 컬럼(자가학습): x. 끝.", "category": "db_schema", "source": "audit"},
    ]
    monkeypatch.setattr(sk, "list_system_knowledge", lambda: items)
    # relay 는 컬럼 드리프트(recd_dttm 추가), gone_table 은 소멸
    monkeypatch.setattr(sk, "_real_columns",
                        lambda t: ["farm_id", "hous_id", "recd_dttm"] if t == "relay_l_recording" else [])
    saved, deleted = [], []
    monkeypatch.setattr(sk, "save_system_knowledge",
                        lambda text, **k: (saved.append(k.get("key")), {"success": True})[1])
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.delete_document",
                        lambda c, ids=None: deleted.append(ids))

    rep = sk.audit_system_knowledge()
    assert rep["refreshed"] == 1 and rep["removed"] == 1
    assert "cols_relay_l_recording" in saved                 # 드리프트 → 재생성
    assert ["sysk_cols_gone_table"] in deleted               # 소멸 → 삭제


def test_audit_skips_when_matched(monkeypatch):
    items = [{"knowledge_id": "sysk_cols_t",
              "text": "[DB테이블 t] 실제 컬럼(자가학습): a, b. 끝.", "category": "db_schema", "source": "audit"}]
    monkeypatch.setattr(sk, "list_system_knowledge", lambda: items)
    monkeypatch.setattr(sk, "_real_columns", lambda t: ["a", "b"])
    saved = []
    monkeypatch.setattr(sk, "save_system_knowledge", lambda text, **k: saved.append(1))
    rep = sk.audit_system_knowledge()
    assert rep["ok"] == 1 and rep["refreshed"] == 0 and saved == []   # 일치 → 재임베딩 생략


def test_ensure_seeds_when_empty(monkeypatch):
    monkeypatch.setattr(sk, "list_system_knowledge", lambda: [])
    monkeypatch.setattr(sk, "seed_system_knowledge", lambda: {"success": True, "seeded": 13})
    monkeypatch.setattr(sk, "audit_system_knowledge", lambda: {"success": True, "audited": True})
    assert sk.ensure_system_knowledge().get("seeded") == 13        # 비었으면 시드


def test_ensure_audits_when_present(monkeypatch):
    monkeypatch.setattr(sk, "list_system_knowledge", lambda: [{"knowledge_id": "sysk_x"}])
    monkeypatch.setattr(sk, "seed_system_knowledge", lambda: {"seeded": 99})
    monkeypatch.setattr(sk, "audit_system_knowledge", lambda: {"audited": True})
    assert sk.ensure_system_knowledge().get("audited") is True     # 있으면 감사
