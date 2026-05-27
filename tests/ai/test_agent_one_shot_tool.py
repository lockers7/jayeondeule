# ══════════════════════════════════════════════════════════════════════════════
# test_agent_one_shot_tool — 채팅 → agent 1회 분석 도구 검증
#
# 대상: tools_executor.execute_tool("agent_one_shot", ...)
#       + tools_definition.TOOLS_DEFINITION 의 schema
#       + question_analyzer._VALID_TOOLS 등록
#
# 정책:
#   · ai_monitor_agent.run_agent 는 mock 으로 격리 (실 LLM 호출 없음)
#   · 결과 dict 의 핵심 필드 (success/final/duration_sec/log_id) 압축 검증
#
# 파일 시작 함수 목록:
#   TestToolRegistered    : _VALID_TOOLS + TOOLS_DEFINITION schema
#   TestExecuteSuccess    : run_agent success=True 케이스
#   TestExecuteFailure    : MAX_STEPS / loop 등 success=False 케이스
#   TestArgsCoercion      : task 누락 / farm_id 비정수 안전 처리
# ══════════════════════════════════════════════════════════════════════════════
import json
from unittest.mock import patch

import pytest


# ────────────────────────────────────────────────────────────────────
# 1) Registry / Schema 검증
# ────────────────────────────────────────────────────────────────────
class TestToolRegistered:
    def test_in_valid_tools(self):
        from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
        assert "agent_one_shot" in _VALID_TOOLS

    def test_in_tools_definition(self):
        from agri_ai_core.src.ai.tools_definition import get_available_tools
        tools = get_available_tools()
        names = [t["function"]["name"] for t in tools]
        assert "agent_one_shot" in names

    def test_schema_required_task(self):
        from agri_ai_core.src.ai.tools_definition import get_available_tools
        tools = get_available_tools()
        spec = next(t for t in tools
                    if t["function"]["name"] == "agent_one_shot")
        params = spec["function"]["parameters"]
        assert "task" in params["properties"]
        assert "task" in params.get("required", [])
        # farm_id 는 선택 (기본 1)
        assert "farm_id" in params["properties"]


# ────────────────────────────────────────────────────────────────────
# 2) 정상 실행 (run_agent mock)
# ────────────────────────────────────────────────────────────────────
class TestExecuteSuccess:
    def test_returns_compact_final(self):
        from agri_ai_core.src.ai.tools_executor import execute_tool

        fake_result = {
            "success": True,
            "final": "1호기 수온 정상 (24.5℃)",
            "duration_sec": 92.5,
            "steps": [
                {"tool": "get_sensor_window", "args": {}},
                {"tool": "get_thresholds", "args": {}},
                {"final": "..."},
            ],
            "log_id": 42,
        }
        with patch("agri_ai_core.src.control.ai_monitor_agent.run_agent",
                   return_value=fake_result) as mra:
            out = execute_tool("agent_one_shot",
                               {"task": "1호기 진단", "farm_id": 1})

        # 결과는 JSON 문자열
        data = json.loads(out)
        assert data["success"] is True
        assert data["final"] == "1호기 수온 정상 (24.5℃)"
        assert data["duration_sec"] == 92.5
        assert data["steps"] == 3
        assert data["log_id"] == 42
        # tool_calls 카운팅
        assert data["tool_calls"] == {"get_sensor_window": 1, "get_thresholds": 1}
        # run_agent 호출 인자 검증
        kw = mra.call_args.kwargs
        assert kw["task"] == "1호기 진단"
        assert kw["farm_id"] == 1
        assert kw["trigger_type"] == "user"


# ────────────────────────────────────────────────────────────────────
# 3) 실패 케이스 (MAX_STEPS / loop)
# ────────────────────────────────────────────────────────────────────
class TestExecuteFailure:
    def test_max_steps_exceeded(self):
        from agri_ai_core.src.ai.tools_executor import execute_tool

        fake_result = {
            "success": False,
            "reason": "MAX_STEPS exceeded",
            "duration_sec": 200.3,
            "steps": [{"tool": "get_sensor_window"}] * 8,
            "final": None,
            "log_id": 43,
        }
        with patch("agri_ai_core.src.control.ai_monitor_agent.run_agent",
                   return_value=fake_result):
            out = execute_tool("agent_one_shot", {"task": "X", "farm_id": 1})
        data = json.loads(out)
        assert data["success"] is False
        assert data["reason"] == "MAX_STEPS exceeded"
        assert data["final"] is None
        assert data["steps"] == 8


# ────────────────────────────────────────────────────────────────────
# 4) 인자 안전 처리
# ────────────────────────────────────────────────────────────────────
class TestArgsCoercion:
    def test_farm_id_string_coerced(self):
        from agri_ai_core.src.ai.tools_executor import execute_tool

        fake = {"success": True, "final": "ok", "duration_sec": 1, "steps": []}
        with patch("agri_ai_core.src.control.ai_monitor_agent.run_agent",
                   return_value=fake) as mra:
            execute_tool("agent_one_shot", {"task": "X", "farm_id": "2"})
        assert mra.call_args.kwargs["farm_id"] == 2

    def test_farm_id_invalid_defaults_to_1(self):
        from agri_ai_core.src.ai.tools_executor import execute_tool

        fake = {"success": True, "final": "ok", "duration_sec": 1, "steps": []}
        with patch("agri_ai_core.src.control.ai_monitor_agent.run_agent",
                   return_value=fake) as mra:
            execute_tool("agent_one_shot", {"task": "X", "farm_id": "bogus"})
        assert mra.call_args.kwargs["farm_id"] == 1

    def test_task_missing_defaults(self):
        from agri_ai_core.src.ai.tools_executor import execute_tool

        fake = {"success": True, "final": "ok", "duration_sec": 1, "steps": []}
        with patch("agri_ai_core.src.control.ai_monitor_agent.run_agent",
                   return_value=fake) as mra:
            execute_tool("agent_one_shot", {})
        # task 빈값 → 기본 task "농장 모니터링" 사용
        assert mra.call_args.kwargs["task"] == "농장 모니터링"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
