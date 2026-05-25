# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 단위테스트 — ai_monitor_agent ReAct loop.
# LLM 호출은 mock 으로 대체 (실제 Ollama 호출 안 함).
#
# 검증:
#   1) JSON parse — 정상/실패/코드블록 wrapping
#   2) tool 실행 — 정상/미존재/args mismatch/예외
#   3) loop 감지 — 같은 (tool, args) 3회 연속
#   4) final 도달 — 정상 종료
#   5) MAX_STEPS — 무한 loop 방지
#   6) build_system_prompt — TOOLS 주입 + 길이
# ═══════════════════════════════════════════════════════════════════════════
import json
from unittest.mock import patch, MagicMock

import pytest

from agri_ai_core.src.control import ai_monitor_agent as agent_mod
from agri_ai_core.src.control.ai_monitor_agent import (
    _parse_response, _execute_tool, _detect_loop,
    build_system_prompt, run_agent, _persist_agent_log,
)


# ════════════════════════════════════════════════════════════════════
# 1) JSON parse
# ════════════════════════════════════════════════════════════════════
class TestParseResponse:
    def test_plain_json(self):
        r = _parse_response('{"thought":"x", "tool":"y", "args":{}}')
        assert r == {"thought": "x", "tool": "y", "args": {}}

    def test_with_code_fence(self):
        r = _parse_response('```json\n{"thought":"x", "final":"done"}\n```')
        assert r == {"thought": "x", "final": "done"}

    def test_with_whitespace(self):
        r = _parse_response('   \n  {"a":1}  \n')
        assert r == {"a": 1}

    def test_invalid_json(self):
        assert _parse_response("not json") is None
        assert _parse_response("") is None
        assert _parse_response(None) is None

    def test_partial_json(self):
        assert _parse_response('{"thought":"x"') is None


# ════════════════════════════════════════════════════════════════════
# 2) Tool 실행
# ════════════════════════════════════════════════════════════════════
class TestExecuteTool:
    def test_unknown_tool(self):
        r = _execute_tool("nonexistent_tool", {})
        assert "error" in r
        assert "unknown tool" in r["error"]

    def test_args_not_dict(self):
        r = _execute_tool("get_sensor_window", "not a dict")
        assert "error" in r
        assert "dict" in r["error"].lower()

    def test_args_mismatch(self):
        # get_sensor_window 는 (farm, house, minutes) — 'foo' 라는 키는 없음
        r = _execute_tool("get_sensor_window", {"foo": "bar"})
        assert "error" in r

    def test_valid_call(self):
        # 실 DB 호출 — 999호는 데이터 없음 — success=True + n=0
        r = _execute_tool("get_sensor_window",
                          {"farm": 1, "house": 999, "minutes": 5})
        assert r.get("success") is True
        assert r["n"] == 0


# ════════════════════════════════════════════════════════════════════
# 3) Loop 감지
# ════════════════════════════════════════════════════════════════════
class TestDetectLoop:
    def test_empty_history(self):
        assert _detect_loop([]) is False

    def test_short_history(self):
        h = [{"step": 0, "tool": "X", "args": {}}]
        assert _detect_loop(h) is False

    def test_no_loop(self):
        h = [
            {"step": 0, "tool": "A", "args": {"x": 1}},
            {"step": 1, "tool": "B", "args": {"x": 1}},
            {"step": 2, "tool": "A", "args": {"x": 2}},
        ]
        assert _detect_loop(h) is False

    def test_loop_detected(self):
        h = [
            {"step": 0, "tool": "A", "args": {"x": 1}},
            {"step": 1, "tool": "A", "args": {"x": 1}},
            {"step": 2, "tool": "A", "args": {"x": 1}},
        ]
        assert _detect_loop(h) is True

    def test_loop_with_irrelevant_entries(self):
        """JSON parse 실패 같은 entries 도 history 안에 있을 수 있음."""
        h = [
            {"step": 0, "error": "json_parse_fail"},
            {"step": 1, "tool": "A", "args": {"x": 1}},
            {"step": 2, "tool": "A", "args": {"x": 1}},
            {"step": 3, "tool": "A", "args": {"x": 1}},
        ]
        # 마지막 3개 tool 항목이 동일 → loop
        assert _detect_loop(h) is True


