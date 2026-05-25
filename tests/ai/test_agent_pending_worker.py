# ══════════════════════════════════════════════════════════════════════════════
# test_agent_pending_worker — Phase 3.3 단위 테스트 [2026-05-25]
#
# 대상: agri_ai_core/src/control/agent_pending_worker.py
#   · _execute_action  : tool_name 별 dispatch + status 갱신
#   · _exec_set_relay  : relay_manager.set_relay_value mock 호출
#   · _exec_set_threshold : sensor_m_setting UPDATE (key 화이트리스트)
#   · _exec_set_growth : tools_admin.set_growth_stage mock 호출
#   · _exec_send_alert : logger 호출 (성공 반환)
#
# 정책:
#   · 실제 하드웨어/DB 변경 없는 mock 위주
#   · status 갱신 (_mark_executed/_mark_failed) 도 monkey-patch
#
# 파일 시작 함수 목록:
#   TestDispatch          : unknown tool / known tools 분기
#   TestExecSetRelay      : relay_manager 호출 인자
#   TestExecSetThreshold  : key 화이트리스트 검증 + UPDATE 호출 mock
#   TestExecSetGrowth     : tools_admin 호출 인자
#   TestExecSendAlert     : level 별 logger 호출
#   TestClaimDue          : 큐에서 row 잡아오기 (real DB)
# ══════════════════════════════════════════════════════════════════════════════
import importlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def W():
    import agri_ai_core.src.control.agent_pending_worker as mod
    importlib.reload(mod)
    return mod


# ────────────────────────────────────────────────────────────────────
# _execute_action — dispatch
# ────────────────────────────────────────────────────────────────────
class TestDispatch:
    def test_unknown_tool_marked_failed(self, W):
        with patch.object(W, "_mark_failed") as mf, \
             patch.object(W, "_mark_executed") as me:
            W._execute_action({"id": 1, "tool_name": "ghost", "args": {}})
        mf.assert_called_once()
        me.assert_not_called()
        args, _ = mf.call_args
        assert args[0] == 1
        assert "unknown tool" in args[1]["message"]

    def test_handler_exception_marked_failed(self, W):
        def boom(args): raise RuntimeError("boom")
        with patch.dict(W._DISPATCH, {"set_relay": boom}, clear=False), \
             patch.object(W, "_mark_failed") as mf, \
             patch.object(W, "_mark_executed") as me:
            W._execute_action({"id": 2, "tool_name": "set_relay",
                               "args": {"farm_id": 1, "house_id": 1,
                                        "semantic": "lighting_flag", "on": True}})
        mf.assert_called_once()
        me.assert_not_called()

    def test_success_marked_executed(self, W):
        def ok(args): return {"success": True, "message": "done"}
        with patch.dict(W._DISPATCH, {"set_relay": ok}, clear=False), \
             patch.object(W, "_mark_executed") as me, \
             patch.object(W, "_mark_failed") as mf:
            W._execute_action({"id": 3, "tool_name": "set_relay",
                               "args": {}})
        me.assert_called_once()
        mf.assert_not_called()
        args, _ = me.call_args
        assert args[1]["success"] is True
        assert "duration_sec" in args[1]


# ────────────────────────────────────────────────────────────────────
# _exec_set_relay — relay_manager 호출
# ────────────────────────────────────────────────────────────────────
class TestExecSetRelay:
    def test_calls_set_relay_value(self, W):
        mock_set = MagicMock(return_value=(True, "ok"))
        with patch("agri_ai_core.src.control.relay_manager.set_relay_value", mock_set):
            r = W._exec_set_relay({"farm_id": 1, "house_id": 2,
                                    "semantic": "water_heater_flag", "on": False})
        assert r["success"] is True
        assert r["applied"]["semantic"] == "water_heater_flag"
        assert r["applied"]["on"] is False
        # set_relay_value(farm, house, {semantic: on}, raw_mode=False) 형태
        call_args = mock_set.call_args
        assert call_args[0][0] == 1
        assert call_args[0][1] == 2
        assert call_args[0][2] == {"water_heater_flag": False}
        assert call_args[1].get("raw_mode") is False

    def test_relay_exception_returns_failure(self, W):
        with patch("agri_ai_core.src.control.relay_manager.set_relay_value",
                   side_effect=RuntimeError("hw error")):
            r = W._exec_set_relay({"farm_id": 1, "house_id": 2,
                                    "semantic": "exhaust_fan_flag", "on": True})
        assert r["success"] is False
        assert "hw error" in r["message"]


