# ══════════════════════════════════════════════════════════════════════════════
# tools_agent_sub — 채팅에서 반복 agent 모니터링 등록
#
# 채팅 LLM 이 "1시간마다 모니터링하라" 같은 *반복 의도* 를 받으면 이 도구를 호출.
# agent_subscriptions 테이블에 INSERT 하고, agent_scheduler 가 매 분 polling 으로
# due subscription 을 잡아 ai_monitor_agent.run_agent 호출 → 결과 alert 영속.
#
# schedule_monitor (간단 임계값 체크) 와 역할 구분:
#   · schedule_monitor: 단순 센서 임계 이탈 알림 (APScheduler)
#   · agent_subscribe:  ReAct 다단계 분석 (ai_monitor_agent)
#
# 도구 5개:
#   · agent_subscribe         (task, interval_min, farm_id, user_id?)
#   · list_agent_subscriptions(user_id?)
#   · cancel_agent_subscription(id)
#   · set_alert_interval      (interval_min)  — 카카오 발송 간격
#   · set_alert_level         (level)         — 카카오 발송 최소 심각도
#
# 카카오 알림 정책(간격·심각도)은 농장주가 채팅으로 요청하면 LLM 이 아래 두 도구로
# kakao_notify_config 에 기록하고, kakao_notify.push_alert 가 그 값을 이행한다.
# 코드는 정책을 정하지 않는다. critical(비상) 은 정책과 무관하게 항상 즉시 발송.
#
# 파일 시작 함수 목록:
#   agent_subscribe              : INSERT row, 반환 {success, subscription_id, ...}
#   list_agent_subscriptions     : SELECT active rows
#   cancel_agent_subscription    : UPDATE active=FALSE, cancelled_*
#   set_alert_interval           : 카카오 최소 발송 간격(분) 기록 (0=해제)
#   set_alert_level              : 카카오 최소 심각도 기록 (info|warning|critical)
# ══════════════════════════════════════════════════════════════════════════════
import json
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# ── 안전 가드 파라미터 ──
MIN_INTERVAL_MIN = 5     # 5분 미만 등록 금지 (LLM 부담)
MAX_INTERVAL_MIN = 1440  # 24시간 초과 금지
MAX_PER_USER     = 5     # 사용자당 active subscription 최대 5건
# 대체 판정은 보수적으로 — 오대체가 자율제어 구독을 중단시키는 위험이 억제 실익보다 크다.
SIMILAR_TASK_RATIO = 0.62  # 이 이상(준동일 재등록)만 기존 구독 자동 대체
SIMILAR_WARN_RATIO = 0.30  # 이 이상이면 대체하지 않고 결과에 중복 의심 경고 부착
# (실측: 동일 지시 1.0 / 표현만 바꾼 재지시 0.35~0.57 / 성격 다른 자율제어 ≤0.21 /
#  공통 접두어 있는 짧은 상이 과제 0.39~0.51 — 부풀림 존재)