# ════════════════════════════════════════════════════════════════════
# 4) System prompt
# ════════════════════════════════════════════════════════════════════
class TestSystemPrompt:
    def test_default_inline(self):
        # DB block 없을 때 inline fallback
        p = build_system_prompt(max_steps=5)
        assert isinstance(p, str)
        assert len(p) > 500
        assert "스마트팜 모니터링" in p
        assert "최대 5단계" in p

    def test_tools_injected(self):
        p = build_system_prompt(max_steps=8)
        # 5개 도구 이름이 모두 포함되어야
        for tool in ("get_sensor_window", "get_recent_decisions",
                     "get_relay_state", "compare_houses", "get_thresholds"):
            assert tool in p, f"{tool} 누락"


# ════════════════════════════════════════════════════════════════════
# 5) run_agent — LLM mock (persist_db=False 로 DB INSERT 회피)
# ════════════════════════════════════════════════════════════════════
class TestRunAgent:
    @patch.object(agent_mod, "_call_llm")
    def test_immediate_final(self, mock_llm):
        """첫 step 에 final → 정상 종료."""
        mock_llm.return_value = '{"thought":"빠른 결론", "final":"테스트 OK"}'
        r = run_agent(task="간단 테스트", farm_id=1, max_steps=3, persist_db=False)
        assert r["success"] is True
        assert r["final"] == "테스트 OK"
        assert len(r["steps"]) == 1

    @patch.object(agent_mod, "_call_llm")
    def test_tool_then_final(self, mock_llm):
        """step1: tool 호출 → step2: final."""
        mock_llm.side_effect = [
            '{"thought":"센서 확인", "tool":"get_sensor_window", "args":{"farm":1, "house":999, "minutes":5}}',
            '{"thought":"데이터 없음 확인", "final":"999호는 데이터 없음. 모니터 대상 아님."}',
        ]
        r = run_agent(task="999 호기 분석", farm_id=1, max_steps=5, persist_db=False)
        assert r["success"] is True
        assert "999호" in r["final"]
        assert len(r["steps"]) == 2
        # 첫 step 에 tool_result 가 기록됨
        assert "tool_result" in r["steps"][0]
        assert r["steps"][0]["tool_result"]["n"] == 0

    @patch.object(agent_mod, "_call_llm")
    def test_max_steps_exceeded(self, mock_llm):
        """LLM 이 계속 *서로 다른* tool 만 호출 → MAX_STEPS 초과."""
        # 5번의 서로 다른 tool 호출 (loop 감지 안 되도록)
        mock_llm.side_effect = [
            '{"thought":"step '+str(i)+'", "tool":"get_sensor_window", "args":{"farm":1, "house":'+str(i+1)+', "minutes":5}}'
            for i in range(10)
        ]
        r = run_agent(task="끝없는 분석", farm_id=1, max_steps=3, persist_db=False)
        assert r["success"] is False
        assert "MAX_STEPS" in r["reason"]

    @patch.object(agent_mod, "_call_llm")
    def test_loop_detected(self, mock_llm):
        """같은 도구·args 3회 연속 → loop 감지로 종료."""
        same_call = '{"thought":"동일 반복", "tool":"get_sensor_window", "args":{"farm":1, "house":1, "minutes":5}}'
        mock_llm.side_effect = [same_call] * 5
        r = run_agent(task="loop 테스트", farm_id=1, max_steps=10, persist_db=False)
        assert r["success"] is False
        assert "loop" in r["reason"].lower()

    @patch.object(agent_mod, "_call_llm")
    def test_json_parse_fail_retry(self, mock_llm):
        """첫 응답이 invalid JSON 이면 가이드 후 다음 응답 정상 final 시 success."""
        mock_llm.side_effect = [
            "not json at all",
            '{"thought":"이번엔 정상", "final":"recovered"}',
        ]
        r = run_agent(task="parse 실패 테스트", farm_id=1, max_steps=3, persist_db=False)
        assert r["success"] is True
        assert r["final"] == "recovered"
        # history 에 error step + final step 모두 존재
        assert any('error' in h for h in r["steps"])
        assert any('final' in h for h in r["steps"])

    @patch.object(agent_mod, "_call_llm")
    def test_unknown_tool_handled(self, mock_llm):
        """LLM 이 없는 도구 호출 → error 결과 → 다음 step 에 final."""
        mock_llm.side_effect = [
            '{"thought":"잘못된 도구 호출", "tool":"nonexistent", "args":{}}',
            '{"thought":"오류 인지 후 종료", "final":"unknown tool 처리됨"}',
        ]
        r = run_agent(task="unknown tool", farm_id=1, max_steps=3, persist_db=False)
        assert r["success"] is True
        # 첫 step 의 tool_result 에 error
        assert "error" in r["steps"][0]["tool_result"]

    @patch.object(agent_mod, "_call_llm")
    def test_missing_tool_and_final(self, mock_llm):
        """tool/final 둘 다 없는 응답 → 가이드 후 retry."""
        mock_llm.side_effect = [
            '{"thought":"애매한 응답만"}',
            '{"thought":"이번엔 final", "final":"corrected"}',
        ]
        r = run_agent(task="missing keys", farm_id=1, max_steps=3, persist_db=False)
        assert r["success"] is True
        assert r["final"] == "corrected"


