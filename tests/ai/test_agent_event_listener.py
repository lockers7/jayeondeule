# ══════════════════════════════════════════════════════════════════════════════
# test_agent_event_listener.py — Phase 5 단위 테스트 [2026-05-27]
#
# 대상: agri_ai_core/src/control/agent_event_listener.py
#   · _handle_event         : payload 파싱 / 쿨다운 / trigger 호출
#   · _trigger_subscriptions: UPDATE mock 호출 + 반환값 검증
#   · _run_heartbeat_check  : DB 쿼리 mock + 단절 이벤트 주입 검증
#
# 정책:
#   · 실제 DB / LISTEN 소켓 미사용 — 모두 mock 격리
#   · 쿨다운 상태는 각 테스트 전 초기화 (_cooldown.clear())
#   · importlib.reload 로 모듈 전역 상태 초기화
#
# 파일 시작 함수 목록:
#   TestHandleEvent           : payload 파싱·쿨다운·trigger 호출 흐름
#   TestTriggerSubscriptions  : DB UPDATE 인자·반환값 검증
#   TestHeartbeatCheck        : 단절 감지 이벤트 주입 검증
#   TestCooldownIsolation     : 쿨다운 키 독립성 (farm/house 다르면 별도 카운트)
# ══════════════════════════════════════════════════════════════════════════════
import importlib
import json
import time
from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture
def M():
    import agri_ai_core.src.control.agent_event_listener as mod
    importlib.reload(mod)
    # 각 테스트 전 쿨다운 상태 초기화
    mod._cooldown.clear()
    return mod


# ────────────────────────────────────────────────────────────────────
# _handle_event — payload 파싱 / 쿨다운 / trigger 호출 흐름
# ────────────────────────────────────────────────────────────────────
class TestHandleEvent:
    def test_sensor_threshold_triggers_subscription(self, M):
        """sensor_threshold 이벤트 — _trigger_subscriptions 호출 확인"""
        payload = json.dumps({
            "event":     "sensor_threshold",
            "farm_id":   1,
            "house_id":  2,
            "sensor":    "tprt",
            "value":     16.0,
            "threshold": 15.0,
            "direction": "low",
        })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            M._handle_event(payload)
        mock_trig.assert_called_once_with(farm_id=1, house_id=2, event_type="sensor_threshold")

    def test_llm_keep_streak_triggers_subscription(self, M):
        """llm_keep_streak 이벤트 — _trigger_subscriptions 호출 확인"""
        payload = json.dumps({
            "event":    "llm_keep_streak",
            "farm_id":  1,
            "house_id": 3,
            "streak":   5,
        })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "_trigger_subscriptions", return_value=2) as mock_trig:
            M._handle_event(payload)
        mock_trig.assert_called_once_with(farm_id=1, house_id=3, event_type="llm_keep_streak")

    def test_invalid_json_skipped(self, M):
        """파싱 불가 payload — trigger 미호출"""
        with patch.object(M, "_trigger_subscriptions") as mock_trig:
            M._handle_event("not-json-{{")
        mock_trig.assert_not_called()

    def test_missing_farm_id_skipped(self, M):
        """farm_id 누락 payload — trigger 미호출"""
        payload = json.dumps({"event": "sensor_threshold", "house_id": 1})
        with patch.object(M, "_trigger_subscriptions") as mock_trig:
            M._handle_event(payload)
        mock_trig.assert_not_called()

    def test_non_monitored_farm_skipped(self, M):
        """모니터링 대상 아닌 farm_id — trigger 미호출"""
        payload = json.dumps({
            "event":    "llm_keep_streak",
            "farm_id":  99,
            "house_id": 1,
            "streak":   5,
        })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1, 2]), \
             patch.object(M, "_trigger_subscriptions") as mock_trig:
            M._handle_event(payload)
        mock_trig.assert_not_called()

    def test_cooldown_suppresses_duplicate(self, M):
        """동일 (event, farm, house) 는 쿨다운 내 재발화 억제"""
        payload = json.dumps({
            "event":    "sensor_threshold",
            "farm_id":  1,
            "house_id": 1,
            "sensor":   "tprt",
            "value":    16.0,
            "threshold": 15.0,
            "direction": "low",
        })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "AGENT_EVENT_COOLDOWN_SEC", 9999), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            # 첫 번째 호출 — trigger 실행
            M._handle_event(payload)
            # 두 번째 호출 — 쿨다운으로 억제
            M._handle_event(payload)
        assert mock_trig.call_count == 1, "쿨다운 내 재발화가 억제되어야 함"

    def test_cooldown_expired_triggers_again(self, M):
        """쿨다운 만료 후 재발화 허용"""
        payload = json.dumps({
            "event":    "sensor_threshold",
            "farm_id":  1,
            "house_id": 1,
            "sensor":   "tprt",
            "value":    16.0,
            "threshold": 15.0,
            "direction": "low",
        })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "AGENT_EVENT_COOLDOWN_SEC", 0), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            M._handle_event(payload)
            M._handle_event(payload)
        assert mock_trig.call_count == 2, "쿨다운 0초 — 두 번 모두 trigger 실행"

    def test_db_no_insert_event_handled(self, M):
        """db_no_insert 합성 이벤트 — trigger 호출 확인"""
        payload = json.dumps({
            "event":    "db_no_insert",
            "farm_id":  1,
            "house_id": 2,
            "minutes":  7,
        })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            M._handle_event(payload)
        mock_trig.assert_called_once_with(farm_id=1, house_id=2, event_type="db_no_insert")


