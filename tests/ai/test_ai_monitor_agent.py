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
    _parse_response, _execute_tool, _detect_loop, _trim_tool_msg,
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

    def test_write_tool_trigger_type_injected(self):
        # write 도구 호출 시 trigger_type 자동 주입 — LLM 이 안 줘도 통과
        # 실제 큐 INSERT 가 일어나지 않도록 cooldown 으로 차단 (daily_limit 도 가능)
        import agri_ai_core.src.ai.tools_agent_write as W
        from datetime import datetime
        from unittest.mock import patch
        recent = datetime.now()  # 방금 호출한 척 → cooldown 위반
        with patch.object(W, "_last_call_at", return_value=recent), \
             patch.object(W, "_count_today", return_value=0):
            r = _execute_tool(
                "send_user_alert",
                {"level": "info", "message": "ping"},
                trigger_type="schedule")
        # cooldown 으로 거부 — 다만 호출 자체는 인자 불일치 예외 없이 통과해야 함
        assert r.get("success") is False
        assert r.get("reason") == "cooldown"


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
        # DB block 로드 확인 (Phase 2 이후 DB 단일 소스)
        p = build_system_prompt(max_steps=5)
        assert isinstance(p, str)
        assert len(p) > 500
        # Phase 2: "자율 환경제어 에이전트"로 역할 변경됨
        assert "스마트팜" in p
        assert "에이전트" in p
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
# 6) 컨텍스트 안정화 — Phase 1
# ════════════════════════════════════════════════════════════════════
class TestContextSafety:
    """_trim_tool_msg / 빈 응답 조기 종료 / 최종 보고 압박 검증."""

    # ── _trim_tool_msg ──────────────────────────────────────────────

    def test_trim_small_result_unchanged(self):
        """800자 미만 result 는 동일 객체 그대로 반환."""
        small = {"success": True, "n": 5, "note": "정상"}
        out = _trim_tool_msg(small)
        assert out == small

    def test_trim_large_result_truncated(self):
        """800자 초과 result 는 핵심 필드 + _truncated + _preview 로 압축."""
        large = {"success": True, "n": 100, "data": "x" * 2000}
        out = _trim_tool_msg(large)
        full_len = len(json.dumps(large, ensure_ascii=False))
        assert full_len > 800
        assert out["_truncated"] is True
        assert "_preview" in out
        assert len(json.dumps(out, ensure_ascii=False)) < full_len
        # 핵심 필드 보존
        assert out["success"] is True
        assert out["n"] == 100

    def test_trim_preserves_error_field(self):
        """error 필드가 있으면 압축 후에도 보존."""
        large = {"success": False, "error": "타임아웃", "data": "z" * 2000}
        out = _trim_tool_msg(large)
        assert out["error"] == "타임아웃"
        assert out["success"] is False

    def test_trim_result_boundary(self):
        """정확히 800자인 result 는 그대로."""
        s = "a" * (800 - len('{"k": ""}'))
        r = {"k": s}
        out = _trim_tool_msg(r)
        assert out == r

    # ── history 에는 full result 유지 ───────────────────────────────

    @patch.object(agent_mod, "_call_llm")
    def test_history_keeps_full_result_when_msg_trimmed(self, mock_llm):
        """큰 tool_result 라도 history 에는 full data, LLM 메시지에는 trimmed."""
        large_result = {"success": True, "n": 200, "payload": "z" * 2000}

        mock_llm.side_effect = [
            '{"thought":"데이터 조회", "tool":"get_sensor_window", "args":{"farm":1,"house":1,"minutes":5}}',
            '{"thought":"분석 완료", "final":"정상"}',
        ]
        with patch.object(agent_mod, "_execute_tool", return_value=large_result):
            r = run_agent(task="full result 보존 테스트", farm_id=1, max_steps=5, persist_db=False)

        assert r["success"] is True
        # history 에 full result 보존
        assert r["steps"][0]["tool_result"]["payload"] == "z" * 2000
        # 두 번째 LLM 호출의 messages 에는 trimmed 포함
        second_call_msgs = mock_llm.call_args_list[1][0][0]
        # user 메시지 순서: [0]=초기 task, [1]=tool_result → [-1] 이 tool_result
        tool_result_user_msg = [m for m in second_call_msgs if m["role"] == "user"][-1]["content"]
        assert "_truncated" in tool_result_user_msg
        assert len(tool_result_user_msg) < 1500

    # ── 최종 보고 압박 메시지 ────────────────────────────────────────

    @patch.object(agent_mod, "_call_llm")
    def test_pressure_message_injected_at_penultimate_step(self, mock_llm):
        """max_steps=4 기준 step2(max_steps-2) 완료 후 마지막 LLM 호출에 압박 메시지 포함."""
        # step0: tool, step1: tool, step2: tool → pressure 추가, step3: final
        mock_llm.side_effect = [
            '{"thought":"s0","tool":"get_sensor_window","args":{"farm":1,"house":1,"minutes":5}}',
            '{"thought":"s1","tool":"get_sensor_window","args":{"farm":1,"house":2,"minutes":5}}',
            '{"thought":"s2","tool":"get_sensor_window","args":{"farm":1,"house":3,"minutes":5}}',
            '{"thought":"종합","final":"압박 후 최종 보고"}',
        ]
        r = run_agent(task="압박 테스트", farm_id=1, max_steps=4, persist_db=False)
        assert r["success"] is True
        assert mock_llm.call_count == 4
        # 마지막(4번째) LLM 호출 messages 에 압박 문구 포함
        last_msgs = mock_llm.call_args_list[3][0][0]
        combined = " ".join(m["content"] for m in last_msgs if m["role"] == "user")
        assert "마지막 데이터" in combined or "최종 보고" in combined

    @patch.object(agent_mod, "_call_llm")
    def test_no_pressure_when_steps_sufficient(self, mock_llm):
        """step2=max_steps-2 에서 final 을 이미 반환했다면 pressure 는 사용 안 됨."""
        mock_llm.side_effect = [
            '{"thought":"s0","tool":"get_sensor_window","args":{"farm":1,"house":1,"minutes":5}}',
            '{"thought":"충분","final":"조기 종료"}',
        ]
        r = run_agent(task="조기종료 테스트", farm_id=1, max_steps=5, persist_db=False)
        assert r["success"] is True
        assert mock_llm.call_count == 2  # 조기에 종료, pressure 발동 안 됨

    # ── 연속 빈 응답 조기 종료 ───────────────────────────────────────

    @patch.object(agent_mod, "_call_llm")
    def test_consecutive_empty_terminates_early(self, mock_llm):
        """LLM 빈 응답 2회 연속 → MAX_STEPS 전 조기 종료."""
        mock_llm.side_effect = [
            '{"thought":"조회","tool":"get_sensor_window","args":{"farm":1,"house":1,"minutes":5}}',
            "",    # 1회 빈 응답
            "",    # 2회 연속 → 조기 종료
        ]
        r = run_agent(task="빈 응답 테스트", farm_id=1, max_steps=10, persist_db=False)
        assert r["success"] is False
        assert "빈 응답" in r["reason"]
        assert "컨텍스트 포화" in r["reason"]
        assert mock_llm.call_count == 3  # 10번 다 호출하지 않음

    @patch.object(agent_mod, "_call_llm")
    def test_single_empty_then_recovery(self, mock_llm):
        """빈 응답 1회 후 정상 응답 → 계속 진행, 조기 종료 안 됨."""
        mock_llm.side_effect = [
            "",    # 1회 빈 응답
            '{"thought":"복구","final":"빈 응답 1회 후 정상"}',
        ]
        r = run_agent(task="1회 빈 응답 복구", farm_id=1, max_steps=5, persist_db=False)
        assert r["success"] is True
        assert r["final"] == "빈 응답 1회 후 정상"

    @patch.object(agent_mod, "_call_llm")
    def test_none_response_counts_as_empty(self, mock_llm):
        """None 응답도 빈 응답으로 처리 — 2회 연속 시 조기 종료."""
        mock_llm.side_effect = [None, None]
        r = run_agent(task="None 응답 테스트", farm_id=1, max_steps=10, persist_db=False)
        assert r["success"] is False
        assert "빈 응답" in r["reason"]

    # ── num_ctx 설정값 확인 ─────────────────────────────────────────

    def test_num_ctx_env_constant_exists(self):
        """AI_CONTROL_NUM_CTX 상수가 env 로 읽혀 기본값 32768 인지 확인."""
        assert hasattr(agent_mod, "AI_CONTROL_NUM_CTX"), "AI_CONTROL_NUM_CTX 상수 없음"
        assert hasattr(agent_mod, "AI_CONTROL_NUM_PREDICT"), "AI_CONTROL_NUM_PREDICT 상수 없음"
        # env 미설정 시 기본값 유지
        import os
        env_ctx = int(os.getenv("AI_CONTROL_NUM_CTX", "32768"))
        assert agent_mod.AI_CONTROL_NUM_CTX == env_ctx


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