# ────────────────────────────────────────────────────────────────────
# 두 task 문장의 유사도(0~1) — 같은 지시의 재등록(중복 누적) 판정용.
# 임베딩 없이 결정적으로 동작: 문자 2-gram 자카드와 difflib ratio 중 큰 값.
# ────────────────────────────────────────────────────────────────────
def _task_similarity(a: str, b: str) -> float:
    import difflib
    na = "".join((a or "").split())[:300]
    nb = "".join((b or "").split())[:300]
    if not na or not nb:
        return 0.0
    ga = {na[i:i + 2] for i in range(len(na) - 1)}
    gb = {nb[i:i + 2] for i in range(len(nb) - 1)}
    jac = len(ga & gb) / max(1, len(ga | gb))
    return max(jac, difflib.SequenceMatcher(None, na, nb).ratio())


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

            conflict_note = ""
            cur.execute(
                "SELECT id, next_run_at "
                "FROM agent_subscriptions "
                "WHERE active=TRUE AND farm_id=%s AND intent='__default_cron__' "
                "  AND ABS(EXTRACT(EPOCH FROM (next_run_at - (NOW() + (%s || ' minutes')::interval)))) <= 180 "
                "ORDER BY next_run_at LIMIT 1",
                (farm_id, str(interval_min)),
            )
            conflict = cur.fetchone()
            if conflict:
                conflict_note = (
                    f" 기본 Agent(id={int(conflict['id'])}) 예정 시각과 3분 이내로 겹칩니다. "
                    "LLM 품질 보호를 위해 같은 시각 동시 실행은 하지 않고, 이전 Agent 사이클 종료 후 순차 실행될 수 있습니다."
                )

            # 동일 farm 의 유사 task 활성 구독은 새 구독으로 자동 대체 —
            # "2시간마다로 해라" 류 재지시가 중복 누적되지 않게 한다 (2026-07-15 실사고:
            # 동일 지시 3중 등록 + 구형 잔존으로 합성 알림 간격 2~5분 폭주).
            replaced_ids = []
            similar_warn = []
            cur.execute(
                "SELECT id, task FROM agent_subscriptions "
                "WHERE active=TRUE AND farm_id=%s AND COALESCE(intent,'') <> '__default_cron__'",
                (farm_id,))
            for old_row in (cur.fetchall() or []):
                _sim = _task_similarity(task, old_row["task"])
                if _sim >= SIMILAR_TASK_RATIO:
                    cur.execute(
                        "UPDATE agent_subscriptions SET active=FALSE, cancelled_at=NOW(), "
                        "cancelled_by='유사 구독 자동 대체' WHERE id=%s", (int(old_row["id"]),))
                    replaced_ids.append(int(old_row["id"]))
                elif _sim >= SIMILAR_WARN_RATIO:
                    similar_warn.append(int(old_row["id"]))

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
        if replaced_ids:
            logger.info(f"[Agent Sub] 유사 구독 자동 대체: {replaced_ids} → 신규 id={sub_id}")
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
            "replaced_subscription_ids": replaced_ids,
            "similar_subscription_ids": similar_warn,
            "message": (f"기존 유사 구독 {replaced_ids} 을(를) 새 구독으로 대체했습니다. " if replaced_ids else "")
                       + (f"⚠ 비슷해 보이는 기존 구독 {similar_warn} 이 있습니다 — 중복이면 'id N 취소'로 정리를 권합니다. " if similar_warn else "")
                       + f"{interval_min}분마다 모니터링 등록 (id={sub_id}). "
                       f"첫 사이클은 {interval_min}분 뒤. 취소하려면 'id {sub_id} 취소' 명령."
                       f"{conflict_note}",
            "warning": conflict_note or None,
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
# ────────────────────────────────────────────────────────────────────
# set_alert_interval — 카카오 알림 최소 간격(쿨다운) 설정.
# 제어·채팅 알림은 그대로 유지하고 카카오 발송 빈도만 낮춘다.
# farm_id 지정 시 그 농장의 전체 활성 구독(숨김 __default_cron__ 포함)에 적용 —
# "이 농장 알림을 2시간마다로" 요구를 한 번에 반영. subscription_id 지정 시 개별.
# interval_min=0 은 쿨다운 해제(매번 발송).
# ────────────────────────────────────────────────────────────────────
def set_alert_interval(*, interval_min: int,
                       farm_id: Optional[int] = None,
                       subscription_id: Optional[int] = None,
                       auth_farm_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        interval_min = int(interval_min)
    except (TypeError, ValueError):
        return {"success": False, "message": "interval_min 은 정수(분)여야 합니다. 0=해제"}
    if interval_min < 0 or interval_min > 1440:
        return {"success": False, "message": "interval_min 범위 0~1440"}

    from agri_ai_core.src.ai.tools_auth import check_farm_access
    from agri_ai_core.src.postgresql.connection import db_session

    from agri_ai_core.src.ai.tools_utils import normalize_id as _normalize_id
    fid = _normalize_id(farm_id) or _normalize_id(auth_farm_id)
    if subscription_id is None and not fid:
        return {"success": False, "message": "farm_id 또는 subscription_id 가 필요합니다."}
    if fid:
        denied = check_farm_access(auth_farm_id, fid)
        if denied:
            return denied

    cd = interval_min if interval_min > 0 else None
    try:
        with db_session() as d:
            if subscription_id is not None:
                d.execute_query(
                    "UPDATE agent_subscriptions SET alert_cooldown_min=%s "
                    "WHERE id=%s AND active=TRUE", (cd, int(subscription_id)))
                targets = [int(subscription_id)]
            else:
                rows = d.fetch_all(
                    "SELECT id FROM agent_subscriptions WHERE active=TRUE AND farm_id=%s",
                    (fid,), as_dict=True) or []
                targets = [int(r["id"]) for r in rows]
                for t in targets:
                    d.execute_query(
                        "UPDATE agent_subscriptions SET alert_cooldown_min=%s WHERE id=%s",
                        (cd, t))
        # 실제 발송 관문(push_alert)이 이행하는 단일 정책에 기록 — 구독별 컬럼만
        # 갱신하면 send_user_alert 경로(구독 문맥 없음)에서 이행되지 않는다.
        from agri_ai_core.src.ai.kakao_notify import set_notify_cooldown
        set_notify_cooldown(cd)

        logger.info(f"[Agent Sub] 카카오 알림 간격 설정 {interval_min}분 → 구독 {targets}")
        _msg = (f"카카오 알림 최소 간격을 {interval_min}분으로 설정했습니다. "
                f"제어와 채팅 알림은 그대로 유지되고, 카카오 발송만 {interval_min}분에 1번으로 제한됩니다. "
                f"단 비상(critical) 알림은 간격과 무관하게 즉시 발송됩니다."
                if cd else "카카오 알림 쿨다운을 해제했습니다(매번 발송).")
        return {"success": True, "interval_min": interval_min,
                "affected_subscription_ids": targets, "message": _msg}
    except Exception as e:
        logger.warning(f"[Agent Sub] set_alert_interval 실패: {e}")
        return {"success": False, "message": str(e)}


# ────────────────────────────────────────────────────────────────────
# set_alert_level — 카카오 알림 최소 심각도 설정.
# "심각한 문제일 때만 알려줘" → level='critical', "경고 이상" → 'warning',
# "전부" → 'info'. 제어·채팅 알림은 그대로 유지되고 카카오 발송만 걸러진다.
# critical 은 어떤 설정에서도 항상 발송된다(비상 예외 — 농장주 지시).
# ────────────────────────────────────────────────────────────────────
def set_alert_level(*, level: str,
                    auth_farm_id: Optional[str] = None) -> Dict[str, Any]:
    lv = (level or "").strip().lower()
    _aliases = {"info": "info", "all": "info", "전체": "info", "모두": "info",
                "warning": "warning", "warn": "warning", "경고": "warning",
                "critical": "critical", "심각": "critical", "비상": "critical"}
    lv = _aliases.get(lv, lv)
    if lv not in ("info", "warning", "critical"):
        return {"success": False,
                "message": "level 은 info(전부) | warning(경고 이상) | critical(심각한 것만) 중 하나여야 합니다."}
    try:
        from agri_ai_core.src.ai.kakao_notify import set_notify_min_level
        if not set_notify_min_level(lv):
            return {"success": False, "message": "심각도 정책 기록에 실패했습니다."}
        _desc = {"info": "모든 알림을 카카오로 발송합니다.",
                 "warning": "경고 이상만 카카오로 발송합니다(정보성 알림은 카카오 미발송).",
                 "critical": "심각(비상) 알림만 카카오로 발송합니다."}[lv]
        logger.info(f"[Agent Sub] 카카오 알림 최소 심각도 설정 → {lv}")
        return {"success": True, "level": lv,
                "message": f"카카오 알림 최소 심각도를 {lv} 로 설정했습니다. {_desc} "
                           f"제어와 채팅 알림은 그대로 유지됩니다."}
    except Exception as e:
        logger.warning(f"[Agent Sub] set_alert_level 실패: {e}")
        return {"success": False, "message": str(e)}


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
