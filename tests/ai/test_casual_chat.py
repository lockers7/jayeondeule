# ══════════════════════════════════════════════════════════════════════════════
# test_casual_chat — 잡담·친교 모드 검증
#
# 핵심 안전성: 업무 발화가 잡담 고속경로로 새는 오분류가 절대 없어야 한다.
#
# 파일 시작 함수 목록:
#   test_fast_casual_positive      : 확실-잡담 발화 → casual_chat 즉시 분류
#   test_fast_casual_blocks_farm   : 농장/장치/숫자 포함 → 고속경로 금지 (LLM행)
#   test_fast_greeting_unchanged   : 기존 인사 고속분류 회귀 없음
#   test_valid_types_include_casual: 유형 화이트리스트 등록
#   test_runner_skips_stage2       : casual_chat 은 2단계(도구) 스킵 대상
#   test_persona_prompt            : 페르소나 로드(치환·chunk 폴백) + 업무마무리 금지문
#   test_profile_remember_recall   : 관심사 저장→회상 왕복 (실 VectorDB)
#   test_profile_failsafe          : 저장/회상 예외가 흐름을 깨지 않음
# ══════════════════════════════════════════════════════════════════════════════
import time

from agri_ai_core.src.ai.pipeline.question_analyzer import fast_classify, _VALID_TYPES


def test_fast_casual_positive():
    cases = [
        "심심한데 재밌는 얘기 하나 해줘~",
        "지금 버스 타고 가는 중이야 ㅎㅎ",
        "오늘 기분이 참 좋네. 잘 지냈어?",
        "밥 먹었어? 난 이제 퇴근길이야",
    ]
    for q in cases:
        assert fast_classify(q) == "casual_chat", q


def test_fast_casual_blocks_farm():
    # 업무 요소가 섞이면 절대 고속경로 금지 → None (LLM 분석행)
    cases = [
        "안녕, 가는 길인데 2호 온도 괜찮아?",     # 장치/숫자
        "심심한데 재배사 상태나 알려줘",           # 농장어 + 알려
        "버스 타고 농장으로 가고 있어",            # '농장' 포함 — 보수 처리
        "재밌는 얘기 해줘. 그리고 히터 꺼줘",      # 제어 혼합
        "ㅎㅎ 오늘 수확량 얼마나 돼?",             # 수확
        "기분 좋다~ 카카오 알림 잘 오지?",         # 시스템어
    ]
    for q in cases:
        assert fast_classify(q) is None, q


def test_fast_greeting_unchanged():
    assert fast_classify("안녕하세요") == "greeting"
    assert fast_classify("고마워요~") == "greeting"
    assert fast_classify("안녕하세요. 1호 온도 알려줘") is None


def test_valid_types_include_casual():
    assert "casual_chat" in _VALID_TYPES


def test_runner_skips_stage2():
    import inspect
    from agri_ai_core.src.ai.pipeline import runner
    src = inspect.getsource(runner.run_3stage_pipeline_sync)
    assert '"casual_chat"' in src.split("_skip_types = ")[1].split(")")[0]


def test_persona_prompt(monkeypatch):
    from agri_ai_core.src.ai.pipeline.answer_generator import _get_casual_persona, CASUAL_PERSONA_RAW
    monkeypatch.setenv("USE_DB_PROMPTS", "0")   # 코드 기본값 경로
    p = _get_casual_persona("자연들에", "존댓말 톤")
    assert "자연들에" in p and "존댓말 톤" in p
    assert "필요한 정보가 있으시면 말씀해주세요" in CASUAL_PERSONA_RAW  # 금지문 명시 확인
    assert "되물음" in p
    # chunk 우선 경로
    monkeypatch.setenv("USE_DB_PROMPTS", "1")
    p2 = _get_casual_persona("자연들에", "톤")
    assert "말벗" in p2


def test_profile_remember_recall(monkeypatch):
    # 결정론적 왕복: 우리 코드(저장 페이로드 구성·회상 파싱/거리필터)를 검증.
    # 실 ChromaDB 인덱싱 타이밍은 우리 코드가 아니며 스위트 문맥에서 플레이키
    # (저장 직후 검색 미가시).
    from agri_ai_core.src.ai import chat_profile
    saved = {}

    def fake_add(collection_name, doc_id, text, metadata, embedding=None):
        saved.update(doc_id=doc_id, text=text, meta=metadata, emb=embedding)
        return {"success": True}

    def fake_query(collection_name, query_embeddings=None, n_results=5, where=None, include=None, **kw):
        # 평탄화 반환 형태 (실 query_documents 와 동일)
        return {"documents": [saved["text"], "무관한 옛 기록"],
                "metadatas": [saved["meta"], {"created_at": "2026-01-01"}],
                "distances": [0.31, 0.92]}   # 두 번째는 거리필터(0.75)로 걸러져야 함

    monkeypatch.setattr("agri_ai_core.src.chroma.operations.add_document", fake_add)
    monkeypatch.setattr("agri_ai_core.src.chroma.operations.query_documents", fake_query)
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text", lambda t: [0.1] * 1024)

    chat_profile._remember("낚시 얘기 — 주말에 저수지 가고 싶다", farm_id="1")
    assert saved["meta"]["data_type"] == "farmer_interest"
    assert saved["meta"]["farm_id"] == "1" and saved["emb"] is not None
    assert saved["doc_id"].startswith("interest_")

    block = chat_profile.recall("주말에 낚시나 갈까 하는데")
    assert "낚시" in block and "관심사" in block
    assert "무관한 옛 기록" not in block   # 거리 0.92 > 0.75 필터 동작


def test_profile_failsafe(monkeypatch):
    from agri_ai_core.src.ai import chat_profile
    monkeypatch.setattr("agri_ai_core.src.ai.embedder.embed_text",
                        lambda t: (_ for _ in ()).throw(RuntimeError("임베더 다운")))
    chat_profile._remember("아무 발화")          # 예외 없어야 함
    assert chat_profile.recall("아무 발화") == ""  # 빈 블록 (흐름 보존)


def test_busy_wait_message_dynamic():
    # 대기 문구 — 농장명 동적 치환
    from agri_ai_core.src.ai.chat_llm_gate import busy_wait_message
    assert "자연들에 농장 관리 AI가 작업 중" in busy_wait_message("자연들에")
    assert "고흥뜰에 농장 관리 AI가 작업 중" in busy_wait_message("고흥뜰에")
    m = busy_wait_message(None)
    assert "농장 관리 AI가 작업 중" in m and "제어 LLM" not in m


# ⛔ 회귀 방지 (2026-07-17): 단독 확인응답이 greeting 으로 낚이면
#   "확인해 드릴까요?" → "네" 가 정형 인사말로 답해지고 LLM·MCP·직전 맥락을
#   전부 우회한다. 절대 룰 "LLM 대화 키워드 응답 금지" 위반.
def test_confirmation_not_greeting():
    from agri_ai_core.src.ai.pipeline.question_analyzer import fast_classify
    for q in ("네", "예", "응", "어", "ok", "오케이", "아니요", "아뇨",
              "네 1", "예 2"):
        assert fast_classify(q) is None, f"{q!r} 가 규칙분류로 우회됨 — LLM 분석 필요"


def test_pure_greeting_still_fast():
    from agri_ai_core.src.ai.pipeline.question_analyzer import fast_classify
    for q in ("안녕하세요", "반가워요", "감사합니다", "좋은 아침", "hi", "bye"):
        assert fast_classify(q) == "greeting", f"{q!r} 인사 고속경로가 깨짐"