# ════════════════════════════════════════════════════════════════════
# 6) DB 영속 — _persist_agent_log
# ════════════════════════════════════════════════════════════════════
class TestPersistAgentLog:
    def test_persist_success(self):
        """정상 결과 INSERT + 통계(llm_calls/tool_calls) 산출 확인."""
        result = {
            "success": True, "final": "단위테스트", "duration_sec": 1.5,
            "steps": [
                {"step": 0, "thought": "x", "tool": "get_sensor_window", "args": {"farm": 1, "house": 1, "minutes": 5}, "tool_result": {"n": 0}},
                {"step": 1, "thought": "y", "tool": "get_sensor_window", "args": {"farm": 1, "house": 2, "minutes": 5}, "tool_result": {"n": 0}},
                {"step": 2, "thought": "z", "final": "최종"},
            ],
        }
        log_id = _persist_agent_log(result, "pytest persist", 1, "user")
        assert isinstance(log_id, int) and log_id > 0

        # SELECT 로 검증
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            r = db.fetch_all(
                "SELECT trigger_type, farm_id, task, success, llm_calls, tool_calls "
                "FROM agent_decision_log WHERE id=%s", (log_id,))
            assert len(r) == 1
            trig, farm, task, succ, llm_n, tool_counts = r[0]
            assert trig == "user"
            assert farm == 1
            assert task == "pytest persist"
            assert succ is True
            assert llm_n == 3
            # tool_calls 는 jsonb — 자동 dict 또는 str 일 수 있음
            if isinstance(tool_counts, str):
                import json as _json
                tool_counts = _json.loads(tool_counts)
            assert tool_counts.get("get_sensor_window") == 2

            # 정리 — 테스트 row 삭제
            db.execute_query("DELETE FROM agent_decision_log WHERE id=%s", (log_id,))

    def test_persist_failure(self):
        """실패 결과 (success=False + reason) 도 정상 INSERT."""
        result = {
            "success": False, "reason": "MAX_STEPS exceeded", "duration_sec": 60.5,
            "steps": [{"step": 0, "thought": "x", "tool": "get_sensor_window", "args": {}}],
        }
        log_id = _persist_agent_log(result, "fail test", 1, "schedule")
        assert isinstance(log_id, int)
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            r = db.fetch_all(
                "SELECT success, reason, trigger_type FROM agent_decision_log WHERE id=%s", (log_id,))
            assert r[0] == (False, "MAX_STEPS exceeded", "schedule")
            db.execute_query("DELETE FROM agent_decision_log WHERE id=%s", (log_id,))

    def test_persist_empty_steps(self):
        """빈 steps — llm_calls=0, tool_calls={}."""
        result = {"success": False, "reason": "empty", "duration_sec": 0.1, "steps": []}
        log_id = _persist_agent_log(result, "empty", 0, "event")
        assert isinstance(log_id, int)
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            r = db.fetch_all("SELECT llm_calls FROM agent_decision_log WHERE id=%s", (log_id,))
            assert r[0][0] == 0
            db.execute_query("DELETE FROM agent_decision_log WHERE id=%s", (log_id,))
