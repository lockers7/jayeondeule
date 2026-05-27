# ══════════════════════════════════════════════════════════════════════════════
# test_tools_agent_write — agent 쓰기 도구 단위 테스트
#
# 대상: agri_ai_core/src/ai/tools_agent_write.py
#   · args validation (4개 도구)
#   · safety_guard (daily_limit, cooldown)
#   · _enqueue (DB INSERT)
#   · TOOL_REGISTRY / TOOL_SPECS / tool_specs_text
#
# 정책:
#   · DB 호출 부분은 monkey-patch (실제 INSERT 안 함)
#   · 실제 DB INSERT 는 별도 TestRealDB 클래스 — 끝나면 cleanup
#
# 파일 시작 함수 목록:
#   TestArgsValidation        : 4개 도구 인자 검증
#   TestSafetyGuardMocked     : daily_limit / cooldown — monkey-patch
#   TestRegistry              : TOOL_REGISTRY 와 TOOL_SPECS 정합성
#   TestRealDB                : 실제 DB INSERT + cleanup
# ══════════════════════════════════════════════════════════════════════════════
import importlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture
def W():
    import agri_ai_core.src.ai.tools_agent_write as mod
    importlib.reload(mod)
    return mod


# ────────────────────────────────────────────────────────────────────
# 인자 검증
# ────────────────────────────────────────────────────────────────────
class TestArgsValidation:
    def test_set_relay_invalid_semantic(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_relay(farm_id=1, house_id=2, semantic="nope", on=True)
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_set_relay_invalid_on_type(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_relay(farm_id=1, house_id=2, semantic="water_heater_flag", on="true")
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_set_relay_valid(self, W):
        with patch.object(W, "_enqueue", return_value=101), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_relay(farm_id=1, house_id=2, semantic="water_heater_flag",
                            on=False, reason="수온 위험")
        assert r["success"] is True
        assert r["action_id"] == 101
        assert r["execute_in_seconds"] == W.CANCELLABLE_SECONDS

    def test_set_threshold_invalid_key(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_threshold(farm_id=1, house_id=2, key="bogus", value=20.0)
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_set_threshold_value_out_of_range(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_threshold(farm_id=1, house_id=2, key="tprt_min", value=99999)
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_set_threshold_valid(self, W):
        with patch.object(W, "_enqueue", return_value=102), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_threshold(farm_id=1, house_id=2, key="tprt_min", value=18.5,
                                reason="저온 보정")
        assert r["success"] is True
        assert r["action_id"] == 102

    def test_set_growth_invalid_stage(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_growth_stage(farm_id=1, house_id=2, stage="잘못된단계")
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_set_growth_valid(self, W):
        with patch.object(W, "_enqueue", return_value=103), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_growth_stage(farm_id=1, house_id=2, stage="생육기",
                                   reason="수확 다가옴")
        assert r["success"] is True
        assert r["action_id"] == 103

    def test_alert_invalid_level(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.send_user_alert(level="urgent", message="test")
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_alert_empty_message(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.send_user_alert(level="info", message="   ")
        assert r["success"] is False
        assert r["reason"] == "invalid_args"

    def test_alert_too_long(self, W):
        with patch.object(W, "_enqueue", return_value=99), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.send_user_alert(level="info", message="x" * 1001)
        assert r["success"] is False

    def test_alert_valid_immediate(self, W):
        with patch.object(W, "_enqueue", return_value=104), \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.send_user_alert(level="warning", message="센서 이상")
        assert r["success"] is True
        # send_user_alert 는 cancellable=0 즉시 실행
        assert r["execute_in_seconds"] == 0


# ────────────────────────────────────────────────────────────────────
# safety_guard — daily_limit / cooldown
# ────────────────────────────────────────────────────────────────────
class TestSafetyGuardMocked:
    def test_daily_limit_block(self, W):
        # daily_limit 도달 — 큐 INSERT 안 됨.
        # set_relay 는 override 한도(500)를 쓰므로 유효 한도 기준으로 검증.
        eff_limit = W.TOOL_DAILY_LIMIT_OVERRIDE.get("set_relay", W.DAILY_LIMIT)
        with patch.object(W, "_enqueue", return_value=99) as enq, \
             patch.object(W, "_count_today", return_value=eff_limit), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_relay(farm_id=1, house_id=2, semantic="water_heater_flag", on=False)
        assert r["success"] is False
        assert r["reason"] == "daily_limit"
        enq.assert_not_called()

    def test_set_relay_limit_covers_normal_usage(self, W):
        # 정상 운용량(사이클당 2~3콜 × 144사이클 = 최대 432건)이
        # 한도에 걸리지 않아야 함.
        assert W.TOOL_DAILY_LIMIT_OVERRIDE["set_relay"] >= 500

    def test_set_relay_pass_below_limit(self, W):
        # 한도 직전(499)까지는 정상 통과 — agent 자율권 보장
        eff_limit = W.TOOL_DAILY_LIMIT_OVERRIDE["set_relay"]
        with patch.object(W, "_enqueue", return_value=120) as enq, \
             patch.object(W, "_count_today", return_value=eff_limit - 1), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_relay(farm_id=1, house_id=2, semantic="water_heater_flag", on=False)
        assert r["success"] is True
        enq.assert_called_once()


# ────────────────────────────────────────────────────────────────────
# send_user_alert 중복 억제(dedupe)
# ────────────────────────────────────────────────────────────────────
class TestAlertDedup:
    def test_duplicate_alert_blocked(self, W):
        # 동일 message 가 dedupe 창 내 발송됨 — 큐 INSERT 억제 + LLM 안내 메시지
        recent = datetime.now() - timedelta(minutes=5)
        with patch.object(W, "_enqueue", return_value=99) as enq, \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None), \
             patch.object(W, "_same_alert_recent", return_value=recent):
            r = W.send_user_alert(level="warning", message="습도 높음")
        assert r["success"] is False
        assert r["reason"] == "duplicate_alert"
        assert "중복" in r["message"]          # LLM 에게 사유 전달
        assert "다시 알리세요" in r["message"]  # 갱신 재발송 안내
        enq.assert_not_called()

    def test_new_alert_passes(self, W):
        # 새 내용 알림 — 정상 발송
        with patch.object(W, "_enqueue", return_value=101) as enq, \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None), \
             patch.object(W, "_same_alert_recent", return_value=None):
            r = W.send_user_alert(level="critical", message="습도 100% 신규 위기")
        assert r["success"] is True
        enq.assert_called_once()

    def test_dedup_lookup_failure_does_not_block(self, W):
        # dedupe 조회 실패(None 반환) 시 알림은 발송되어야 — 누락 방지 우선
        with patch.object(W, "_enqueue", return_value=102) as enq, \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None), \
             patch.object(W, "_same_alert_recent", return_value=None):
            r = W.send_user_alert(level="info", message="정기 보고")
        assert r["success"] is True
        enq.assert_called_once()

    def test_alert_limit_raised(self, W):
        # 한도 100 이상 보장 (폭주 차단 전용)
        assert W.TOOL_DAILY_LIMIT_OVERRIDE["send_user_alert"] >= 100

    def test_cooldown_block(self, W):
        # 30초 전 동일 호출 — cooldown(60s) 위반
        recent = datetime.now() - timedelta(seconds=30)
        with patch.object(W, "_enqueue", return_value=99) as enq, \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=recent):
            r = W.set_relay(farm_id=1, house_id=2, semantic="water_heater_flag", on=False)
        assert r["success"] is False
        assert r["reason"] == "cooldown"
        enq.assert_not_called()

    def test_cooldown_pass(self, W):
        # 70초 전 호출 — cooldown(60s) 통과
        old = datetime.now() - timedelta(seconds=70)
        with patch.object(W, "_enqueue", return_value=110) as enq, \
             patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=old):
            r = W.set_relay(farm_id=1, house_id=2, semantic="water_heater_flag", on=False)
        assert r["success"] is True
        enq.assert_called_once()

    def test_alert_higher_daily_limit(self, W):
        # send_user_alert 는 default 50 — 일반 10 보다 관대
        with patch.object(W, "_enqueue", return_value=120) as enq, \
             patch.object(W, "_count_today", return_value=20), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.send_user_alert(level="info", message="test")
        assert r["success"] is True
        enq.assert_called_once()


# ────────────────────────────────────────────────────────────────────
# Registry / Specs 정합성
# ────────────────────────────────────────────────────────────────────
class TestRegistry:
    def test_registry_keys(self, W):
        assert set(W.TOOL_REGISTRY.keys()) == {
            "set_relay", "set_threshold", "set_growth_stage", "send_user_alert"
        }

    def test_specs_match_registry(self, W):
        spec_names = {s["name"] for s in W.TOOL_SPECS}
        assert spec_names == set(W.TOOL_REGISTRY.keys())

    def test_specs_text_includes_all_tools(self, W):
        txt = W.tool_specs_text()
        for name in W.TOOL_REGISTRY.keys():
            assert name in txt

    def test_alert_cancellable_is_zero(self, W):
        assert W.TOOL_CANCELLABLE_OVERRIDE["send_user_alert"] == 0


# ────────────────────────────────────────────────────────────────────
# 실제 DB INSERT + cleanup
# ────────────────────────────────────────────────────────────────────
class TestRealDB:
    @pytest.fixture(autouse=True)
    def _cleanup(self):
        """테스트 끝나면 이 테스트가 만든 row 삭제 (reason 식별)."""
        yield
        try:
            from agri_ai_core.src.postgresql.connection import db
            conn = db._getconn()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM agent_pending_actions WHERE reason='__pytest_tools_write__'")
                        conn.commit()
                finally:
                    db._putconn(conn)
        except Exception:
            pass

    def test_set_relay_real_insert(self, W):
        # 큐에 INSERT 됐는지 확인
        with patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.set_relay(farm_id=999, house_id=999,
                            semantic="water_heater_flag", on=False,
                            reason="__pytest_tools_write__",
                            trigger_type="user")
        assert r["success"] is True
        assert r["action_id"] is not None

        # DB 에서 row 확인
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                query="SELECT * FROM agent_pending_actions WHERE id=%s",
                vals=(r["action_id"],))
        assert row is not None
        assert row["tool_name"] == "set_relay"
        assert row["status"] == "pending"
        assert row["args"]["semantic"] == "water_heater_flag"
        # execute_at = created_at + 30s (대략)
        delta = (row["execute_at"] - row["created_at"]).total_seconds()
        assert 25 <= delta <= 35

    def test_alert_real_insert_immediate(self, W):
        with patch.object(W, "_count_today", return_value=0), \
             patch.object(W, "_last_call_at", return_value=None):
            r = W.send_user_alert(level="info", message="pytest alert",
                                  reason="__pytest_tools_write__")
        assert r["success"] is True
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                query="SELECT * FROM agent_pending_actions WHERE id=%s",
                vals=(r["action_id"],))
        # cancellable=0 → execute_at ≈ created_at
        delta = (row["execute_at"] - row["created_at"]).total_seconds()
        assert -2 <= delta <= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