# ════════════════════════════════════════════════════════════════════
# Phase 3 — next_check_minutes 파싱·클램프·run_agent 반환값 검증
# ════════════════════════════════════════════════════════════════════
class TestNextCheckMinutes:
    """run_agent 가 LLM final 의 next_check_minutes 를 올바르게 처리하는지."""

    _FARM_PATCH = "agri_ai_core.src.control.ai_monitor_agent.build_system_prompt"
    _LLM_PATCH  = "agri_ai_core.src.control.ai_monitor_agent._call_llm"

    def _run(self, final_json: dict) -> dict:
        """단일 final 응답 mock 으로 run_agent 실행 (DB INSERT 없음)."""
        raw = json.dumps(final_json, ensure_ascii=False)
        with patch(self._FARM_PATCH, return_value="TEST_SYSTEM"), \
             patch(self._LLM_PATCH, return_value=raw):
            return run_agent("테스트 작업", farm_id=1, max_steps=5, persist_db=False)

    def test_ncm_present_returned(self):
        """final 에 next_check_minutes=10 → 반환값에 10 포함."""
        res = self._run({"thought": "t", "final": "보고", "next_check_minutes": 10})
        assert res["success"] is True
        assert res["next_check_minutes"] == 10

    def test_ncm_absent_returns_none(self):
        """final 에 next_check_minutes 없음 → 반환값에 None."""
        res = self._run({"thought": "t", "final": "보고"})
        assert res["success"] is True
        assert res["next_check_minutes"] is None

    def test_ncm_clamped_below_min(self):
        """next_check_minutes=1 (< _NCM_MIN=3) → 3 으로 클램프."""
        res = self._run({"thought": "t", "final": "보고", "next_check_minutes": 1})
        assert res["next_check_minutes"] == agent_mod._NCM_MIN

    def test_ncm_clamped_above_max(self):
        """next_check_minutes=999 (> _NCM_MAX=60) → 60 으로 클램프."""
        res = self._run({"thought": "t", "final": "보고", "next_check_minutes": 999})
        assert res["next_check_minutes"] == agent_mod._NCM_MAX

    def test_ncm_exact_min(self):
        """next_check_minutes=_NCM_MIN → 그대로 반환."""
        res = self._run({"thought": "t", "final": "보고",
                         "next_check_minutes": agent_mod._NCM_MIN})
        assert res["next_check_minutes"] == agent_mod._NCM_MIN

    def test_ncm_exact_max(self):
        """next_check_minutes=_NCM_MAX → 그대로 반환."""
        res = self._run({"thought": "t", "final": "보고",
                         "next_check_minutes": agent_mod._NCM_MAX})
        assert res["next_check_minutes"] == agent_mod._NCM_MAX

    def test_ncm_float_truncated_to_int(self):
        """next_check_minutes=7.9 → int(7) → 7."""
        res = self._run({"thought": "t", "final": "보고", "next_check_minutes": 7.9})
        assert res["next_check_minutes"] == 7

    def test_ncm_invalid_string_becomes_none(self):
        """next_check_minutes='빠름' (비숫자) → None."""
        res = self._run({"thought": "t", "final": "보고", "next_check_minutes": "빠름"})
        assert res["next_check_minutes"] is None

    def test_ncm_null_becomes_none(self):
        """next_check_minutes=null (JSON null) → None."""
        res = self._run({"thought": "t", "final": "보고", "next_check_minutes": None})
        assert res["next_check_minutes"] is None

    def test_failure_result_has_no_ncm(self):
        """max_steps 초과 실패 결과는 next_check_minutes 키 없거나 None."""
        raw_final = json.dumps({"thought": "t", "tool": "get_sensor_window",
                                "args": {"farm": 1, "house": 1, "minutes": 5}})
        with patch(self._FARM_PATCH, return_value="SYS"), \
             patch(self._LLM_PATCH, return_value=raw_final), \
             patch("agri_ai_core.src.control.ai_monitor_agent._execute_tool",
                   return_value={"success": True}):
            res = run_agent("테스트", farm_id=1, max_steps=2, persist_db=False)
        assert res["success"] is False
        assert res.get("next_check_minutes") is None

    def test_ncm_constants_exist(self):
        """_NCM_MIN, _NCM_MAX 상수가 소스에 정의되어 있고 올바른 관계."""
        assert agent_mod._NCM_MIN >= 1
        assert agent_mod._NCM_MAX <= 120
        assert agent_mod._NCM_MIN < agent_mod._NCM_MAX


