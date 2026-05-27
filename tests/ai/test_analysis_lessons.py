# ══════════════════════════════════════════════════════════════════════════════
# test_analysis_lessons — 분석 자가학습 루프 검증
#
# 농장주 지시: "일반 기능을 로컬 AI가 알아서, 데이터를 스스로 학습·저장·이용" —
# 사례별 코드 정정 대신 교훈(analysis_lesson) 데이터로 성장하는 범용 메커니즘.
# 핵심 안전성: 가르침 오탐으로 관리자지시/제어룰 학습 흐름을 침범하지 않아야 함.
#
# 파일 시작 함수 목록:
#   test_save_lesson_payload        : 저장 페이로드(임베딩·메타·절단) 검증
#   test_recall_format_and_filter   : 회상 블록 형식 + 거리필터 검증
#   test_recall_failsafe            : 임베더 다운 시 빈 블록 (흐름 보존)
#   test_manage_tool_actions        : register/list/delete/오액션 + 권한
#   test_detect_teaching            : 가르침 판정 — 양성/음성(지시·제어룰 비침범)
#   test_detect_correction          : 정정 판정 — 양성/음성
#   test_analyzer_injects_lessons   : ANALYZER 가 교훈 블록을 시스템 메시지로 주입
#   test_analyzer_learns_correction : 정정 발화 → 직전 질문과 교훈 자동 저장
#   test_runner_safety_net_source   : runner 세이프티넷이 2단계 스킵보다 선행
# ══════════════════════════════════════════════════════════════════════════════
import inspect

from agri_ai_core.src.ai import chat_lessons


def test_save_lesson_payload(monkeypatch):
    saved = {}

    def fake_add(collection_name, doc_id, text, metadata, embedding=None):
        saved.update(doc_id=doc_id, text=text, meta=metadata, emb=embedding)
        return {"success": True}

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document", fake_add)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)

    r = chat_lessons.save_lesson("앞으로 왜냐고 물으면 결정 기록을 근거로 답해라" + "x" * 500,
                                 source="teach", farm_id="1")
    assert r["success"] and r["lesson_id"].startswith("lesson_")
    assert saved["meta"]["data_type"] == "analysis_lesson"
    assert saved["meta"]["source"] == "teach" and saved["meta"]["farm_id"] == "1"
    assert saved["emb"] is not None            # 0벡터 저장(검색 불가) 방지
    assert len(saved["text"]) == 400           # _MAX_LEN 절단

    r2 = chat_lessons.save_lesson("짧음")      # _MIN_LEN 미만
    assert not r2["success"]


def test_recall_format_and_filter(monkeypatch):
    def fake_query(collection_name, query_embeddings=None, n_results=5, where=None,
                   include=None, **kw):
        # 평탄화 반환 형태 (실 query_documents 와 동일)
        return {"documents": ["왜냐고 물으면 결정 기록을 근거로 답하라", "무관한 교훈"],
                "metadatas": [{"created_at": "2026-07-10 22:00"}, {"created_at": "2026-01-01"}],
                "distances": [0.42, 0.95]}     # 두 번째는 거리필터(0.9)로 제외

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.query_documents", fake_query)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)

    block = chat_lessons.recall_lessons("왜 재배사마다 릴레이가 다르지?")
    assert "축적된 분석 교훈" in block and "결정 기록" in block
    assert "무관한 교훈" not in block
    assert "반드시 계획" in block              # ANALYZER 반영 지시문 포함


def test_recall_failsafe(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text",
                        lambda t: (_ for _ in ()).throw(RuntimeError("임베더 다운")))
    assert chat_lessons.recall_lessons("아무 질문") == ""


def test_manage_tool_actions(monkeypatch):
    calls = {}
    monkeypatch.setattr(chat_lessons, "save_lesson",
                        lambda text, source="teach", farm_id=None:
                        calls.update(text=text, farm=farm_id) or {"success": True, "lesson_id": "lesson_x"})

    def fake_get(collection_name, where=None, include=None, limit=None, **kw):
        return {"ids": ["lesson_b", "lesson_a"],
                "documents": ["교훈B", "교훈A"],
                "metadatas": [{"created_at": "2026-07-09", "source": "teach"},
                              {"created_at": "2026-07-10", "source": "correction"}]}

    deleted = {}
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.get_documents", fake_get)
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.delete_document",
                        lambda c, ids: deleted.update(ids=ids) or {"success": True})

    r = chat_lessons.manage_analysis_lesson("register", lesson_text="앞으로 이유 질문엔 결정로그 조회",
                                            auth_farm_id="1")
    assert r["success"] and "자동으로 반영" in r["message"] and calls["farm"] == "1"

    r = chat_lessons.manage_analysis_lesson("list")
    assert r["success"] and r["count"] == 2
    assert r["lessons"][0]["lesson_id"] == "lesson_a"      # created_at 내림차순

    # delete: 농장사용자 거부 / 관리자 허용 / lesson_ 접두어 강제 (타 문서 보호)
    r = chat_lessons.manage_analysis_lesson("delete", lesson_id="lesson_a", auth_farm_id="1")
    assert not r["success"]
    r = chat_lessons.manage_analysis_lesson("delete", lesson_id="interest_x", auth_farm_id=None)
    assert not r["success"]
    r = chat_lessons.manage_analysis_lesson("delete", lesson_id="lesson_a", auth_farm_id=None)
    assert r["success"] and deleted["ids"] == ["lesson_a"]

    assert not chat_lessons.manage_analysis_lesson("purge")["success"]


