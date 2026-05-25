# ═══════════════════════════════════════════════════════════════════════════
# Phase 5 단위테스트 — setting_listener (PostgreSQL LISTEN/NOTIFY).
#
# 검증:
#   1) register_callback 으로 등록한 함수가 _handle_notification 에서 호출됨
#   2) 등록되지 않은 table 의 notification 은 silent skip
#   3) payload JSON 디코드 실패 시 silent skip
#   4) 한 callback 의 예외가 다른 callback / loop 에 영향 없음
#   5) 같은 callback 중복 등록 안 됨 (idempotent)
#   6) clear_callbacks 로 모두 제거
#   7) start/stop 동작 — daemon thread 시작·종료
# ═══════════════════════════════════════════════════════════════════════════
import json
import threading
from unittest.mock import MagicMock

import pytest

import agri_ai_core.src.control.setting_listener as sl


@pytest.fixture(autouse=True)
def reset_state():
    sl.clear_callbacks()
    sl._thread = None
    sl._stop_event = None
    yield
    sl.clear_callbacks()
    if sl._thread and sl._thread.is_alive():
        sl.stop(timeout=2)


# ════════════════════════════════════════════════════════════════════
# 1) callback 등록 + dispatch 정상
# ════════════════════════════════════════════════════════════════════
def test_register_callback_dispatches():
    cb = MagicMock()
    sl.register_callback('sensor_m_setting', cb)

    payload = json.dumps({'table': 'sensor_m_setting', 'op': 'UPDATE', 'ts': 0.0})
    sl._handle_notification(payload)

    cb.assert_called_once()


# ════════════════════════════════════════════════════════════════════
# 2) 등록 안 된 table 은 skip
# ════════════════════════════════════════════════════════════════════
def test_unregistered_table_skipped():
    cb = MagicMock()
    sl.register_callback('sensor_m_setting', cb)

    sl._handle_notification(
        json.dumps({'table': 'unknown_table', 'op': 'INSERT'})
    )
    cb.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# 3) 잘못된 JSON payload 는 silent (예외 누설 X)
# ════════════════════════════════════════════════════════════════════
def test_invalid_payload_silent():
    cb = MagicMock()
    sl.register_callback('sensor_m_setting', cb)

    sl._handle_notification("NOT_A_JSON")  # No raise
    sl._handle_notification("{invalid}")   # No raise
    cb.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# 4) callback 예외가 다른 callback 영향 X
# ════════════════════════════════════════════════════════════════════
def test_callback_exception_isolated():
    bad = MagicMock(side_effect=RuntimeError("boom"))
    good = MagicMock()
    sl.register_callback('sensor_m_setting', bad)
    sl.register_callback('sensor_m_setting', good)

    sl._handle_notification(
        json.dumps({'table': 'sensor_m_setting', 'op': 'UPDATE'})
    )
    bad.assert_called_once()
    good.assert_called_once()


# ════════════════════════════════════════════════════════════════════
# 5) 동일 callback 중복 등록 안 됨 (idempotent)
# ════════════════════════════════════════════════════════════════════
def test_register_callback_idempotent():
    cb = MagicMock()
    sl.register_callback('sensor_m_setting', cb)
    sl.register_callback('sensor_m_setting', cb)
    sl.register_callback('sensor_m_setting', cb)

    sl._handle_notification(
        json.dumps({'table': 'sensor_m_setting', 'op': 'UPDATE'})
    )
    assert cb.call_count == 1, "동일 callback 중복 등록되어 다중 호출"


# ════════════════════════════════════════════════════════════════════
# 6) clear_callbacks
# ════════════════════════════════════════════════════════════════════
def test_clear_callbacks():
    cb = MagicMock()
    sl.register_callback('sensor_m_setting', cb)
    sl.clear_callbacks()
    sl._handle_notification(
        json.dumps({'table': 'sensor_m_setting', 'op': 'UPDATE'})
    )
    cb.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# 7) start/stop — DB 연결 mock 으로 thread lifecycle 만 검증
# ════════════════════════════════════════════════════════════════════
def test_start_stop_lifecycle(monkeypatch):
    """실제 DB 연결 없이 _listen_loop 의 lifecycle 만 검증.
    _open_listen_connection 을 mock 해서 select 통과 후 stop 응답."""
    fake_conn = MagicMock()
    fake_conn.notifies = []
    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_conn.cursor = MagicMock(return_value=fake_cursor)

    monkeypatch.setattr(sl, '_open_listen_connection', lambda: fake_conn)
    # select 가 빈 결과 반환 → 5초 timeout 흉내
    monkeypatch.setattr(sl.select, 'select', lambda *a, **k: ([], [], []))

    assert not sl.is_running()
    sl.start()
    # thread 가 시작될 시간 약간
    started = False
    for _ in range(20):
        if sl.is_running():
            started = True
            break
        threading.Event().wait(0.05)
    assert started, "start() 후 thread 가 가동되지 않음"

    sl.stop(timeout=3)
    assert not sl.is_running()


# ════════════════════════════════════════════════════════════════════
# 8) start 두 번 호출 — idempotent
# ════════════════════════════════════════════════════════════════════
def test_start_idempotent(monkeypatch):
    fake_conn = MagicMock()
    fake_conn.notifies = []
    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_conn.cursor = MagicMock(return_value=fake_cursor)
    monkeypatch.setattr(sl, '_open_listen_connection', lambda: fake_conn)
    monkeypatch.setattr(sl.select, 'select', lambda *a, **k: ([], [], []))

    sl.start()
    t1 = sl._thread
    sl.start()  # 다시 호출 — 동일 thread 유지
    t2 = sl._thread
    assert t1 is t2, "start() 두 번 호출 시 thread 가 새로 생성됨"
    sl.stop(timeout=3)


# ════════════════════════════════════════════════════════════════════
# 9) 기본 callback (sensor_m_setting → ai_thresholds.clear_cache) 통합 동작
# ════════════════════════════════════════════════════════════════════
def test_default_callback_invalidates_thresholds(monkeypatch):
    """start() 의 _register_default_callbacks 가 등록한 callback 동작."""
    from agri_ai_core.src.control import ai_thresholds

    cleared = {'count': 0}
    monkeypatch.setattr(ai_thresholds, 'clear_cache',
                        lambda: cleared.update(count=cleared['count'] + 1))

    sl._register_default_callbacks()
    sl._handle_notification(
        json.dumps({'table': 'sensor_m_setting', 'op': 'UPDATE'})
    )
    assert cleared['count'] == 1
