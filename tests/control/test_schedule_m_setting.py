# ═══════════════════════════════════════════════════════════════════════════
# 단위테스트 — SCHEDULE_M_SETTING 테이블 + reader 함수.
#
# 검증 항목:
#   1) read_schedule_settings() 가 seed 13건 반환 + 필수 컬럼 존재
#   2) 각 task_name 이 정확한 schedule_type 으로 매핑
#   3) interval 타입은 interval_seconds NOT NULL, cron 타입은 cron_expr NOT NULL
#   4) read_schedule_max_updt() 가 timestamp 반환
#   5) UPDATE 시 updt_dttm 트리거 자동 갱신
#   6) CHECK 제약: schedule_type 과 interval_seconds/cron_expr 일관성
#
# 운영 DB(jayeondeule) 직접 사용. 테스트는 __test_* 접두사 row 만 INSERT/DELETE.
# ═══════════════════════════════════════════════════════════════════════════
import time
import pytest

from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql.reader import (
    read_schedule_settings,
    read_schedule_max_updt,
)


# 마이그레이션 seed row 13건 (001_schedule_m_setting.sql 와 1:1 매칭)
SEED_INTERVAL_TASKS = {
    'stats_job':         600,
    'relay_control_job': 5,
    'ai_control_loop':   60,
    'pg_pool_heartbeat': 300,
}

SEED_CRON_TASKS = {
    'learning_job':            '0 4 * * *',
    'growth_rag_job_noon':     '0 12 * * *',
    'growth_rag_job_midnight': '5 0 * * *',
    'daily_log_cleanup':       '0 0 * * *',
    'chunk_cleanup_job':       '0 3 * * *',
    'camera_archive_hourly':   '0 * * * *',
    'camera_archive_cleanup':  '0 4 * * *',
    'lotto_weekly_job':        '0 22 * * 6',
}


# ────────────────────────────────────────────────────────────────────
# 1) read_schedule_settings 가 seed 13건 반환
# ────────────────────────────────────────────────────────────────────
def test_read_schedule_settings_returns_seed_rows():
    rows = read_schedule_settings()
    assert isinstance(rows, list)
    names = {r['task_name'] for r in rows}
    expected = set(SEED_INTERVAL_TASKS) | set(SEED_CRON_TASKS)
    missing = expected - names
    assert not missing, f"seed 누락: {missing}"


# ────────────────────────────────────────────────────────────────────
# 2) 각 task_name 의 schedule_type / interval_seconds / cron_expr 매핑
# ────────────────────────────────────────────────────────────────────
def test_seed_interval_tasks_match():
    rows = {r['task_name']: r for r in read_schedule_settings()}
    for task, secs in SEED_INTERVAL_TASKS.items():
        r = rows.get(task)
        assert r is not None, f"{task} row 없음"
        assert r['schedule_type'] == 'interval', f"{task} schedule_type"
        assert r['interval_seconds'] == secs, f"{task} interval_seconds"
        assert r['cron_expr'] is None, f"{task} cron_expr 가 NULL 이어야 함"


def test_seed_cron_tasks_match():
    rows = {r['task_name']: r for r in read_schedule_settings()}
    for task, expr in SEED_CRON_TASKS.items():
        r = rows.get(task)
        assert r is not None, f"{task} row 없음"
        assert r['schedule_type'] == 'cron', f"{task} schedule_type"
        assert r['cron_expr'] == expr, f"{task} cron_expr"
        assert r['interval_seconds'] is None, f"{task} interval_seconds 가 NULL 이어야 함"


# ────────────────────────────────────────────────────────────────────
# 3) seed row 들은 enabled=true 로 시작
# ────────────────────────────────────────────────────────────────────
def test_seed_rows_enabled():
    rows = read_schedule_settings()
    for r in rows:
        assert r['enabled'] is True, f"{r['task_name']} enabled 가 True 여야 함"


# ────────────────────────────────────────────────────────────────────
# 4) read_schedule_max_updt 가 datetime 반환
# ────────────────────────────────────────────────────────────────────
def test_read_schedule_max_updt():
    from datetime import datetime
    max_updt = read_schedule_max_updt()
    assert max_updt is not None
    assert isinstance(max_updt, datetime)


# ────────────────────────────────────────────────────────────────────
# 5) UPDATE 시 updt_dttm 트리거 자동 갱신
# ────────────────────────────────────────────────────────────────────
def test_updt_dttm_trigger_on_update():
    test_task = '__test_trigger_updt'
    with db_session() as db:
        db.execute_query(
            "INSERT INTO schedule_m_setting (task_name, schedule_type, interval_seconds, description) "
            "VALUES (%s, 'interval', 30, '__test__')",
            (test_task,)
        )
    try:
        before = read_schedule_max_updt()
        time.sleep(0.05)
        with db_session() as db:
            db.execute_query(
                "UPDATE schedule_m_setting SET interval_seconds = 31 WHERE task_name = %s",
                (test_task,)
            )
        after = read_schedule_max_updt()
        assert after is not None and before is not None
        assert after > before, f"updt_dttm 트리거 동작 실패 ({before} → {after})"
    finally:
        with db_session() as db:
            db.execute_query("DELETE FROM schedule_m_setting WHERE task_name = %s", (test_task,))


# ────────────────────────────────────────────────────────────────────
# 6) CHECK 제약 — interval 타입은 interval_seconds 필수, cron_expr NULL 이어야
#    db.execute_query 는 예외를 swallow 하므로 "INSERT 후 row 미생성" 으로 검증.
# ────────────────────────────────────────────────────────────────────
def _try_insert(test_task, schedule_type, interval_seconds, cron_expr):
    """INSERT 시도 후 row 가 실제로 생성됐는지 반환. 정리는 호출자가 책임."""
    with db_session() as db:
        db.execute_query(
            "INSERT INTO schedule_m_setting (task_name, schedule_type, interval_seconds, cron_expr) "
            "VALUES (%s, %s, %s, %s)",
            (test_task, schedule_type, interval_seconds, cron_expr)
        )
    with db_session() as db:
        row = db.fetch_one(
            "SELECT 1 AS x FROM schedule_m_setting WHERE task_name = %s",
            (test_task,)
        )
    if row:
        with db_session() as db:
            db.execute_query("DELETE FROM schedule_m_setting WHERE task_name = %s", (test_task,))
    return row is not None


def test_check_constraint_interval_requires_seconds():
    inserted = _try_insert('__test_constraint_a', 'interval', None, None)
    assert not inserted, "interval+NULL seconds 가 CHECK 제약에 안 걸림"


def test_check_constraint_cron_requires_expr():
    inserted = _try_insert('__test_constraint_b', 'cron', None, None)
    assert not inserted, "cron+NULL expr 가 CHECK 제약에 안 걸림"


def test_check_constraint_interval_excludes_cron_expr():
    inserted = _try_insert('__test_constraint_c', 'interval', 10, '0 * * * *')
    assert not inserted, "interval 타입에 cron_expr 같이 들어감 — CHECK 제약 누락"


def test_check_constraint_invalid_schedule_type():
    """schedule_type 이 'interval'/'cron' 외 값이면 INSERT 실패"""
    inserted = _try_insert('__test_constraint_d', 'unknown_type', 10, None)
    assert not inserted, "schedule_type CHECK 제약 누락"
