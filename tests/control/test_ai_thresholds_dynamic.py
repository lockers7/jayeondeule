# ═══════════════════════════════════════════════════════════════════════════
# 단위테스트 — ai_thresholds 캐시 updt_dttm invalidate 정책 검증.
#
# 검증:
#   1) 첫 호출 시 DB 조회 + 캐시에 (updt_dttm, ts) 저장
#   2) updt_dttm 동일하면 두 번째 호출은 캐시 hit (DB 재조회 skip)
#   3) updt_dttm 변경 시 다음 호출에서 자동 invalidate + 재로드
#   4) DB 조회 실패 시 기존 캐시 fallback
#   5) DB 조회 실패 + 캐시 없음 → last_resort 폴백
#   6) farm/house None → global_default 즉시 반환
#
# DB·reader 를 monkeypatch 로 격리해 캐시 동작만 검증.
# ═══════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

import agri_ai_core.src.control.ai_thresholds as th


@pytest.fixture(autouse=True)
def reset_cache():
    th.clear_cache()
    yield
    th.clear_cache()


# 가짜 SENSOR_M_SETTING row (한국어 alias 컬럼명)
def _fake_row(temp_low=25.0, temp_high=28.0):
    return {
        '저장일자': datetime(2026, 5, 9, 14, 0, 0),
        '온도최저': temp_low, '온도적정': 26.0, '온도최고': temp_high,
        '온도비상최저': 20.0, '온도비상최고': 32.0,
        '습도최저': 70.0, '습도최고': 95.0,
        '습도비상최저': 50.0, '습도비상최고': 100.0,
        'co2최저': 100.0, 'co2최고': 2000.0, 'co2비상최고': 3000.0,
        '수온최저': 20.0, '수온최고': 40.0,
        '수온비상최저': 15.0, '수온비상최고': 45.0,
        '발이기최저': 27.0, '발이기최고': 33.0,
    }


# ════════════════════════════════════════════════════════════════════
# 1) 첫 호출 — DB 1회 + 캐시 저장
# ════════════════════════════════════════════════════════════════════
def test_first_call_loads_from_db(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_one = MagicMock(return_value=_fake_row(temp_low=25.0))

    monkeypatch.setattr(th, 'db_session', lambda: db_mock)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_sensor_setting_max_updt',
        lambda f, h: t1)

    ts = th.get_thresholds(1, 1)
    assert ts.temp_low == 25.0
    assert (1, 1) in th._CACHE
    assert th._CACHE[(1, 1)][0] == t1


# ════════════════════════════════════════════════════════════════════
# 2) updt_dttm 동일 → 캐시 hit, DB fetch_one 추가 호출 X
# ════════════════════════════════════════════════════════════════════
def test_cache_hit_skips_db(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    fetch_calls = {'count': 0}
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)

    def _fetch(*a, **k):
        fetch_calls['count'] += 1
        return _fake_row()
    db_mock.fetch_one = _fetch

    monkeypatch.setattr(th, 'db_session', lambda: db_mock)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_sensor_setting_max_updt',
        lambda f, h: t1)

    th.get_thresholds(1, 1)   # 1차: DB 조회
    assert fetch_calls['count'] == 1
    th.get_thresholds(1, 1)   # 2차: 캐시 hit
    assert fetch_calls['count'] == 1, "updt_dttm 동일인데 DB 재조회 발생"
    th.get_thresholds(1, 1)   # 3차: 또 캐시 hit
    assert fetch_calls['count'] == 1


# ════════════════════════════════════════════════════════════════════
# 3) updt_dttm 변경 → 즉시 invalidate + 재로드
# ════════════════════════════════════════════════════════════════════
def test_cache_invalidates_on_updt_change(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    t2 = t1 + timedelta(seconds=10)
    state = {'updt': t1, 'temp': 25.0}

    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_one = lambda *a, **k: _fake_row(temp_low=state['temp'])

    monkeypatch.setattr(th, 'db_session', lambda: db_mock)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_sensor_setting_max_updt',
        lambda f, h: state['updt'])

    ts1 = th.get_thresholds(1, 1)
    assert ts1.temp_low == 25.0

    # 사용자가 web UI 에서 임계값 변경 시뮬레이션
    state['updt'] = t2
    state['temp'] = 27.5

    ts2 = th.get_thresholds(1, 1)
    assert ts2.temp_low == 27.5, "updt_dttm 변경됐는데 캐시가 invalidate 안 됨"
    assert th._CACHE[(1, 1)][0] == t2


# ════════════════════════════════════════════════════════════════════
# 4) DB 조회 실패 — 기존 캐시 fallback
# ════════════════════════════════════════════════════════════════════
def test_db_failure_returns_cached(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)

    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_one = MagicMock(return_value=_fake_row(temp_low=25.0))

    monkeypatch.setattr(th, 'db_session', lambda: db_mock)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_sensor_setting_max_updt',
        lambda f, h: t1)

    ts1 = th.get_thresholds(1, 1)
    assert ts1.temp_low == 25.0

    # 다음 호출에서 DB fetch_one 이 예외 — 그러나 캐시 hit 으로 보호되도록
    # 조건: updt_dttm 가 변경된 상태 + DB 실패
    t2 = t1 + timedelta(seconds=10)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_sensor_setting_max_updt',
        lambda f, h: t2)
    db_mock.fetch_one = MagicMock(side_effect=RuntimeError("DB down"))

    ts2 = th.get_thresholds(1, 1)
    assert ts2 is ts1, "DB 실패 시 캐시 fallback 안 됨"


# ════════════════════════════════════════════════════════════════════
# 5) DB 조회 실패 + 캐시 없음 → last_resort
# ════════════════════════════════════════════════════════════════════
def test_db_failure_no_cache_falls_back(monkeypatch):
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_one = MagicMock(side_effect=RuntimeError("DB down"))

    monkeypatch.setattr(th, 'db_session', lambda: db_mock)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_sensor_setting_max_updt',
        lambda f, h: None)

    ts = th.get_thresholds(1, 1)
    assert ts.source == 'last_resort'


# ════════════════════════════════════════════════════════════════════
# 6) farm/house None → global_default 즉시 반환 (DB 호출 X)
# ════════════════════════════════════════════════════════════════════
def test_none_returns_global_default(monkeypatch):
    db_mock = MagicMock()
    db_mock.fetch_one = MagicMock(side_effect=AssertionError("DB 호출되면 안 됨"))
    monkeypatch.setattr(th, 'db_session', lambda: db_mock)

    ts = th.get_thresholds(None, None)
    assert ts.source == 'last_resort'
    assert (None, None) not in th._CACHE
