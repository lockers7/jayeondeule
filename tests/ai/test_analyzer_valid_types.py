# ══════════════════════════════════════════════════════════════════════════
# Analyzer 유효 유형 회귀 테스트.
# agent_monitor 유형이 _VALID_TYPES 에 누락되면
# LLM 이 반환해도 fallback 으로 떨어져 list_monitors 자연어 라우팅이 깨진다.
# ══════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TYPES


EXPECTED_CORE = {
    "farm_sensor", "farm_control", "farm_knowledge", "farm_knowledge_delete",
    "weather", "web_search",
    "agent_monitor",                          # list/cancel/schedule_monitor 자연어 라우팅용
    "greeting", "conversation_ref", "general", "complex",
}


def test_core_types_registered():
    missing = EXPECTED_CORE - _VALID_TYPES
    assert not missing, f"누락된 유형: {missing}"


def test_agent_monitor_registered():
    # list/cancel/schedule_monitor 자연어 라우팅을 위한 전용 유형
    assert "agent_monitor" in _VALID_TYPES
