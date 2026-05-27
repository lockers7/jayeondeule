# ══════════════════════════════════════════════════════════════════════════════
# db_read_query 자가교정(스키마 힌트) 회귀 테스트
# 배경(2026-07-19): 채팅 "3호 배수OFF 포그ON 이유?" 질문에서 LLM 이 ai_decision_log
#   에 없는 device_name 컬럼으로 SQL 을 만들어 실패 → 사유를 못 가져와 회피성 답변.
#   보완: 컬럼/테이블/타입 오류 시 실제 스키마를 에러에 실어 LLM 이 다음 라운드에
#   정확히 재조회하도록 자가교정 유도.
# DB 필요 — 연결 불가 환경에선 skip.
# ══════════════════════════════════════════════════════════════════════════════
import pytest
from dotenv import load_dotenv
load_dotenv("/workspace/jayeondeule/.env")
from agri_ai_core.src.ai.tools_db import db_read_query


def _needs_db():
    r = db_read_query("SELECT 1 AS x", auth_farm_id=None)
    if not r.get("success"):
        pytest.skip("DB 연결 불가 — self-heal 테스트 skip")


def test_undefined_column_returns_real_columns():
    _needs_db()
    r = db_read_query(
        "SELECT reason FROM ai_decision_log WHERE farm_id=1 AND device_name='x'",
        auth_farm_id=None)
    assert r["success"] is False
    # 실제 컬럼들이 힌트로 실려야 한다
    assert "fog_occurs" in r["error"]
    assert "drainage_motor" in r["error"]
    assert "reason" in r["error"]


def test_undefined_table_returns_table_list():
    _needs_db()
    r = db_read_query("SELECT * FROM ai_decisionlog WHERE farm_id=1", auth_farm_id=None)
    assert r["success"] is False
    assert "사용 가능한 테이블" in r["error"]


def test_type_mismatch_join_returns_cast_hint():
    _needs_db()
    r = db_read_query(
        "SELECT a.reason FROM ai_decision_log a "
        "JOIN ai_conversation c ON a.farm_id = c.farm_id", auth_farm_id=None)
    assert r["success"] is False
    assert "형변환" in r["error"]


def test_valid_query_unaffected():
    _needs_db()
    r = db_read_query(
        "SELECT house_id, reason FROM ai_decision_log "
        "WHERE farm_id=1 ORDER BY decided_at DESC", limit=2, auth_farm_id=None)
    assert r["success"] is True
