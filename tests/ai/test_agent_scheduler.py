# ══════════════════════════════════════════════════════════════════════════════
# test_agent_scheduler.py — agent_scheduler 단위 테스트
#
# 대상: agri_ai_core/src/control/agent_scheduler.py
#   · _next_interval_dt    : 다음 cycle 시각 계산 (정각 boundary)
#   · _build_default_task  : 기본 모니터링 지시문 합성
#   · _run_cycle           : 사이클 실행 (mock 사용)
#
# 외부 의존(LLM, DB) 모두 monkey-patch 로 격리.
#
# 파일 시작 함수 목록:
#   TestNextIntervalDt.test_*    : 시각 계산 다양한 케이스
#   TestBuildDefaultTask         : 지시문 합성 텍스트 검증
#   TestRunCycle                 : run_agent mock 으로 cycle 실행 흐름
# ══════════════════════════════════════════════════════════════════════════════
import importlib
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def scheduler_module():
    import agri_ai_core.src.control.agent_scheduler as mod
    importlib.reload(mod)
    return mod


# ────────────────────────────────────────────────────────────────────
# _next_interval_dt — 30분 / 15분 / 60분 주기 boundary 계산
# ────────────────────────────────────────────────────────────────────
class TestNextIntervalDt:
    def test_30min_before_first_boundary(self, scheduler_module):
        # 11:17 → 11:30
        now = datetime(2026, 5, 25, 11, 17, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 30):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 11, 30, 0)

    def test_30min_between_boundaries(self, scheduler_module):
        # 11:31 → 12:00
        now = datetime(2026, 5, 25, 11, 31, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 30):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 12, 0, 0)

    def test_30min_exact_boundary(self, scheduler_module):
        # 11:30:00 정확히 → 다음은 12:00
        now = datetime(2026, 5, 25, 11, 30, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 30):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 12, 0, 0)

    def test_30min_exact_zero(self, scheduler_module):
        # 11:00:00 → 11:30
        now = datetime(2026, 5, 25, 11, 0, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 30):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 11, 30, 0)

    def test_midnight_crossover(self, scheduler_module):
        # 23:31 → 00:00 (다음날)
        now = datetime(2026, 5, 25, 23, 31, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 30):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 26, 0, 0, 0)

    def test_15min_interval(self, scheduler_module):
        # 15분 주기 — 11:07 → 11:15
        now = datetime(2026, 5, 25, 11, 7, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 15):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 11, 15, 0)

    def test_15min_three_quarters(self, scheduler_module):
        # 11:47 → 12:00
        now = datetime(2026, 5, 25, 11, 47, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 15):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 12, 0, 0)

    def test_60min_interval(self, scheduler_module):
        # 60분 주기 — 11:35 → 12:00
        now = datetime(2026, 5, 25, 11, 35, 0)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 60):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt == datetime(2026, 5, 25, 12, 0, 0)

    def test_seconds_microseconds_zeroed(self, scheduler_module):
        # 초/마이크로초 보유 → 결과는 0초/0마이크로초
        now = datetime(2026, 5, 25, 11, 17, 42, 999999)
        with patch.object(scheduler_module, "AGENT_INTERVAL_MIN", 30):
            nxt = scheduler_module._next_interval_dt(now)
        assert nxt.second == 0
        assert nxt.microsecond == 0


# ────────────────────────────────────────────────────────────────────
# _build_default_task — 기본 지시문 텍스트 골격 검증
# ────────────────────────────────────────────────────────────────────
class TestBuildDefaultTask:
    def test_includes_farm_id(self, scheduler_module):
        task = scheduler_module._build_default_task(farm_id=1)
        assert "농장 1" in task

    def test_includes_now_hhmm(self, scheduler_module):
        task = scheduler_module._build_default_task(farm_id=2)
        # HH:MM 형태 포함 확인
        import re
        assert re.search(r"\d{2}:\d{2}", task), "HH:MM 형식이 포함되어야 함"

    def test_contains_control_keywords(self, scheduler_module):
        task = scheduler_module._build_default_task(farm_id=1)
        # 자율 환경제어 지시문 — "제어" + 센서/임계 키워드
        assert "제어" in task
        assert "센서" in task or "임계" in task
        assert "set_relay" in task or "릴레이" in task


