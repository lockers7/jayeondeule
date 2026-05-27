# ══════════════════════════════════════════════════════════════════════════════
# control_prompt_m 단위 테스트 — get_control_block() 캐시 + placeholder 검증
#
# 검증:
#   1) DB 정상 조회 — CTRL_ROLE block_id 존재 확인
#   2) get_control_block() 첫 호출 — DB 로드 + 캐시 저장
#   3) updt_dttm 동일 → 캐시 hit, _load_control_block_from_db 호출 X
#   4) updt_dttm 변경 → 즉시 invalidate + 재로드
#   5) placeholder ${KEY} 치환 정상
#   6) active_yn='N' block → None 반환
#   7) 실 DB 에서 CTRL_ROLE 조회 성공 (integration)
#   8) ai_control._build_system_prompt() — DB block 조립 결과에 CTRL_SEC1 포함 여부
#   9) ai_control._build_user_prompt() — DB 라벨/메시지 포함 여부
# ══════════════════════════════════════════════════════════════════════════════
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import agri_ai_core.src.prompt_registry as pr


@pytest.fixture(autouse=True)
def reset_cache():
    pr.clear_cache()
    yield
    pr.clear_cache()


# ════════════════════════════════════════════════════════════════════
# 1) DB 직접 — 제어에 실제 사용되는 필수 블록이 모두 존재하는지 확인.
#    (매직넘버 카운트 대신 사용 블록 ID 기준 — 미사용 블록 정리에 견고)
# ════════════════════════════════════════════════════════════════════
_REQUIRED_BLOCKS = [
    # 시스템 프롬프트 뼈대 (_build_system_prompt) — 2026-07-19 단순화:
    # 결정트리 §2~§5·§7·§8 은 CTRL_GUIDE 로 대체됨.
    "CTRL_ROLE", "CTRL_SEC1", "CTRL_SEC_SEASON", "CTRL_GUIDE",
    "CTRL_SEC6", "CTRL_SEC9",
    # Agent 시스템 프롬프트
    "CTRL_AGENT_SYSTEM",
    # 유저 프롬프트 (_build_user_prompt — 절대 룰 현재 상태)
    "CTRL_USER_LABEL_RULE_STATE", "CTRL_USER_MSG_RELAY_STATUS",
    "CTRL_USER_MSG_RULE1_BOTH_ON", "CTRL_USER_MSG_RULE1_HEATER",
    "CTRL_USER_MSG_RULE1_DRAIN", "CTRL_USER_MSG_RULE1_BOTH_OFF",
    "CTRL_USER_MSG_RULE2_VIOLATION",
]


def test_control_prompt_required_blocks_present():
    from agri_ai_core.src.postgresql.connection import db
    conn = db._getconn()
    assert conn is not None, "DB 연결 실패"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT block_id FROM control_prompt_m WHERE active_yn='Y'")
            active = {r[0] for r in cur.fetchall()}
    finally:
        db._putconn(conn)
    missing = [b for b in _REQUIRED_BLOCKS if b not in active]
    assert not missing, f"제어 필수 블록 누락: {missing}"


# ════════════════════════════════════════════════════════════════════
# 2) get_control_block() 첫 호출 — DB 로드 + 캐시 저장 (mock)
# ════════════════════════════════════════════════════════════════════
def test_ctrl_block_first_call_loads(monkeypatch):
    t1 = datetime(2026, 6, 1, 12, 0, 0)
    monkeypatch.setattr(pr, '_load_control_block_from_db', lambda b: 'BODY-CTRL')
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_control_prompt_updt',
        lambda b: t1,
    )
    body = pr.get_control_block('CTRL_TEST_A')
    assert body == 'BODY-CTRL'
    assert pr._CTRL_BLOCK_CACHE['CTRL_TEST_A']['updt_dttm'] == t1
    assert pr._CTRL_BLOCK_CACHE['CTRL_TEST_A']['value'] == 'BODY-CTRL'


# ════════════════════════════════════════════════════════════════════
# 3) updt_dttm 동일 → 캐시 hit, DB 재호출 없음
# ════════════════════════════════════════════════════════════════════
def test_ctrl_block_cache_hit_skips_db(monkeypatch):
    t1 = datetime(2026, 6, 1, 12, 0, 0)
    call_count = {'n': 0}

    def fake_load(b):
        call_count['n'] += 1
        return 'BODY-CTRL'

    monkeypatch.setattr(pr, '_load_control_block_from_db', fake_load)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_control_prompt_updt',
        lambda b: t1,
    )
    pr.get_control_block('CTRL_TEST_B')
    pr.get_control_block('CTRL_TEST_B')
    assert call_count['n'] == 1, "캐시 hit 실패 — DB를 2회 호출함"


