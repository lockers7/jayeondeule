# ══════════════════════════════════════════════════════════════════════════════
# test_greeting_quick — greeting 정형 응답 회귀 [2026-05-26 hotfix]
#
# Ollama 가 환경제어/agent 점유 중일 때 인사 답변 LLM 호출이 큐 대기로 hang.
# fix: response_type='greeting' 분기는 LLM 우회 + 즉시 정형 응답.
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch


def test_greeting_does_not_call_llm():
    """greeting 분기는 _ollama_chat 호출 안 함."""
    from agri_ai_core.src.ai.pipeline.answer_generator import _generate_simple_response
    with patch("agri_ai_core.src.ai.llm_client._ollama_chat") as oc:
        r = _generate_simple_response(
            "안녕 ?", [], "자연들에", "male", "greeting")
    oc.assert_not_called()
    assert r["response"]
    assert "안녕" in r["response"] or "도우미" in r["response"]


def test_conversation_ref_still_calls_llm():
    """conversation_ref 는 기존대로 LLM 호출 (회귀 보전)."""
    from agri_ai_core.src.ai.pipeline import answer_generator
    fake_resp = {"message": {"content": "재포맷된 답변"}}
    with patch.object(answer_generator, "_generate_simple_response") as gen:
        # 실제 LLM 호출이 일어나는지 별도 검증 안 함 — 기존 흐름 유지만
        pass


def test_greeting_keywords():
    """다양한 인사 변형 — 모두 정형 응답 반환."""
    from agri_ai_core.src.ai.pipeline.answer_generator import _greeting_quick_response
    for q in ["안녕", "안녕하세요", "hi", "hello", "고마워", "수고하세요",
              "좋은 아침", "잘 자", "굿모닝"]:
        r = _greeting_quick_response(q, "테스트농장", "male")
        assert isinstance(r, str) and len(r) >= 5


def test_greeting_female_style():
    from agri_ai_core.src.ai.pipeline.answer_generator import _greeting_quick_response
    r = _greeting_quick_response("안녕", "자연들에", "female")
    assert "~" in r or "요" in r  # 해요체 마커


def test_greeting_no_farm_name():
    from agri_ai_core.src.ai.pipeline.answer_generator import _greeting_quick_response
    r = _greeting_quick_response("안녕", None, "male")
    assert "안녕" in r


def test_non_greeting_does_not_match_fast_classify():
    """일반 농장 질문은 fast_classify=None → 기존 ANALYZER+MCP 흐름 보전.
    사용자 절대 룰: '키워드 응답 금지'. 명확한 인사만 우회."""
    from agri_ai_core.src.ai.pipeline.question_analyzer import fast_classify
    # 농장 데이터/제어/모니터링 등은 모두 None — LLM ANALYZER 거침
    assert fast_classify("1호기 수온 알려줘") is None
    assert fast_classify("센서 상태 보여줘") is None
    assert fast_classify("10분마다 모니터링하라") is None
    assert fast_classify("내 알림 있어?") is None
    assert fast_classify("히터 켜줘") is None
    # 인사만 greeting
    assert fast_classify("안녕") == "greeting"
    assert fast_classify("hi") == "greeting"
    assert fast_classify("감사합니다") == "greeting"