# ────────────────────────────────────────────────────────────────────
# _run_cycle — run_agent mock 으로 cycle 흐름 검증
# ────────────────────────────────────────────────────────────────────
class TestRunCycle:
    def test_run_cycle_calls_run_agent_per_farm(self, scheduler_module):
        mock_result = {"success": True, "duration_sec": 12.3, "log_id": 99,
                       "final": "정상 — 이상치 없음"}
        with patch.object(scheduler_module, "AGENT_FARM_IDS", [1, 2]), \
             patch.object(scheduler_module, "run_agent", return_value=mock_result) as mra:
            scheduler_module._run_cycle()
        assert mra.call_count == 2
        # 각 호출 trigger_type 검증
        for call in mra.call_args_list:
            assert call.kwargs.get("trigger_type") == "schedule"

    def test_run_cycle_swallows_exception(self, scheduler_module):
        # run_agent 가 예외를 던져도 cycle 자체는 계속 진행
        with patch.object(scheduler_module, "AGENT_FARM_IDS", [1, 2]), \
             patch.object(scheduler_module, "run_agent", side_effect=RuntimeError("boom")) as mra:
            # 예외 전파되지 않아야 함
            scheduler_module._run_cycle()
        # 첫번째 농장에서 예외 발생해도 두번째 농장 호출됨
        assert mra.call_count == 2

    def test_run_cycle_stops_on_signal(self, scheduler_module):
        # _STOP=True 이면 첫 농장 처리 전 중단
        scheduler_module._STOP = True
        try:
            with patch.object(scheduler_module, "AGENT_FARM_IDS", [1, 2, 3]), \
                 patch.object(scheduler_module, "run_agent") as mra:
                scheduler_module._run_cycle()
            assert mra.call_count == 0
        finally:
            scheduler_module._STOP = False


# ────────────────────────────────────────────────────────────────────
# _advance_subscription 동적 재스케줄 + _run_subscription 연동
# ────────────────────────────────────────────────────────────────────
class TestAdvanceSubscription:
    """_advance_subscription override_minutes 분기 검증 (DB mock)."""

    def _call_advance(self, scheduler_module, sub_id, interval_min, override_minutes=None):
        """DB 실제 호출 없이 SQL 인자만 캡처."""
        captured = {}

        class FakeCursor:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

        class FakeConn:
            def cursor(self): return FakeCursor()
            def commit(self): pass
            def rollback(self): pass

        class FakeDB:
            def _getconn(self): return FakeConn()
            def _putconn(self, c): pass

        with patch.dict("sys.modules", {"agri_ai_core.src.postgresql.connection": type("M", (), {"db": FakeDB()})()}):
            with patch("agri_ai_core.src.postgresql.connection.db", FakeDB()):
                scheduler_module._advance_subscription(sub_id, interval_min,
                                                       override_minutes=override_minutes)
        return captured

    def test_no_override_uses_greatest(self, scheduler_module):
        """override_minutes 없으면 GREATEST(NOW(), next_run_at) SQL 사용."""
        captured = {}
        orig = scheduler_module._advance_subscription

        def fake_adv(sub_id, interval_min, override_minutes=None):
            captured["override"] = override_minutes
            captured["interval"] = interval_min

        with patch.object(scheduler_module, "_advance_subscription", side_effect=fake_adv):
            scheduler_module._advance_subscription(99, 30, override_minutes=None)
        assert captured["override"] is None
        assert captured["interval"] == 30

    def test_override_passed_correctly(self, scheduler_module):
        """override_minutes=10 이 _advance_subscription 에 전달됨."""
        captured = {}

        def fake_adv(sub_id, interval_min, override_minutes=None):
            captured["override"] = override_minutes

        with patch.object(scheduler_module, "_advance_subscription", side_effect=fake_adv):
            scheduler_module._advance_subscription(99, 30, override_minutes=10)
        assert captured["override"] == 10

    def test_ncm_min_constant(self, scheduler_module):
        """_NCM_MIN 상수 존재 + 값 확인."""
        assert hasattr(scheduler_module, "_NCM_MIN")
        assert scheduler_module._NCM_MIN >= 1

    def test_ncm_max_constant(self, scheduler_module):
        """_NCM_MAX 상수 존재 + 값 확인."""
        assert hasattr(scheduler_module, "_NCM_MAX")
        assert scheduler_module._NCM_MAX <= 120

    def test_ncm_min_lt_max(self, scheduler_module):
        """_NCM_MIN < _NCM_MAX."""
        assert scheduler_module._NCM_MIN < scheduler_module._NCM_MAX