# ────────────────────────────────────────────────────────────────────
# _trigger_subscriptions — DB UPDATE 인자 + 반환값 검증
# ────────────────────────────────────────────────────────────────────
class TestTriggerSubscriptions:
    def _make_mock_conn(self, rowcount=2):
        """mock 커넥션 구조 생성 헬퍼."""
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.rowcount = rowcount
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        return mock_conn, mock_cur

    def test_returns_updated_count_with_house(self, M):
        """house_id 있을 때 — _trigger_subscriptions 호출 + int 반환"""
        mock_conn, mock_cur = self._make_mock_conn(rowcount=3)
        # _trigger_subscriptions 내부 lazy import 를 우회 — connection module mock
        import agri_ai_core.src.control.agent_event_listener as mod
        fake_db_mod = MagicMock()
        fake_db_mod.db._getconn.return_value = mock_conn
        with patch.dict("sys.modules",
                        {"agri_ai_core.src.postgresql.connection": fake_db_mod}):
            result = mod._trigger_subscriptions(
                farm_id=1, house_id=2, event_type="sensor_threshold"
            )
        assert isinstance(result, int)
        assert result >= 0

    def test_returns_zero_on_db_failure(self, M):
        """DB 획득 실패 시 0 반환"""
        import agri_ai_core.src.control.agent_event_listener as mod
        fake_db_mod = MagicMock()
        fake_db_mod.db._getconn.return_value = None
        with patch.dict("sys.modules",
                        {"agri_ai_core.src.postgresql.connection": fake_db_mod}):
            result = mod._trigger_subscriptions(
                farm_id=1, house_id=None, event_type="llm_keep_streak"
            )
        assert result == 0

    def test_no_house_id_uses_farm_only_query(self, M):
        """house_id=None 이면 farm_id 단독 조건으로 UPDATE"""
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        fake_db_mod = MagicMock()
        fake_db_mod.db._getconn.return_value = mock_conn

        import agri_ai_core.src.control.agent_event_listener as mod
        with patch.dict("sys.modules",
                        {"agri_ai_core.src.postgresql.connection": fake_db_mod}):
            result = mod._trigger_subscriptions(
                farm_id=1, house_id=None, event_type="db_no_insert"
            )
        # execute 호출 SQL 에 house_id 조건 없어야 함
        executed_sql = mock_cur.execute.call_args[0][0]
        assert "house_id" not in executed_sql.lower()