# ────────────────────────────────────────────────────────────────────
# _exec_set_threshold — key 화이트리스트 + UPDATE
# ────────────────────────────────────────────────────────────────────
class TestExecSetThreshold:
    def test_invalid_key_rejected(self, W):
        # tools_agent_write 의 화이트리스트 통과 못 함
        r = W._exec_set_threshold({"farm_id": 1, "house_id": 1,
                                    "key": "DROP TABLE", "value": 0.0})
        assert r["success"] is False
        assert "key 부적합" in r["message"]

    def test_valid_key_calls_update(self, W):
        # db._getconn / conn.cursor / conn.commit 흐름 mock
        mock_cur = MagicMock()
        mock_cur.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("agri_ai_core.src.postgresql.connection.db._getconn",
                   return_value=mock_conn), \
             patch("agri_ai_core.src.postgresql.connection.db._putconn"):
            r = W._exec_set_threshold({"farm_id": 1, "house_id": 1,
                                        "key": "tprt_min", "value": 18.5})
        assert r["success"] is True
        assert r["applied"]["key"] == "tprt_min"
        assert r["applied"]["value"] == 18.5
        # SQL 안 컬럼명이 직접 들어가야 함 (인터폴레이션)
        executed_sql = mock_cur.execute.call_args[0][0]
        assert "tprt_min" in executed_sql
        assert "UPDATE sensor_m_setting" in executed_sql

    def test_zero_rows_returns_failure(self, W):
        mock_cur = MagicMock()
        mock_cur.rowcount = 0
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        with patch("agri_ai_core.src.postgresql.connection.db._getconn",
                   return_value=mock_conn), \
             patch("agri_ai_core.src.postgresql.connection.db._putconn"):
            r = W._exec_set_threshold({"farm_id": 999, "house_id": 999,
                                        "key": "tprt_min", "value": 20.0})
        assert r["success"] is False
        assert "row 없음" in r["message"]


# ────────────────────────────────────────────────────────────────────
# _exec_set_growth — tools_admin 호출
# ────────────────────────────────────────────────────────────────────
class TestExecSetGrowth:
    def test_passes_args_to_admin(self, W):
        mock_admin = MagicMock(return_value={"success": True, "changed": []})
        with patch("agri_ai_core.src.ai.tools_admin.set_growth_stage", mock_admin):
            r = W._exec_set_growth({"farm_id": 1, "house_id": 2, "stage": "생육기"})
        assert r["success"] is True
        kw = mock_admin.call_args.kwargs
        assert kw["house_id"] == "2"
        assert kw["stage"] == "생육기"
        assert kw["farm_id"] == "1"
        assert kw["auth_farm_id"] == "1"

    def test_admin_exception_returns_failure(self, W):
        with patch("agri_ai_core.src.ai.tools_admin.set_growth_stage",
                   side_effect=ValueError("bad")):
            r = W._exec_set_growth({"farm_id": 1, "house_id": 2, "stage": "휴지기"})
        assert r["success"] is False


# ────────────────────────────────────────────────────────────────────
# _exec_send_alert — level 별 logger
# ────────────────────────────────────────────────────────────────────
class TestExecSendAlert:
    def test_returns_success(self, W):
        r = W._exec_send_alert({"level": "warning", "message": "test"})
        assert r["success"] is True
        assert r["delivered_via"] == "log"

    def test_unknown_level_defaults_info(self, W):
        # invalid level 도 worker 단계서는 logger.info 로 fallback (큐 진입은 이미
        # tools_agent_write 의 validation 통과한 후이므로 이 분기는 방어용)
        r = W._exec_send_alert({"level": "bogus", "message": "test"})
        assert r["success"] is True


# ────────────────────────────────────────────────────────────────────
# _claim_due_actions — 실제 DB (멱등 cleanup)
# ────────────────────────────────────────────────────────────────────
class TestClaimDue:
    @pytest.fixture
    def planted(self):
        """과거 execute_at 으로 1건 INSERT, yield 후 삭제."""
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            pytest.skip("DB unavailable")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_pending_actions "
                    "(execute_at, trigger_type, tool_name, args, reason, status) "
                    "VALUES (NOW() - INTERVAL '1 second', 'user', 'send_user_alert', "
                    " '{\"level\":\"info\",\"message\":\"test\"}'::jsonb, "
                    " '__pytest_worker_claim__', 'pending') RETURNING id"
                )
                aid = cur.fetchone()[0]
                conn.commit()
        finally:
            db._putconn(conn)
        yield aid
        # cleanup
        conn = db._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM agent_pending_actions WHERE reason='__pytest_worker_claim__'")
                conn.commit()
        finally:
            db._putconn(conn)

    def test_claim_returns_due_row(self, W, planted):
        rows = W._claim_due_actions(limit=50)
        ids = [r["id"] for r in rows]
        assert planted in ids
        # claim 된 row 의 tool_name / args 보존
        claimed = next(r for r in rows if r["id"] == planted)
        assert claimed["tool_name"] == "send_user_alert"
        assert claimed["args"]["level"] == "info"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