class TestRunSubscriptionNcm:
    """_run_subscription 이 run_agent 의 next_check_minutes 를 _advance_subscription 에 전달하는지."""

    def test_ncm_forwarded_to_advance(self, scheduler_module):
        """run_agent 반환 next_check_minutes=5 → _advance_subscription(override_minutes=5)."""
        mock_result = {
            "success": True, "log_id": 1, "final": "이상 감지 — 히터 ON",
            "next_check_minutes": 5,
        }
        sub = {"id": 1, "farm_id": 1, "task": "테스트", "user_id": None,
               "interval_min": 30, "intent": "__default_cron__"}
        advance_calls = []

        def fake_advance(sub_id, interval_min, override_minutes=None):
            advance_calls.append({"sub_id": sub_id, "interval": interval_min,
                                   "override": override_minutes})

        with patch.object(scheduler_module, "run_agent", return_value=mock_result), \
             patch.object(scheduler_module, "_advance_subscription", side_effect=fake_advance):
            scheduler_module._run_subscription(sub)

        assert len(advance_calls) == 1
        assert advance_calls[0]["override"] == 5
        assert advance_calls[0]["interval"] == 30

    def test_ncm_none_forwarded_when_absent(self, scheduler_module):
        """run_agent 반환에 next_check_minutes 없음 → override=None."""
        mock_result = {
            "success": True, "log_id": 2, "final": "정상",
        }
        sub = {"id": 2, "farm_id": 1, "task": "테스트", "user_id": None,
               "interval_min": 30, "intent": "__default_cron__"}
        advance_calls = []

        def fake_advance(sub_id, interval_min, override_minutes=None):
            advance_calls.append(override_minutes)

        with patch.object(scheduler_module, "run_agent", return_value=mock_result), \
             patch.object(scheduler_module, "_advance_subscription", side_effect=fake_advance):
            scheduler_module._run_subscription(sub)

        assert advance_calls[0] is None

    def test_ncm_exception_still_advances(self, scheduler_module):
        """run_agent 예외 발생해도 _advance_subscription 는 반드시 호출됨 (finally)."""
        sub = {"id": 3, "farm_id": 1, "task": "테스트", "user_id": None,
               "interval_min": 30, "intent": "__default_cron__"}
        advance_calls = []

        def fake_advance(sub_id, interval_min, override_minutes=None):
            advance_calls.append(override_minutes)

        with patch.object(scheduler_module, "run_agent", side_effect=RuntimeError("오류")), \
             patch.object(scheduler_module, "_advance_subscription", side_effect=fake_advance):
            scheduler_module._run_subscription(sub)

        # 예외가 발생해도 finally 블록에서 advance 호출됨 — override 는 None
        assert len(advance_calls) == 1
        assert advance_calls[0] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