# ════════════════════════════════════════════════════════════════════
# 4) updt_dttm 변경 → 즉시 invalidate + 재로드
# ════════════════════════════════════════════════════════════════════
def test_ctrl_block_invalidate_on_updt_change(monkeypatch):
    t1 = datetime(2026, 6, 1, 12, 0, 0)
    t2 = t1 + timedelta(seconds=1)
    times = [t1, t2]
    call_count = {'n': 0}

    def fake_updt(b):
        return times.pop(0) if times else t2

    def fake_load(b):
        call_count['n'] += 1
        return f'BODY-v{call_count["n"]}'

    monkeypatch.setattr(pr, '_load_control_block_from_db', fake_load)
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_control_prompt_updt',
        fake_updt,
    )
    body1 = pr.get_control_block('CTRL_TEST_C')
    body2 = pr.get_control_block('CTRL_TEST_C')
    assert body1 == 'BODY-v1'
    assert body2 == 'BODY-v2'
    assert call_count['n'] == 2


# ════════════════════════════════════════════════════════════════════
# 5) placeholder ${KEY} 치환 정상
# ════════════════════════════════════════════════════════════════════
def test_ctrl_block_placeholder_substitution(monkeypatch):
    t1 = datetime(2026, 6, 1, 12, 0, 0)
    monkeypatch.setattr(pr, '_load_control_block_from_db',
                        lambda b: '온도하한=${TEMP_LOW}, 상한=${TEMP_HIGH}')
    monkeypatch.setattr(
        'agri_ai_core.src.postgresql.reader.read_control_prompt_updt',
        lambda b: t1,
    )
    result = pr.get_control_block('CTRL_TEST_PH', TEMP_LOW='15', TEMP_HIGH='30')
    assert '온도하한=15' in result
    assert '상한=30' in result
    assert '${TEMP_LOW}' not in result


# ════════════════════════════════════════════════════════════════════
# 6) 실 DB — CTRL_ROLE 조회 성공 (body_text 비어 있지 않음)
# ════════════════════════════════════════════════════════════════════
def test_ctrl_role_real_db_load():
    body = pr.get_control_block('CTRL_ROLE')
    assert body, "CTRL_ROLE DB 조회 결과가 None/빈값"
    assert len(body) > 20, f"CTRL_ROLE body_text 너무 짧음: '{body[:50]}'"


# ════════════════════════════════════════════════════════════════════
# 7) 실 DB — CTRL_SEC1 조회 성공
# ════════════════════════════════════════════════════════════════════
def test_ctrl_sec1_real_db_load():
    body = pr.get_control_block('CTRL_SEC1')
    assert body, "CTRL_SEC1 DB 조회 결과가 None/빈값"


# ════════════════════════════════════════════════════════════════════
# 8) ai_control._build_system_prompt() — DB 기반 섹션 포함 여부
# ════════════════════════════════════════════════════════════════════
def test_build_system_prompt_uses_db():
    from agri_ai_core.src.control.ai_control import _build_system_prompt
    prompt = _build_system_prompt("생육기")
    assert prompt, "system_prompt DB 조회 결과 없음"
    assert len(prompt) > 200, f"system_prompt 너무 짧음 — DB block 조회 실패 의심"


# ════════════════════════════════════════════════════════════════════
# 9) ai_control._build_user_prompt() — DB 라벨/메시지 포함 여부
# ════════════════════════════════════════════════════════════════════
def test_build_user_prompt_uses_db():
    from agri_ai_core.src.control.ai_control import _build_user_prompt
    from agri_ai_core.src.control.control_common import get_pin_map

    pin_map = get_pin_map(2)
    current_relay = {
        pin_map["water_heater_flag"]: True,
        pin_map["fog_occurs_flag"]: False,
        pin_map["drainage_motor_flag"]: False,
    }
    prompt = _build_user_prompt(
        {
            "indoor_temperature": 22.0,
            "indoor_humidity": 75.0,
            "co2": 800,
            "outdoor_temperature": 12.0,
            "outdoor_humidity": 65.0,
            "water_temperature": 24.0,
        },
        current_relay, "생육기", {}, "", 2,
    )
    assert prompt, "_build_user_prompt 반환값 없음"
    # relay 상태 섹션 (CTRL_USER_MSG_RELAY_STATUS 또는 fallback)
    assert "water_heater_flag" in prompt, "릴레이 상태 누락"
    # 룰 상태 라벨 (CTRL_USER_LABEL_RULE_STATE 또는 fallback)
    assert len(prompt) > 100, "user_prompt 너무 짧음 — DB block 조회 실패 의심"


# ════════════════════════════════════════════════════════════════════
# 10) ai_monitor_agent.build_system_prompt() — DB 조회 성공
# ════════════════════════════════════════════════════════════════════
def test_monitor_agent_system_prompt_uses_db():
    from agri_ai_core.src.control.ai_monitor_agent import build_system_prompt
    prompt = build_system_prompt(max_steps=5)
    assert prompt, "CTRL_AGENT_SYSTEM DB 조회 실패"
    assert len(prompt) > 100, "agent system_prompt 너무 짧음"
