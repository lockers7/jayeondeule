# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 단위테스트 — farm_cache 시작로드 캐시 제거 검증.
#
# 검증:
#   1) get_farm_name 매 호출마다 DB 조회 (시작 1회 로드 X)
#   2) DB 결과 변경 시 즉시 반영 (새 농장 추가 즉시 보임)
#   3) DB 실패 시 fallback 캐시 사용
#   4) get_house_name 매 호출 DB
#   5) get_house_name DB 실패 시 'N호재배사' 폴백
#   6) get_farm_id_by_name 역방향 조회
#   7) get_all_farm_names 매 호출 DB
# ═══════════════════════════════════════════════════════════════════════════
from unittest.mock import MagicMock

import pytest

import agri_ai_core.src.ai.farm_cache as fc


@pytest.fixture(autouse=True)
def reset_caches():
    fc._farm_name_cache.clear()
    fc._house_name_cache.clear()
    yield
    fc._farm_name_cache.clear()
    fc._house_name_cache.clear()


# ════════════════════════════════════════════════════════════════════
# 1) get_farm_name 매 호출 DB
# ════════════════════════════════════════════════════════════════════
def test_get_farm_name_calls_db_each_time(monkeypatch):
    db_calls = {'count': 0}
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)

    def _fetch(*a, **k):
        db_calls['count'] += 1
        return [{'farm_id': 1, 'farm_name': '자연들에'}]
    db_mock.fetch_all = _fetch

    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    fc.get_farm_name(1)
    fc.get_farm_name(1)
    fc.get_farm_name(1)
    assert db_calls['count'] == 3, "캐시가 살아있음 — DB 조회 횟수 부족"


# ════════════════════════════════════════════════════════════════════
# 2) DB 결과 변경 시 즉시 반영
# ════════════════════════════════════════════════════════════════════
def test_get_farm_name_reflects_db_change(monkeypatch):
    state = {'rows': [{'farm_id': 1, 'farm_name': 'A'}]}
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_all = lambda *a, **k: state['rows']

    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    assert fc.get_farm_name(1) == 'A'
    state['rows'] = [{'farm_id': 1, 'farm_name': 'A2'}, {'farm_id': 2, 'farm_name': 'B'}]
    assert fc.get_farm_name(1) == 'A2'
    assert fc.get_farm_name(2) == 'B'


# ════════════════════════════════════════════════════════════════════
# 3) DB 실패 시 fallback 캐시
# ════════════════════════════════════════════════════════════════════
def test_get_farm_name_db_failure_uses_fallback(monkeypatch):
    state = {'mode': 'ok'}
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)

    def _fetch(*a, **k):
        if state['mode'] == 'fail':
            raise RuntimeError("DB down")
        return [{'farm_id': 1, 'farm_name': '자연들에'}]
    db_mock.fetch_all = _fetch

    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    # 1차: 정상 조회 → fallback 캐시 채워짐
    assert fc.get_farm_name(1) == '자연들에'
    # 2차: DB 실패 → fallback 캐시 사용
    state['mode'] = 'fail'
    assert fc.get_farm_name(1) == '자연들에'


# ════════════════════════════════════════════════════════════════════
# 4) get_house_name 매 호출 DB
# ════════════════════════════════════════════════════════════════════
def test_get_house_name_calls_db_each_time(monkeypatch):
    db_calls = {'count': 0}
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)

    def _fetch(*a, **k):
        db_calls['count'] += 1
        return [{'farm_id': 1, 'hous_id': 1, 'hous_name': '상황버섯1호재배사'}]
    db_mock.fetch_all = _fetch

    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    fc.get_house_name(1, 1)
    fc.get_house_name(1, 1)
    assert db_calls['count'] == 2


# ════════════════════════════════════════════════════════════════════
# 5) get_house_name DB 실패 + fallback 미존재 → N호재배사
# ════════════════════════════════════════════════════════════════════
def test_get_house_name_db_failure_no_fallback(monkeypatch):
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_all = MagicMock(side_effect=RuntimeError("DB down"))

    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    name = fc.get_house_name(1, 7)
    assert name == '7호재배사'


# ════════════════════════════════════════════════════════════════════
# 6) get_farm_id_by_name 역방향
# ════════════════════════════════════════════════════════════════════
def test_get_farm_id_by_name(monkeypatch):
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_all = lambda *a, **k: [
        {'farm_id': 1, 'farm_name': 'A'},
        {'farm_id': 2, 'farm_name': 'B'},
    ]
    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    assert fc.get_farm_id_by_name('B') == '2'
    assert fc.get_farm_id_by_name('NOPE') is None


# ════════════════════════════════════════════════════════════════════
# 7) get_all_farm_names 매 호출 DB + 사본 반환
# ════════════════════════════════════════════════════════════════════
def test_get_all_farm_names(monkeypatch):
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_all = lambda *a, **k: [{'farm_id': 1, 'farm_name': 'A'}]
    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    d = fc.get_all_farm_names()
    assert d == {'1': 'A'}
    # 사본 반환 — caller 가 변경해도 내부 캐시 영향 없음
    d['1'] = 'MUTATED'
    d2 = fc.get_all_farm_names()
    assert d2['1'] == 'A'


# ════════════════════════════════════════════════════════════════════
# 8) is_cache_loaded — 1회 이상 성공 조회 후 True
# ════════════════════════════════════════════════════════════════════
def test_is_cache_loaded_after_first_success(monkeypatch):
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.fetch_all = lambda *a, **k: [{'farm_id': 1, 'farm_name': 'A'}]
    monkeypatch.setattr('agri_ai_core.src.postgresql.connection.db_session', lambda: db_mock)

    assert not fc.is_cache_loaded()
    fc.get_farm_name(1)
    assert fc.is_cache_loaded()
