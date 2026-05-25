# ══════════════════════════════════════════════════════════════════════════════
# tools_agent_sub — 채팅에서 반복 agent 모니터링 등록 (B 단계) [2026-05-25]
#
# 채팅 LLM 이 "1시간마다 모니터링하라" 같은 *반복 의도* 를 받으면 이 도구를 호출.
# agent_subscriptions 테이블에 INSERT 하고, agent_scheduler 가 매 분 polling 으로
# due subscription 을 잡아 ai_monitor_agent.run_agent 호출 → 결과 alert 영속.
#
# 기존 schedule_monitor (간단 임계값 체크) 와 분리:
#   · schedule_monitor: 단순 센서 임계 이탈 알림 (APScheduler)
#   · agent_subscribe:  ReAct 다단계 분석 (ai_monitor_agent)
#
# 도구 3개:
#   · agent_subscribe         (task, interval_min, farm_id, user_id?)
#   · list_agent_subscriptions(user_id?)
#   · cancel_agent_subscription(id)
#
# 파일 시작 함수 목록:
#   agent_subscribe              : INSERT row, 반환 {success, subscription_id, ...}
#   list_agent_subscriptions     : SELECT active rows
#   cancel_agent_subscription    : UPDATE active=FALSE, cancelled_*
# ══════════════════════════════════════════════════════════════════════════════
import json
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# ── 안전 가드 파라미터 ──
MIN_INTERVAL_MIN = 5     # 5분 미만 등록 금지 (LLM 부담)
MAX_INTERVAL_MIN = 1440  # 24시간 초과 금지
MAX_PER_USER     = 5     # 사용자당 active subscription 최대 5건