def test_detect_teaching():
    positives = [
        "앞으로 내가 왜냐고 묻는 질문에는 반드시 결정 기록을 근거로 답해라",
        "다음부터 재배사 상태를 물으면 CO2 농도도 함께 알려주는 식으로 대답해줘",
        "매번 센서 요청에는 임계값과 비교해서 답변하라",
    ]
    for q in positives:
        assert chat_lessons.detect_teaching(q), q

    negatives = [
        "별도 지시가 있을 때까지 모든 재배사 수온히터 꺼둬",       # 관리자지시 영역
        "다음부터 수온이 20도 넘으면 히터를 꺼라",                  # 제어룰(save_domain_knowledge) 영역
        "2호 재배사 온도 알려줘",                                   # 일반 조회
        "왜 재배사마다 릴레이가 다르지?",                           # 이유 질문 자체
        "항상 고마워",                                              # 잡담
    ]
    for q in negatives:
        assert not chat_lessons.detect_teaching(q), q


def test_detect_correction():
    assert chat_lessons.detect_correction("그게 아니라 내 질문은 릴레이가 왜 다른지였다")
    assert chat_lessons.detect_correction("엉뚱한 대답을 했다. 다시 답해라")
    assert not chat_lessons.detect_correction("1호 온도 알려줘")
    assert not chat_lessons.detect_correction("고마워요~")


def _mock_analyzer_llm(monkeypatch, captured):
    import agri_ai_core.src.ai.llm_client as llm_client

    def fake_chat(model, messages, tools=None, options=None, keep_alive=None, timeout_sec=None):
        captured["messages"] = messages
        return {"message": {"content": ""}}

    monkeypatch.setattr(llm_client, "_ollama_chat", fake_chat)
    monkeypatch.setattr(llm_client, "_extract_message_content", lambda r: (
        '{"question_type":"farm_sensor","intent":"x","required_data":'
        '[{"tool":"get_farm_realtime_data","args":{},"priority":1}],'
        '"data_freshness":"realtime","answer_format":"text","multi_house":false,"house_ids":[]}'))


def test_analyzer_injects_lessons(monkeypatch):
    from agri_ai_core.src.ai.pipeline.question_analyzer import analyze_question
    captured = {}
    _mock_analyzer_llm(monkeypatch, captured)
    monkeypatch.setattr(chat_lessons, "recall_lessons",
                        lambda q, top_k=3: "[축적된 분석 교훈 — 테스트]\n- 교훈1")

    result = analyze_question("왜 재배사마다 릴레이가 다르지?", farm_id="1", house_id="1")
    assert result["question_type"] == "farm_sensor"
    sys_texts = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert any("축적된 분석 교훈" in t for t in sys_texts)


def test_analyzer_learns_correction(monkeypatch):
    from agri_ai_core.src.ai.pipeline.question_analyzer import analyze_question
    captured, learned = {}, {}
    _mock_analyzer_llm(monkeypatch, captured)
    monkeypatch.setattr(chat_lessons, "recall_lessons", lambda q, top_k=3: "")
    monkeypatch.setattr(chat_lessons, "learn_correction_async",
                        lambda prev, corr, farm_id=None: learned.update(prev=prev, corr=corr))

    ctx = [{"role": "user", "content": "재배사 릴레이가 왜 다르게 설정됐어?"},
           {"role": "assistant", "content": "상태를 알려드렸어요"}]
    analyze_question("그게 아니라 내 질문은 그렇게 설정한 이유였다",
                     conversation_context=ctx, farm_id="1", house_id="1")
    assert learned["prev"] == "재배사 릴레이가 왜 다르게 설정됐어?"
    assert "이유였다" in learned["corr"]


def test_runner_safety_net_source():
    # 세이프티넷이 2단계 스킵 판정보다 앞이고, _force_collect 가 스킵을 무효화하는지
    from agri_ai_core.src.ai.pipeline import runner
    src = inspect.getsource(runner.run_3stage_pipeline_sync)
    assert "detect_teaching" in src and "manage_analysis_lesson" in src
    assert src.index("detect_teaching") < src.index("_skip_types = ")
    assert "and not _force_collect" in src
