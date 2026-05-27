# ═══════════════════════════════════════════════════════════════════════════
# 통합 테스트 — DB 트리거 → NOTIFY → Python LISTEN 수신 검증.
#
# 운영 DB 사용. schedule_m_setting 의 임시 row 로 INSERT/UPDATE/DELETE 시
# 채널 'setting_changed' NOTIFY 가 실제로 발화·수신되는지 확인.
# ═══════════════════════════════════════════════════════════════════════════
import json
import select
import time

import pytest

from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.control.setting_listener import _open_listen_connection


# ────────────────────────────────────────────────────────────────────
# DB 트리거 → NOTIFY → 본 프로세스의 LISTEN connection 으로 수신.
# ────────────────────────────────────────────────────────────────────
def test_db_notify_received_for_schedule_change():
    test_task = '__notify_integration__'

    # 1) LISTEN connection 준비
    conn = _open_listen_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("LISTEN setting_changed;")

        # 2) 다른 connection 으로 INSERT — 트리거 발화 → NOTIFY
        with db_session() as db:
            db.execute_query(
                "INSERT INTO schedule_m_setting (task_name, schedule_type, interval_seconds, description) "
                "VALUES (%s, 'interval', 30, '__test__')",
                (test_task,)
            )

        # 3) 알림 폴링 (최대 5초)
        deadline = time.time() + 5
        received = []
        while time.time() < deadline and not received:
            ready = select.select([conn], [], [], 1)
            if ready == ([], [], []):
                continue
            conn.poll()
            while conn.notifies:
                n = conn.notifies.pop(0)
                received.append(n.payload)

        assert received, "5초 내 NOTIFY 수신 실패 — 트리거 미동작"

        # payload 가 schedule_m_setting INSERT 인지 확인 (다른 변경도 섞일 수 있음)
        ok = False
        for p in received:
            try:
                j = json.loads(p)
            except Exception:
                continue
            if j.get('table') == 'schedule_m_setting' and j.get('op') == 'INSERT':
                ok = True
                break
        assert ok, f"schedule_m_setting INSERT NOTIFY 미수신: payloads={received}"
    finally:
        # 정리
        with db_session() as db:
            db.execute_query("DELETE FROM schedule_m_setting WHERE task_name = %s", (test_task,))
        try:
            conn.close()
        except Exception:
            pass


def test_db_notify_received_for_update():
    """기존 schedule row UPDATE → NOTIFY 수신."""
    test_task = '__notify_update_test__'

    # seed
    with db_session() as db:
        db.execute_query(
            "INSERT INTO schedule_m_setting (task_name, schedule_type, interval_seconds, description) "
            "VALUES (%s, 'interval', 30, '__test__')",
            (test_task,)
        )

    conn = _open_listen_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("LISTEN setting_changed;")

        # UPDATE
        with db_session() as db:
            db.execute_query(
                "UPDATE schedule_m_setting SET interval_seconds = 31 WHERE task_name = %s",
                (test_task,)
            )

        # 폴링
        deadline = time.time() + 5
        received = []
        while time.time() < deadline and not received:
            ready = select.select([conn], [], [], 1)
            if ready == ([], [], []):
                continue
            conn.poll()
            while conn.notifies:
                n = conn.notifies.pop(0)
                received.append(n.payload)

        assert received, "UPDATE NOTIFY 수신 실패"
        ok = any(
            (json.loads(p).get('op') == 'UPDATE' and
             json.loads(p).get('table') == 'schedule_m_setting')
            for p in received if _is_json(p)
        )
        assert ok
    finally:
        with db_session() as db:
            db.execute_query("DELETE FROM schedule_m_setting WHERE task_name = %s", (test_task,))
        try:
            conn.close()
        except Exception:
            pass


def _is_json(s):
    try:
        json.loads(s); return True
    except Exception:
        return False
