# ══════════════════════════════════════════════════════════════════════════
# 재포맷 감지 — _is_conversational_query 회귀 테스트.
# "표로 작성해줘" 같은 재포맷 요청이 이전 대화 맥락 유지를 위해 conversational
# 로 판정되는지 검증.
# ══════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.ai.llm_response_processing import _is_conversational_query as f


@pytest.mark.parametrize("q", [
    "표로 작성해줘",
    "보기가 어렵다.. 표로 작성해줘",
    "정리해줘",
    "요약해줘",
    "자세히 설명해줘",
    "간단히 말해줘",
    "안녕",
    "",
    "아까 뭐라고 했어",
    "방금 말한 온도 다시 알려줘",
])
def test_conversational_patterns(q):
    assert f(q) is True, f"{q!r} 은 conversational 이어야 함"


@pytest.mark.parametrize("q", [
    "지금 상태 다시 조회해서 표로 보여줘",   # 새 수집 의도 포함 → False
    "최신 데이터로 표 그려줘",
    "1호재배사 온도 알려줘",
    "조명 꺼줘",
    "배출팬 켜줘",
])
def test_directive_patterns(q):
    assert f(q) is False, f"{q!r} 은 directive 이어야 함"