# ────────────────────────────────────────────────────────────────────
# get_pending_alerts — 미수신 agent 알림 조회 (채팅 LLM 이 응답 시 참조)
# ────────────────────────────────────────────────────────────────────
def get_pending_alerts(*, user_id: Optional[str] = None,
                       limit: int = 10,
                       mark_read: bool = True) -> Dict[str, Any]:
    """미읽 알림을 가져옴. mark_read=True 면 동시에 read_at 설정 (idempotent)."""
    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
    except Exception as e:
        return {"success": False, "reason": "db_error", "message": str(e)}

    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10

    conn = db._getconn()
    if conn is None:
        return {"success": False, "reason": "db_error",
                "message": "DB connection 실패"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = ["read_at IS NULL"]
            vals = []
            if user_id:
                where.append("(user_id IS NULL OR user_id=%s)")
                vals.append(user_id)
            sql = (
                f"SELECT id, created_at, user_id, subscription_id, agent_log_id, "
                f"       level, title, body "
                f"FROM agent_user_alerts "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY created_at DESC LIMIT %s"
            )
            cur.execute(sql, tuple(vals) + (limit,))
            rows = cur.fetchall()
            items = [
                {
                    "id": int(r["id"]),
                    "created_at": str(r["created_at"]),
                    "user_id": r["user_id"],
                    "subscription_id": r["subscription_id"],
                    "agent_log_id": r["agent_log_id"],
                    "level": r["level"],
                    "title": r["title"],
                    "body": r["body"],
                }
                for r in rows
            ]
            if mark_read and items:
                ids = [it["id"] for it in items]
                cur.execute(
                    "UPDATE agent_user_alerts SET read_at=NOW() "
                    "WHERE id = ANY(%s) AND read_at IS NULL",
                    (ids,))
            conn.commit()
        return {"success": True, "count": len(items), "alerts": items}
    except Exception as e:
        logger.warning(f"[Agent Alert] get_pending 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return {"success": False, "reason": "db_error", "message": str(e)}
    finally:
        try: db._putconn(conn)
        except Exception: pass


# ────────────────────────────────────────────────────────────────────
# agent_subscribe — 채팅에서 반복 agent 모니터링 등록
# ────────────────────────────────────────────────────────────────────
def agent_subscribe(*, task: str, interval_min: int,
                    farm_id: Optional[int] = None,
                    house_id: Optional[int] = None,
                    user_id: Optional[str] = None,
                    intent: Optional[str] = None) -> Dict[str, Any]:
    """반복 agent task 등록.

    Args:
        task: agent 가 수행할 작업 (한국어 한 문장)
        interval_min: 사이클 주기 (5~1440 분)
        farm_id: 농장 ID (기본 1)
        house_id: 호기 ID (선택)
        user_id: 채팅 발신자 (선택, 없으면 NULL = 운영자 등록 취급)
        intent: 사용자 자연어 원문 (감사 로그용)
    """
    # 인자 검증
    if not task or not task.strip():
        return {"success": False, "reason": "invalid_args", "message": "task 필수"}
    try:
        interval_min = int(interval_min)
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_args",
                "message": "interval_min 정수 필요"}
    if not (MIN_INTERVAL_MIN <= interval_min <= MAX_INTERVAL_MIN):
        return {"success": False, "reason": "invalid_args",
                "message": f"interval_min 범위 {MIN_INTERVAL_MIN}~{MAX_INTERVAL_MIN}분"}
    try:
        farm_id = int(farm_id) if farm_id is not None else 1
    except (TypeError, ValueError):
        farm_id = 1
    try:
        house_id = int(house_id) if house_id is not None else None
    except (TypeError, ValueError):
        house_id = None
    user_id = (user_id or None) and str(user_id)[:50]
    intent  = (intent or task[:200])[:500]

    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
    except Exception as e:
        return {"success": False, "reason": "db_error", "message": str(e)}

    conn = db._getconn()
    if conn is None:
        return {"success": False, "reason": "db_error",
                "message": "DB connection 실패"}

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 사용자당 active 갯수 제한
            if user_id:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM agent_subscriptions "
                    "WHERE user_id=%s AND active=TRUE", (user_id,))
                row = cur.fetchone()
                cnt = int(row["c"]) if row else 0
                if cnt >= MAX_PER_USER:
                    return {"success": False, "reason": "limit",
                            "message": f"활성 구독 한도 {MAX_PER_USER}건 초과 ({cnt})"}

            cur.execute(
                "INSERT INTO agent_subscriptions "
                "(user_id, farm_id, house_id, interval_min, task, intent, next_run_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW() + (%s || ' minutes')::interval) "
                "RETURNING id",
                (user_id, farm_id, house_id, interval_min,
                 task.strip()[:1000], intent, str(interval_min))
            )
            row = cur.fetchone()
            conn.commit()

        sub_id = int(row["id"]) if row else None
        logger.info(
            f"[Agent Sub] 등록 id={sub_id} user={user_id or '-'} "
            f"farm={farm_id} interval={interval_min}분 task={task[:60]!r}"
        )
        return {
            "success": True,
            "subscription_id": sub_id,
            "interval_min": interval_min,
            "farm_id": farm_id,
            "house_id": house_id,
            "message": f"{interval_min}분마다 모니터링 등록 (id={sub_id}). "
                       f"첫 사이클은 {interval_min}분 뒤. 취소하려면 'id {sub_id} 취소' 명령.",
        }
    except Exception as e:
        logger.warning(f"[Agent Sub] 등록 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return {"success": False, "reason": "db_error", "message": str(e)}
    finally:
        try: db._putconn(conn)
        except Exception: pass


# ────────────────────────────────────────────────────────────────────
# list_agent_subscriptions — 활성 구독 조회
# ────────────────────────────────────────────────────────────────────
def list_agent_subscriptions(*, user_id: Optional[str] = None,
                             include_default: bool = False) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
    except Exception as e:
        return {"success": False, "reason": "db_error", "message": str(e)}

    try:
        where = ["active=TRUE"]
        vals = []
        if user_id:
            where.append("user_id=%s")
            vals.append(user_id)
        elif not include_default:
            # 운영자 자동 default subscription 은 일반 list 에서 숨김
            where.append("intent <> '__default_cron__'")
        sql = (
            f"SELECT id, user_id, farm_id, house_id, interval_min, task, intent, "
            f"       created_at, last_run_at, next_run_at, total_runs "
            f"FROM agent_subscriptions "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY created_at DESC LIMIT 50"
        )
        with db_session() as d:
            rows = d.fetch_all(sql, tuple(vals), as_dict=True)
        items = [
            {
                "id": int(r["id"]),
                "user_id": r["user_id"],
                "farm_id": r["farm_id"],
                "house_id": r["house_id"],
                "interval_min": int(r["interval_min"]),
                "task": r["task"],
                "intent": r["intent"],
                "created_at": str(r["created_at"]),
                "last_run_at": str(r["last_run_at"]) if r["last_run_at"] else None,
                "next_run_at": str(r["next_run_at"]),
                "total_runs": int(r["total_runs"] or 0),
            }
            for r in (rows or [])
        ]
        return {"success": True, "count": len(items), "subscriptions": items}
    except Exception as e:
        logger.warning(f"[Agent Sub] list 실패: {e}")
        return {"success": False, "reason": "db_error", "message": str(e)}


# ────────────────────────────────────────────────────────────────────
# cancel_agent_subscription — 구독 취소 (active=FALSE)
# ────────────────────────────────────────────────────────────────────
def cancel_agent_subscription(*, subscription_id: int,
                              user_id: Optional[str] = None,
                              reason: Optional[str] = None) -> Dict[str, Any]:
    try:
        subscription_id = int(subscription_id)
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_args",
                "message": "subscription_id 정수 필요"}

    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception as e:
        return {"success": False, "reason": "db_error", "message": str(e)}

    conn = db._getconn()
    if conn is None:
        return {"success": False, "reason": "db_error",
                "message": "DB connection 실패"}
    try:
        with conn.cursor() as cur:
            # 사용자 일치 검증 (user_id 가 주어진 경우만)
            if user_id:
                cur.execute(
                    "SELECT user_id, active FROM agent_subscriptions WHERE id=%s",
                    (subscription_id,))
                row = cur.fetchone()
                if not row:
                    return {"success": False, "reason": "not_found",
                            "message": f"id={subscription_id} 없음"}
                if row[0] and row[0] != user_id:
                    return {"success": False, "reason": "forbidden",
                            "message": "다른 사용자 구독 — 취소 불가"}
                if not row[1]:
                    return {"success": False, "reason": "already_inactive",
                            "message": "이미 취소된 구독"}

            cur.execute(
                "UPDATE agent_subscriptions "
                "SET active=FALSE, cancelled_at=NOW(), cancelled_by=%s "
                "WHERE id=%s AND active=TRUE",
                (f"user:{user_id}" if user_id else "system:cancel",
                 subscription_id))
            affected = cur.rowcount
            conn.commit()
        if affected == 0:
            return {"success": False, "reason": "not_found_or_inactive",
                    "message": f"id={subscription_id} 활성 구독 없음"}
        logger.info(f"[Agent Sub] 취소 id={subscription_id} user={user_id or '-'}")
        return {"success": True, "subscription_id": subscription_id,
                "message": f"구독 id={subscription_id} 취소 완료"}
    except Exception as e:
        logger.warning(f"[Agent Sub] 취소 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return {"success": False, "reason": "db_error", "message": str(e)}
    finally:
        try: db._putconn(conn)
        except Exception: pass
