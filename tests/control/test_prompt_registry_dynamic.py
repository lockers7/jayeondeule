# ═══════════════════════════════════════════════════════════════════════════
# Phase 3-b 단위테스트 — prompt_registry 캐시 invalidate 정책 변경.
#
# 검증 (block):
#   1) 첫 호출 — DB 로드 + 캐시 저장
#   2) updt_dttm 동일 → 캐시 hit, _load_block_from_db 호출 X
#   3) updt_dttm 변경 → 즉시 invalidate + 재로드
#   4) DB 로드 실패 + 기존 캐시 있음 → 캐시 fallback
#   5) placeholder 치환 정상
#
# 검증 (tools):
#   6) 첫 호출 — DB 로드 + 캐시 저장
#   7) updt_dttm 동일 → 캐시 hit
#   8) updt_dttm 변경 → 즉시 재로드
# ═══════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

import agri_ai_core.src.prompt_registry as pr


@pytest.fixture(autouse=True)
def reset_cache():
    pr.clear_cache()
    yield
    pr.clear_cache()


# ════════════════════════════════════════════════════════════════════
# get_block — 1) 첫 호출 DB 로드
# ════════════════════════════════════════════════════════════════════
def test_block_first_call_loads(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    monkeypatch.setattr(pr, '_load_block_from_db', lambda b: 'BODY-A')
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_prompt_block_updt',
        lambda b: t1)

    body = pr.get_block('BLK1')
    assert body == 'BODY-A'
    assert pr._BLOCK_CACHE['BLK1']['updt_dttm'] == t1
    assert pr._BLOCK_CACHE['BLK1']['value'] == 'BODY-A'


# ════════════════════════════════════════════════════════════════════
# get_block — 2) updt_dttm 동일이면 DB 안 부름
# ════════════════════════════════════════════════════════════════════
def test_block_cache_hit_skips_db(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    calls = {'count': 0}

    def _load(b):
        calls['count'] += 1
        return 'BODY-X'

    monkeypatch.setattr(pr, '_load_block_from_db', _load)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_prompt_block_updt',
        lambda b: t1)

    pr.get_block('BLK1')
    assert calls['count'] == 1
    pr.get_block('BLK1')   # 캐시 hit
    assert calls['count'] == 1
    pr.get_block('BLK1')   # 또 hit
    assert calls['count'] == 1


# ════════════════════════════════════════════════════════════════════
# get_block — 3) updt_dttm 변경 → 즉시 재로드
# ════════════════════════════════════════════════════════════════════
def test_block_invalidates_on_updt_change(monkeypatch):
    state = {'updt': datetime(2026, 5, 9, 14, 0, 0), 'body': 'BODY-OLD'}

    monkeypatch.setattr(pr, '_load_block_from_db', lambda b: state['body'])
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_prompt_block_updt',
        lambda b: state['updt'])

    assert pr.get_block('BLK1') == 'BODY-OLD'

    # web UI 에서 본문 변경 시뮬레이션
    state['updt'] = state['updt'] + timedelta(seconds=10)
    state['body'] = 'BODY-NEW'

    assert pr.get_block('BLK1') == 'BODY-NEW'
    assert pr._BLOCK_CACHE['BLK1']['value'] == 'BODY-NEW'


# ════════════════════════════════════════════════════════════════════
# get_block — 4) DB 로드 실패 + 기존 캐시 fallback
# ════════════════════════════════════════════════════════════════════
def test_block_db_failure_falls_back_to_cache(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)

    monkeypatch.setattr(pr, '_load_block_from_db', lambda b: 'BODY-A')
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_prompt_block_updt',
        lambda b: t1)
    pr.get_block('BLK1')   # 캐시에 BODY-A 저장

    # 다음 호출에서 DB 가 None 반환, updt_dttm 변경
    t2 = t1 + timedelta(seconds=10)
    monkeypatch.setattr(pr, '_load_block_from_db', lambda b: None)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_prompt_block_updt',
        lambda b: t2)

    body = pr.get_block('BLK1')
    assert body == 'BODY-A', "DB None 반환 시 캐시 fallback 안 됨"


# ════════════════════════════════════════════════════════════════════
# get_block — 5) placeholder 치환
# ════════════════════════════════════════════════════════════════════
def test_block_placeholder_substitution(monkeypatch):
    monkeypatch.setattr(pr, '_load_block_from_db',
                        lambda b: '안녕 ${name} 님 (호기 ${house})')
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_prompt_block_updt',
        lambda b: datetime.now())

    body = pr.get_block('BLK1', name='홍길동', house=3)
    assert body == '안녕 홍길동 님 (호기 3)'


# ════════════════════════════════════════════════════════════════════
# get_tools — 6) 첫 호출 DB 로드
# ════════════════════════════════════════════════════════════════════
def test_tools_first_call_loads(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    fake_rows = [
        {'tool_id': 'A', 'schema_json': {}, 'description': 'a', 'category': 'x', 'priority': 1},
        {'tool_id': 'B', 'schema_json': {}, 'description': 'b', 'category': 'y', 'priority': 2},
    ]
    monkeypatch.setattr(pr, '_load_tools_from_db', lambda active_only=True: fake_rows)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_tool_definition_max_updt',
        lambda: t1)

    tools = pr.get_tools()
    assert len(tools) == 2
    assert pr._TOOLS_CACHE['updt_dttm'] == t1
    # 반환은 list 복사본이라 caller 가 변경해도 캐시 안전
    tools.append('extra')
    assert len(pr._TOOLS_CACHE['value']) == 2


# ════════════════════════════════════════════════════════════════════
# get_tools — 7) updt_dttm 동일이면 DB 안 부름
# ════════════════════════════════════════════════════════════════════
def test_tools_cache_hit_skips_db(monkeypatch):
    t1 = datetime(2026, 5, 9, 14, 0, 0)
    calls = {'count': 0}

    def _load(active_only=True):
        calls['count'] += 1
        return [{'tool_id': 'A', 'schema_json': {}, 'description': '', 'category': '', 'priority': 1}]

    monkeypatch.setattr(pr, '_load_tools_from_db', _load)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_tool_definition_max_updt',
        lambda: t1)

    pr.get_tools()
    pr.get_tools()
    pr.get_tools()
    assert calls['count'] == 1


# ════════════════════════════════════════════════════════════════════
# get_tools — 8) updt_dttm 변경 → 즉시 재로드
# ════════════════════════════════════════════════════════════════════
def test_tools_invalidates_on_updt_change(monkeypatch):
    state = {'updt': datetime(2026, 5, 9, 14, 0, 0), 'count': 1}

    def _load(active_only=True):
        return [{'tool_id': f'T{i}', 'schema_json': {}, 'description': '',
                 'category': '', 'priority': i} for i in range(state['count'])]

    monkeypatch.setattr(pr, '_load_tools_from_db', _load)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_tool_definition_max_updt',
        lambda: state['updt'])

    assert len(pr.get_tools()) == 1

    # web UI 에서 새 도구 추가 시뮬레이션
    state['updt'] = state['updt'] + timedelta(seconds=10)
    state['count'] = 3

    assert len(pr.get_tools()) == 3