# ────────────────────────────────────────────────────────────────────
# _run_heartbeat_check — DB 단절 감지 + 합성 이벤트 주입
# ────────────────────────────────────────────────────────────────────
class TestHeartbeatCheck:
    def test_no_gap_no_event(self, M):
        """최신 INSERT 가 30초 전 — 이벤트 주입 안 함"""
        from datetime import datetime, timedelta
        recent_ts = datetime.now() - timedelta(seconds=30)

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = [(1, recent_ts)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        fake_db_mod = MagicMock()
        fake_db_mod.db._getconn.return_value = mock_conn

        import agri_ai_core.src.control.agent_event_listener as mod
        with patch.object(mod, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(mod, "AGENT_EVENT_HEARTBEAT_SEC", 300), \
             patch.dict("sys.modules",
                        {"agri_ai_core.src.postgresql.connection": fake_db_mod}), \
             patch.object(mod, "_handle_event") as mock_he:
            mod._run_heartbeat_check()
        mock_he.assert_not_called()

    def test_gap_exceeds_threshold_injects_event(self, M):
        """최신 INSERT 가 10분 전 — db_no_insert 이벤트 주입"""
        from datetime import datetime, timedelta
        old_ts = datetime.now() - timedelta(minutes=10)

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = [(2, old_ts)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        fake_db_mod = MagicMock()
        fake_db_mod.db._getconn.return_value = mock_conn

        import agri_ai_core.src.control.agent_event_listener as mod
        with patch.object(mod, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(mod, "AGENT_EVENT_HEARTBEAT_SEC", 300), \
             patch.dict("sys.modules",
                        {"agri_ai_core.src.postgresql.connection": fake_db_mod}), \
             patch.object(mod, "_handle_event") as mock_he:
            mod._run_heartbeat_check()
        mock_he.assert_called_once()
        injected = json.loads(mock_he.call_args[0][0])
        assert injected["event"] == "db_no_insert"
        assert injected["farm_id"] == 1
        assert injected["house_id"] == 2
        assert injected["minutes"] >= 10

    def test_null_last_ts_skipped(self, M):
        """last_ts = None 인 호기 — 이벤트 주입 안 함"""
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = [(1, None)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        fake_db_mod = MagicMock()
        fake_db_mod.db._getconn.return_value = mock_conn

        import agri_ai_core.src.control.agent_event_listener as mod
        with patch.object(mod, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(mod, "AGENT_EVENT_HEARTBEAT_SEC", 300), \
             patch.dict("sys.modules",
                        {"agri_ai_core.src.postgresql.connection": fake_db_mod}), \
             patch.object(mod, "_handle_event") as mock_he:
            mod._run_heartbeat_check()
        mock_he.assert_not_called()


# ────────────────────────────────────────────────────────────────────
# 쿨다운 키 독립성 — farm/house 다르면 별도 카운트
# ────────────────────────────────────────────────────────────────────
class TestCooldownIsolation:
    def test_different_house_not_suppressed(self, M):
        """house_id 다른 동일 이벤트는 각자 독립 쿨다운"""
        def make_payload(house_id):
            return json.dumps({
                "event":     "sensor_threshold",
                "farm_id":   1,
                "house_id":  house_id,
                "sensor":    "tprt",
                "value":     16.0,
                "threshold": 15.0,
                "direction": "low",
            })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "AGENT_EVENT_COOLDOWN_SEC", 9999), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            M._handle_event(make_payload(1))
            M._handle_event(make_payload(2))  # 다른 house — 억제 안 됨
        assert mock_trig.call_count == 2

    def test_different_event_type_not_suppressed(self, M):
        """동일 farm/house 라도 event 유형이 다르면 별도 쿨다운"""
        farm_house = {"farm_id": 1, "house_id": 1}
        p1 = json.dumps({**farm_house, "event": "sensor_threshold",
                         "sensor": "tprt", "value": 16.0, "threshold": 15.0, "direction": "low"})
        p2 = json.dumps({**farm_house, "event": "llm_keep_streak", "streak": 5})
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1]), \
             patch.object(M, "AGENT_EVENT_COOLDOWN_SEC", 9999), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            M._handle_event(p1)
            M._handle_event(p2)
        assert mock_trig.call_count == 2

    def test_same_farm_different_farm_id(self, M):
        """farm_id 다른 이벤트는 억제 안 됨"""
        def make_payload(farm_id):
            return json.dumps({
                "event":     "llm_keep_streak",
                "farm_id":   farm_id,
                "house_id":  1,
                "streak":    5,
            })
        with patch.object(M, "AGENT_EVENT_FARM_IDS", [1, 2]), \
             patch.object(M, "AGENT_EVENT_COOLDOWN_SEC", 9999), \
             patch.object(M, "_trigger_subscriptions", return_value=1) as mock_trig:
            M._handle_event(make_payload(1))
            M._handle_event(make_payload(2))
        assert mock_trig.call_count == 2


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
