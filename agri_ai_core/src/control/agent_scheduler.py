# ══════════════════════════════════════════════════════════════════════════════
# Agent Scheduler — 30분 cron 데몬 (Phase 2) [2026-05-25 신규]
#
# 매 N분 정각마다 ai_monitor_agent.run_agent 호출 → DB 영속.
# 운영 scheduler (`agri_ai_core/scheduler.py`) 와 *완전 별개 프로세스*.
#
# 동작:
#   · 매 분 시작 시 sleep 으로 정확한 정각 도달 대기
#   · 사이클 안 LLM 호출 동안 다음 분 도달 → 그 사이클 종료 후 다음 정각 대기
#   · _is_previous_running flag — 사이클이 30분 넘어가도 중첩 실행 방지
#
# 환경변수:
#   AGENT_INTERVAL_MIN  : 사이클 주기 (기본 30분)
#   AGENT_FARM_IDS      : 모니터링 농장 ID 쉼표 구분 (기본 "1")
#   AGENT_INITIAL_DELAY : 시작 시 첫 사이클 대기 (초, 기본 60)
#   AGENT_LLM_MODEL     : LLM 모델 (ai_monitor_agent 와 공유)
#
# 사용법:
#   python -m agri_ai_core.src.control.agent_scheduler
#
# 파일 시작 함수 목록:
#   _next_interval_dt    : 다음 사이클 fire 시각 계산
#   _run_cycle           : 한 사이클 실행 (모든 농장 모니터링)
#   _build_default_task  : 기본 작업 지시문 합성
#   main                 : 무한 loop 엔트리포인트
# ══════════════════════════════════════════════════════════════════════════════
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import List

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.control.ai_monitor_agent import run_agent

logger = setup_logger(__name__)

AGENT_INTERVAL_MIN  = int(os.getenv("AGENT_INTERVAL_MIN", "30"))
AGENT_INITIAL_DELAY = int(os.getenv("AGENT_INITIAL_DELAY", "60"))
AGENT_FARM_IDS      = [int(x.strip()) for x in os.getenv("AGENT_FARM_IDS", "1").split(",") if x.strip()]
# [B 단계 2026-05-25] subscriptions polling 주기 (초). 기본 60.
AGENT_SUB_POLL_SEC  = int(os.getenv("AGENT_SUB_POLL_SEC", "60"))
# default subscription 자동 부트스트랩 여부 (기존 30분 cron 호환)
AGENT_BOOTSTRAP_DEFAULT = os.getenv("AGENT_BOOTSTRAP_DEFAULT", "1") == "1"

_STOP = False


def _on_signal(signum, frame):
    """SIGTERM/SIGINT 우아한 종료."""
    global _STOP
    logger.info(f"[Agent Scheduler] signal {signum} 수신 — 다음 cycle 후 종료")
    _STOP = True