# ════════════════════════════════════════════════════════════════════
# Phase 2 — 조회 도구 반복 제한 + 쓰기 도구 즉시 final 압박
# ════════════════════════════════════════════════════════════════════
class TestReadToolLimit:
    """조회 도구 _MAX_READ_TOOL_CALLS 초과 시 skip + final 압박 검증."""

    _LLM  = "agri_ai_core.src.control.ai_monitor_agent._call_llm"
    _SYS  = "agri_ai_core.src.control.ai_monitor_agent.build_system_prompt"
    _EXEC = "agri_ai_core.src.control.ai_monitor_agent._execute_tool"

    def test_max_read_tool_calls_constant_exists(self):
        """_MAX_READ_TOOL_CALLS 상수 존재 + 양수."""
        assert hasattr(agent_mod, "_MAX_READ_TOOL_CALLS")
        assert agent_mod._MAX_READ_TOOL_CALLS >= 1

    @patch.object(agent_mod, "_call_llm")
    @patch.object(agent_mod, "_execute_tool", return_value={"success": True, "n": 0})
    def test_read_tool_skipped_after_limit(self, mock_exec, mock_llm):
        """같은 조회 도구 _MAX_READ_TOOL_CALLS+1 회 시 마지막 호출 skip → final 압박 주입.

        실제 패턴: 하우스별 args가 달라 _detect_loop 에는 걸리지 않지만
        같은 '도구 이름' 기준으로 _MAX_READ_TOOL_CALLS 초과 시 skip.
        """
        limit = agent_mod._MAX_READ_TOOL_CALLS
        # args 를 하우스별로 다르게 → _detect_loop 미발동, 도구 이름 카운터만 증가
        tool_resps = [
            json.dumps({"thought": "x", "tool": "get_sensor_window",
                        "args": {"farm": 1, "house": i, "minutes": 5}})
            for i in range(1, limit + 2)  # limit+1 개
        ]
        mock_llm.side_effect = tool_resps + ['{"thought":"done","final":"보고","next_check_minutes":30}']
        with patch(self._SYS, return_value="SYS"):
            r = run_agent("테스트", farm_id=1, max_steps=20, persist_db=False)
        # limit 회까지만 실제 실행 (limit+1 회째는 skip)
        assert mock_exec.call_count == limit
        assert r["success"] is True
        # skip 된 step 에 _skipped 키가 있어야 함
        skipped = [s for s in r["steps"] if "_skipped" in s]
        assert len(skipped) >= 1

    @patch.object(agent_mod, "_call_llm")
    @patch.object(agent_mod, "_execute_tool", return_value={"success": True, "n": 0})
    def test_different_read_tools_have_separate_counts(self, mock_exec, mock_llm):
        """서로 다른 조회 도구는 각자 독립 카운터 — 교대 호출 시 각각 limit 적용.

        get_thresholds 와 get_sensor_window 를 교대로 limit+1 회씩 호출.
        하우스 args 를 다르게 하여 _detect_loop 미발동.
        """
        limit = agent_mod._MAX_READ_TOOL_CALLS
        # 각 도구를 하우스별 다른 args 로 limit+1 회 → _detect_loop 미발동
        side = []
        for i in range(1, limit + 2):
            side.append(json.dumps({"thought": "t", "tool": "get_thresholds",
                                    "args": {"farm": 1, "house": i}}))
            side.append(json.dumps({"thought": "s", "tool": "get_sensor_window",
                                    "args": {"farm": 1, "house": i, "minutes": 5}}))
        side.append('{"thought":"done","final":"완료","next_check_minutes":30}')
        mock_llm.side_effect = side
        with patch(self._SYS, return_value="SYS"):
            r = run_agent("교대 호출 테스트", farm_id=1, max_steps=30, persist_db=False)
        # 실행 횟수 = limit×2 (각 도구 limit 회씩, 마지막 1회씩은 skip)
        assert mock_exec.call_count == limit * 2
        assert r["success"] is True


class TestWriteToolFinalPressure:
    """쓰기 도구(set_relay 등) 성공 직후 즉시 final 압박 주입 검증."""

    _LLM  = "agri_ai_core.src.control.ai_monitor_agent._call_llm"
    _SYS  = "agri_ai_core.src.control.ai_monitor_agent.build_system_prompt"
    _EXEC = "agri_ai_core.src.control.ai_monitor_agent._execute_tool"

    @patch.object(agent_mod, "_call_llm")
    @patch.object(agent_mod, "_execute_tool")
    def test_final_pressure_after_set_relay_success(self, mock_exec, mock_llm):
        """set_relay 성공 다음 LLM 호출 messages 에 '제어가 완료' 문구 포함."""
        mock_exec.return_value = {"success": True, "relay": "on"}  # 쓰기 도구 성공
        mock_llm.side_effect = [
            '{"thought":"제어","tool":"set_relay","args":{"farm_id":1,"house_id":1,"relay_number":1,"state":true}}',
            '{"thought":"완료","final":"가온 ON 완료","next_check_minutes":30}',
        ]
        with patch(self._SYS, return_value="SYS"):
            r = run_agent("릴레이 제어", farm_id=1, max_steps=5, persist_db=False)
        assert r["success"] is True
        # 두 번째 LLM 호출 messages 에 '제어가 완료' 포함 여부 확인
        second_msgs = mock_llm.call_args_list[1][0][0]
        combined = " ".join(m["content"] for m in second_msgs if m["role"] == "user")
        assert "제어가 완료" in combined

    @patch.object(agent_mod, "_call_llm")
    @patch.object(agent_mod, "_execute_tool")
    def test_no_pressure_when_write_tool_fails(self, mock_exec, mock_llm):
        """set_relay 실패(success=False) 시 즉시 final 압박 미주입 — 정상 흐름 계속."""
        mock_exec.return_value = {"success": False, "error": "냉각 중"}
        mock_llm.side_effect = [
            '{"thought":"제어","tool":"set_relay","args":{"farm_id":1,"house_id":1,"relay_number":1,"state":true}}',
            '{"thought":"실패 후 계속","final":"제어 실패 — 재시도 예정","next_check_minutes":5}',
        ]
        with patch(self._SYS, return_value="SYS"):
            r = run_agent("실패 릴레이 제어", farm_id=1, max_steps=5, persist_db=False)
        assert r["success"] is True
        # 두 번째 LLM 호출에 '제어가 완료' 압박 없음
        second_msgs = mock_llm.call_args_list[1][0][0]
        combined = " ".join(m["content"] for m in second_msgs if m["role"] == "user")
        assert "제어가 완료" not in combined