# ────────────────────────────────────────────────────────────────────
# 다음 cycle 시각 — 정각 기준 AGENT_INTERVAL_MIN 단위로 정렬.
# 예: 현재 12:17 / 30분 주기 → 12:30. 현재 12:31 → 13:00.
# ────────────────────────────────────────────────────────────────────
def _next_interval_dt(now: datetime = None) -> datetime:
    now = now or datetime.now()
    # 현재 분을 AGENT_INTERVAL_MIN 으로 나눠 다음 boundary 찾기
    minutes = (now.minute // AGENT_INTERVAL_MIN + 1) * AGENT_INTERVAL_MIN
    if minutes >= 60:
        # 다음 시간 정각
        nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        nxt = now.replace(minute=minutes, second=0, microsecond=0)
    return nxt


# ────────────────────────────────────────────────────────────────────
# 기본 작업 지시문 — Phase 2 단순화. Phase 5 에서 이벤트별 분기 가능.
# ────────────────────────────────────────────────────────────────────
def _build_default_task(farm_id: int) -> str:
    now = datetime.now().strftime("%H:%M")
    return (
        f"농장 {farm_id} 전체 호기 정기 30분 모니터링 ({now} 기준).\n"
        f"각 호기의 현재 센서 상태를 확인하고, 임계 근접·이상치·LLM 결정 패턴을 "
        f"종합 분석해 운영자가 알아야 할 위험 신호가 있는지 보고하라."
    )


# ────────────────────────────────────────────────────────────────────
# 한 cycle — 모든 농장에 대해 agent 실행. 결과는 자동 DB 영속.
# ────────────────────────────────────────────────────────────────────
def _run_cycle():
    cycle_start = time.time()
    logger.info(f"[Agent Scheduler] === cycle 시작 {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    for farm_id in AGENT_FARM_IDS:
        if _STOP:
            logger.info("[Agent Scheduler] 종료 신호 — cycle 중단")
            return
        task = _build_default_task(farm_id)
        try:
            result = run_agent(task=task, farm_id=farm_id, trigger_type="schedule")
            ok = result.get("success")
            duration = result.get("duration_sec")
            log_id = result.get("log_id")
            final_preview = (result.get("final") or "")[:120]
            logger.info(
                f"[Agent Scheduler] farm={farm_id} 완료 success={ok} duration={duration}s "
                f"log_id={log_id} | {final_preview}"
            )
        except Exception as e:
            logger.warning(f"[Agent Scheduler] farm={farm_id} 예외: {e}")

    cycle_duration = time.time() - cycle_start
    logger.info(f"[Agent Scheduler] === cycle 완료 ({cycle_duration:.1f}s) ===")


# ════════════════════════════════════════════════════════════════════
# [B 단계 2026-05-25] Subscriptions polling — 사용자 채팅 등록 반복 task
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# default subscription 부트스트랩 — 기존 30분 cron 행동 보존.
# AGENT_FARM_IDS 각 농장에 대해 *시스템 default* subscription 이 없으면 생성.
# 표시자: user_id=NULL, intent='__default_cron__'.
# ────────────────────────────────────────────────────────────────────
def _bootstrap_default_subscriptions():
    if not AGENT_BOOTSTRAP_DEFAULT:
        return
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for farm_id in AGENT_FARM_IDS:
                cur.execute(
                    "SELECT id FROM agent_subscriptions "
                    "WHERE farm_id=%s AND user_id IS NULL "
                    "  AND intent='__default_cron__' AND active=TRUE LIMIT 1",
                    (farm_id,))
                row = cur.fetchone()
                if row:
                    continue
                task = (
                    f"농장 {farm_id} 전체 호기 정기 {AGENT_INTERVAL_MIN}분 모니터링. "
                    f"각 호기의 현재 센서 상태를 확인하고, 임계 근접·이상치·LLM 결정 "
                    f"패턴을 종합 분석해 운영자가 알아야 할 위험 신호가 있는지 보고하라."
                )
                cur.execute(
                    "INSERT INTO agent_subscriptions "
                    "(user_id, farm_id, house_id, interval_min, task, intent, next_run_at) "
                    "VALUES (NULL, %s, NULL, %s, %s, '__default_cron__', NOW())",
                    (farm_id, AGENT_INTERVAL_MIN, task))
                logger.info(f"[Agent Scheduler] default subscription 생성: farm={farm_id} interval={AGENT_INTERVAL_MIN}분")
            conn.commit()
    except Exception as e:
        logger.warning(f"[Agent Scheduler] bootstrap 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


# ────────────────────────────────────────────────────────────────────
# polling: active + next_run_at <= NOW() 인 row 잡아옴.
# SKIP LOCKED 로 race-free (다중 scheduler 실행 시도 시).
# ────────────────────────────────────────────────────────────────────
def _claim_due_subscriptions(limit: int = 5):
    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
    except Exception:
        return []
    conn = db._getconn()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, user_id, farm_id, house_id, interval_min, task, intent "
                "FROM agent_subscriptions "
                "WHERE active=TRUE AND next_run_at <= NOW() "
                "ORDER BY next_run_at "
                "FOR UPDATE SKIP LOCKED LIMIT %s",
                (limit,))
            rows = cur.fetchall()
            conn.commit()
        return [dict(r) for r in rows] if rows else []
    except Exception as e:
        logger.warning(f"[Agent Scheduler] _claim_due_subscriptions 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return []
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _advance_subscription(sub_id: int, interval_min: int):
    """사이클 끝나면 next_run_at += interval_min, total_runs += 1."""
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_subscriptions "
                "SET last_run_at = NOW(), "
                "    next_run_at = GREATEST(NOW(), next_run_at) + (%s || ' minutes')::interval, "
                "    total_runs = total_runs + 1 "
                "WHERE id=%s",
                (str(interval_min), sub_id))
            conn.commit()
    except Exception as e:
        logger.warning(f"[Agent Scheduler] _advance_subscription({sub_id}) 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _save_alert(user_id, sub_id, log_id, level, title, body):
    """agent_user_alerts 에 결과 영속. 채팅 프론트엔드가 폴링/SSE 로 받음."""
    if not body:
        return
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_user_alerts "
                "(user_id, subscription_id, agent_log_id, level, title, body) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, sub_id, log_id, level, (title or "")[:200], body))
            conn.commit()
    except Exception as e:
        logger.warning(f"[Agent Scheduler] _save_alert 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _run_subscription(sub: dict):
    """단일 subscription 실행 — run_agent 호출 + advance + alert."""
    sub_id = int(sub["id"])
    farm_id = int(sub["farm_id"]) if sub.get("farm_id") else 1
    task = sub["task"]
    user_id = sub.get("user_id")
    interval_min = int(sub.get("interval_min") or AGENT_INTERVAL_MIN)
    is_default = (sub.get("intent") == "__default_cron__")

    logger.info(
        f"[Agent Scheduler] subscription #{sub_id} 실행 farm={farm_id} "
        f"user={user_id or '-'} interval={interval_min}분 default={is_default}"
    )
    try:
        result = run_agent(task=task, farm_id=farm_id, trigger_type="subscription")
        ok = result.get("success")
        log_id = result.get("log_id")
        final = result.get("final") or ""
        logger.info(
            f"[Agent Scheduler] sub #{sub_id} 완료 success={ok} "
            f"log_id={log_id} | {final[:100]}"
        )
        # 사용자 등록 subscription 만 alert 영속 (default 는 운영 로그/DB 이력 충분)
        if not is_default and user_id and final:
            level = "info" if ok else "warning"
            title = f"농장 {farm_id} 모니터링 결과"
            _save_alert(user_id, sub_id, log_id, level, title, final)
    except Exception as e:
        logger.warning(f"[Agent Scheduler] sub #{sub_id} 예외: {e}")
    finally:
        _advance_subscription(sub_id, interval_min)


def _run_due_subscriptions():
    """매 polling 사이클: due subscription 모두 처리."""
    rows = _claim_due_subscriptions(limit=5)
    if not rows:
        return
    logger.info(f"[Agent Scheduler] due subscriptions = {len(rows)}건")
    for row in rows:
        if _STOP:
            return
        _run_subscription(row)


# ────────────────────────────────────────────────────────────────────
# 메인 — 매 분 polling. subscriptions 처리 + (option) 30분 boundary cron.
# 기존 30분 cron 동작은 default subscription 으로 보존 (_bootstrap_default).
# ────────────────────────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT,  _on_signal)

    logger.info(
        f"[Agent Scheduler] 시작 interval={AGENT_INTERVAL_MIN}분 (default cron) "
        f"farms={AGENT_FARM_IDS} sub_poll={AGENT_SUB_POLL_SEC}s "
        f"initial_delay={AGENT_INITIAL_DELAY}s"
    )

    # 시작 직후 즉시 사이클 도는 것 방지 (Ollama 준비 대기)
    if AGENT_INITIAL_DELAY > 0:
        for _ in range(AGENT_INITIAL_DELAY):
            if _STOP:
                return
            time.sleep(1)

    # default subscription 부트스트랩 (기존 30분 cron 행동 보존)
    _bootstrap_default_subscriptions()

    # 메인 loop — 매 AGENT_SUB_POLL_SEC 초마다 due subscriptions 처리
    while not _STOP:
        try:
            _run_due_subscriptions()
        except Exception as e:
            logger.error(f"[Agent Scheduler] polling 사이클 예외: {e}")

        # 1초 단위 sleep + 종료 신호 체크 (즉시 반응)
        slept = 0
        while slept < AGENT_SUB_POLL_SEC and not _STOP:
            time.sleep(1)
            slept += 1

    logger.info("[Agent Scheduler] 정상 종료")


if __name__ == "__main__":
    sys.exit(main() or 0)
