# ══════════════════════════════════════════════════════════════════════════════
# Agent API Router — Phase 4 web UI 백엔드 (REST) [2026-05-25]
#
# 사용자/운영자가 채팅창 외부에서 agent 이력·큐·구독·알림을 직접 조회/제어.
# 채팅 LLM 도구(tools_agent_sub) 와 *동일 함수* 호출 — 코드 중복 없음.
#
# Endpoint 6개:
#   GET    /api/v1/agent/history           — agent_decision_log 조회 (페이지네이션)
#   GET    /api/v1/agent/pending           — agent_pending_actions 큐 조회
#   POST   /api/v1/agent/pending/{id}/cancel — pending action 취소
#   POST   /api/v1/agent/trigger           — 수동 1회 ReAct 분석
#   GET    /api/v1/agent/subscriptions     — 구독 목록
#   POST   /api/v1/agent/subscribe         — 신규 구독 등록
#   POST   /api/v1/agent/subscriptions/{id}/cancel — 구독 취소
#   GET    /api/v1/agent/alerts            — 사용자 알림 조회 + mark_read
#
# 파일 시작 함수 목록:
#   get_history          : 사이클 이력 조회
#   get_pending          : 큐 조회
#   cancel_pending       : 큐 항목 취소
#   trigger_oneshot      : 1회 ReAct 분석 (백그라운드 + 결과 polling)
#   list_subs            : 구독 목록
#   create_sub           : 신규 구독
#   cancel_sub           : 구독 취소
#   get_alerts           : 알림 조회 + mark_read
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

agent_router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


# ════════════════════════════════════════════════════════════════════
# 1) GET /history — agent_decision_log 조회
# ════════════════════════════════════════════════════════════════════
@agent_router.get("/history")
def get_history(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    trigger_type: Optional[str] = Query(None, description="schedule/subscription/user/event"),
    farm_id: Optional[int] = Query(None),
    only_success: Optional[bool] = Query(None),
) -> Dict[str, Any]:
    """사이클 이력 — 최신순. JSONB steps 제외 (가벼움)."""
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        where = ["1=1"]
        vals: List[Any] = []
        if trigger_type:
            where.append("trigger_type=%s"); vals.append(trigger_type)
        if farm_id is not None:
            where.append("farm_id=%s"); vals.append(int(farm_id))
        if only_success is not None:
            where.append("success=%s"); vals.append(bool(only_success))
        sql = (
            "SELECT id, started_at, ended_at, trigger_type, farm_id, "
            "       success, reason, duration_sec, llm_calls, tool_calls, model, "
            "       LEFT(final_report, 500) AS final_preview, "
            "       LEFT(task, 300) AS task "
            f"FROM agent_decision_log WHERE {' AND '.join(where)} "
            "ORDER BY id DESC LIMIT %s OFFSET %s"
        )
        with db_session() as d:
            rows = d.fetch_all(sql, tuple(vals) + (limit, offset), as_dict=True)
            count_row = d.fetch_one(
                f"SELECT COUNT(*) AS c FROM agent_decision_log WHERE {' AND '.join(where)}",
                tuple(vals))
        total = int(count_row["c"]) if count_row else 0
        items = [{
            "id": int(r["id"]),
            "started_at": str(r["started_at"]) if r["started_at"] else None,
            "ended_at": str(r["ended_at"]) if r["ended_at"] else None,
            "trigger_type": r["trigger_type"],
            "farm_id": r["farm_id"],
            "success": r["success"],
            "reason": r["reason"],
            "duration_sec": float(r["duration_sec"]) if r["duration_sec"] else None,
            "llm_calls": r["llm_calls"],
            "tool_calls": r["tool_calls"],
            "model": r["model"],
            "task": r["task"],
            "final_preview": r["final_preview"],
        } for r in (rows or [])]
        return {"success": True, "total": total, "limit": limit, "offset": offset,
                "items": items}
    except Exception as e:
        logger.warning(f"[Agent API] get_history 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 2) GET /history/{id} — 단일 사이클 상세 (steps 포함)
# ════════════════════════════════════════════════════════════════════
@agent_router.get("/history/{log_id}")
def get_history_detail(log_id: int) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                "SELECT id, started_at, ended_at, trigger_type, farm_id, task, "
                "       steps, final_report, success, reason, duration_sec, "
                "       llm_calls, tool_calls, model "
                "FROM agent_decision_log WHERE id=%s", (log_id,))
        if not row:
            raise HTTPException(status_code=404, detail=f"id={log_id} 없음")
        return {
            "success": True,
            "id": int(row["id"]),
            "started_at": str(row["started_at"]),
            "ended_at": str(row["ended_at"]) if row["ended_at"] else None,
            "trigger_type": row["trigger_type"],
            "farm_id": row["farm_id"],
            "task": row["task"],
            "steps": row["steps"],
            "final_report": row["final_report"],
            "success": row["success"],
            "reason": row["reason"],
            "duration_sec": float(row["duration_sec"]) if row["duration_sec"] else None,
            "llm_calls": row["llm_calls"],
            "tool_calls": row["tool_calls"],
            "model": row["model"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Agent API] history detail 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 3) GET /pending — agent_pending_actions 큐 조회
# ════════════════════════════════════════════════════════════════════
@agent_router.get("/pending")
def get_pending(
    status: Optional[str] = Query(None, description="pending/executed/cancelled/failed"),
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        where = ["1=1"]
        vals: List[Any] = []
        if status:
            where.append("status=%s"); vals.append(status)
        sql = (
            "SELECT id, created_at, execute_at, agent_log_id, trigger_type, "
            "       tool_name, args, reason, status, executed_at, exec_result, "
            "       cancelled_by, cancelled_reason "
            f"FROM agent_pending_actions WHERE {' AND '.join(where)} "
            "ORDER BY id DESC LIMIT %s"
        )
        with db_session() as d:
            rows = d.fetch_all(sql, tuple(vals) + (limit,), as_dict=True)
        items = [{
            "id": int(r["id"]),
            "created_at": str(r["created_at"]),
            "execute_at": str(r["execute_at"]),
            "agent_log_id": r["agent_log_id"],
            "trigger_type": r["trigger_type"],
            "tool_name": r["tool_name"],
            "args": r["args"],
            "reason": r["reason"],
            "status": r["status"],
            "executed_at": str(r["executed_at"]) if r["executed_at"] else None,
            "exec_result": r["exec_result"],
            "cancelled_by": r["cancelled_by"],
            "cancelled_reason": r["cancelled_reason"],
        } for r in (rows or [])]
        return {"success": True, "count": len(items), "items": items}
    except Exception as e:
        logger.warning(f"[Agent API] get_pending 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 4) POST /pending/{id}/cancel — 큐 항목 취소
# ════════════════════════════════════════════════════════════════════
class CancelPendingRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="취소 주체 식별")
    reason: Optional[str] = Field(None, description="취소 사유 (운영 로그용)")


@agent_router.post("/pending/{action_id}/cancel")
def cancel_pending(action_id: int, req: Optional[CancelPendingRequest] = None) -> Dict[str, Any]:
    user_id = (req.user_id if req else None) or "user"
    reason = (req.reason if req else None) or "수동 취소"
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(status_code=500, detail="DB connection 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_pending_actions "
                    "SET status='cancelled', cancelled_by=%s, cancelled_reason=%s "
                    "WHERE id=%s AND status='pending' "
                    "RETURNING id",
                    (f"user:{user_id}", reason, action_id))
                row = cur.fetchone()
                conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if not row:
            raise HTTPException(status_code=404,
                                detail=f"id={action_id} 의 pending 항목 없음 또는 이미 처리됨")
        return {"success": True, "action_id": action_id,
                "message": f"action {action_id} 취소 완료"}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Agent API] cancel_pending({action_id}) 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 5) POST /trigger — 수동 1회 ReAct 분석 (동기, 100~250초 소요)
# ════════════════════════════════════════════════════════════════════
class TriggerRequest(BaseModel):
    task: str = Field(..., description="agent 가 수행할 작업 (한국어 한 문장)")
    farm_id: int = Field(1, description="농장 ID")


@agent_router.post("/trigger")
def trigger_oneshot(req: TriggerRequest) -> Dict[str, Any]:
    """동기 호출 — agent ReAct 1 사이클 완료 후 결과 반환. 100~250초 소요."""
    try:
        from agri_ai_core.src.control.ai_monitor_agent import run_agent
        result = run_agent(task=req.task.strip(), farm_id=int(req.farm_id),
                           trigger_type="user")
        return {
            "success": bool(result.get("success")),
            "log_id": result.get("log_id"),
            "duration_sec": result.get("duration_sec"),
            "steps": len(result.get("steps", [])),
            "final": result.get("final"),
            "reason": result.get("reason"),
        }
    except Exception as e:
        logger.warning(f"[Agent API] trigger 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 6) GET /subscriptions — 구독 목록
# ════════════════════════════════════════════════════════════════════
@agent_router.get("/subscriptions")
def list_subs(
    user_id: Optional[str] = Query(None),
    include_default: bool = Query(False, description="default __default_cron__ 포함"),
) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_agent_sub import list_agent_subscriptions
        return list_agent_subscriptions(user_id=user_id, include_default=include_default)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 7) POST /subscribe — 신규 구독 등록
# ════════════════════════════════════════════════════════════════════
class SubscribeRequest(BaseModel):
    task: str = Field(..., description="매 사이클 수행할 작업")
    interval_min: int = Field(..., ge=5, le=1440, description="사이클 주기 분")
    farm_id: int = Field(1)
    house_id: Optional[int] = Field(None)
    user_id: Optional[str] = Field(None, description="발신자 식별")
    intent: Optional[str] = Field(None, description="원본 자연어")


@agent_router.post("/subscribe")
def create_sub(req: SubscribeRequest) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_agent_sub import agent_subscribe
        r = agent_subscribe(
            task=req.task, interval_min=req.interval_min,
            farm_id=req.farm_id, house_id=req.house_id,
            user_id=req.user_id, intent=req.intent)
        if not r.get("success"):
            raise HTTPException(status_code=400, detail=r.get("message"))
        return r
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 8) POST /subscriptions/{id}/cancel — 구독 취소
# ════════════════════════════════════════════════════════════════════
class CancelSubRequest(BaseModel):
    user_id: Optional[str] = Field(None)
    reason: Optional[str] = Field(None)


@agent_router.post("/subscriptions/{sub_id}/cancel")
def cancel_sub(sub_id: int, req: Optional[CancelSubRequest] = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_agent_sub import cancel_agent_subscription
        user_id = req.user_id if req else None
        reason = req.reason if req else None
        r = cancel_agent_subscription(subscription_id=sub_id,
                                      user_id=user_id, reason=reason)
        if not r.get("success"):
            raise HTTPException(status_code=400, detail=r.get("message"))
        return r
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 9) GET /alerts — 사용자 알림 조회 + mark_read
# ════════════════════════════════════════════════════════════════════
@agent_router.get("/alerts")
def get_alerts(
    user_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    mark_read: bool = Query(True, description="조회 시 read 처리"),
) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_agent_sub import get_pending_alerts
        return get_pending_alerts(user_id=user_id, limit=limit, mark_read=mark_read)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════
# 10) GET /stream — SSE 알림 실시간 push (Phase 4 W-4)
#
# 채팅 프론트엔드 또는 admin 대시보드가 EventSource 로 구독.
# 새 unread 알림 발생 시 즉시 push (5초 polling, 클라이언트 입장에선 push).
#
# 클라이언트 사용 예:
#   const es = new EventSource('/api/v1/agent/stream?user_id=foo');
#   es.addEventListener('alert', e => console.log(JSON.parse(e.data)));
# ════════════════════════════════════════════════════════════════════
import asyncio
import json

from fastapi import Request
from fastapi.responses import StreamingResponse


SSE_POLL_INTERVAL_SEC = 5    # DB polling 주기
SSE_HEARTBEAT_SEC = 30        # 30초 무알림 시 heartbeat
SSE_MAX_DURATION_SEC = 3600   # 최대 1시간 연결 (proxy timeout 고려)


async def _alerts_event_generator(request: Request,
                                   user_id: Optional[str],
                                   since_id: int = 0):
    """unread 알림을 SSE 로 푸시. 클라이언트 끊김 감지 시 즉시 종료."""
    from agri_ai_core.src.postgresql.connection import db
    start_ts = asyncio.get_event_loop().time()
    last_heartbeat = start_ts
    last_max_id = since_id

    # 초기 hello
    yield f"event: hello\ndata: {json.dumps({'user_id': user_id, 'since_id': since_id})}\n\n"

    while True:
        # 클라이언트 연결 끊겼는지
        if await request.is_disconnected():
            logger.info(f"[Agent SSE] client disconnected user={user_id}")
            break

        # 최대 연결 시간 초과 (proxy 가 강제로 끊기 전에 자발 종료)
        now = asyncio.get_event_loop().time()
        if now - start_ts > SSE_MAX_DURATION_SEC:
            yield "event: max_duration\ndata: {}\n\n"
            break

        # DB polling
        try:
            conn = db._getconn()
            if conn:
                try:
                    with conn.cursor() as cur:
                        if user_id:
                            cur.execute(
                                "SELECT id, created_at, user_id, subscription_id, "
                                "       agent_log_id, level, title, body "
                                "FROM agent_user_alerts "
                                "WHERE id > %s AND read_at IS NULL "
                                "  AND (user_id IS NULL OR user_id=%s) "
                                "ORDER BY id LIMIT 20",
                                (last_max_id, user_id))
                        else:
                            cur.execute(
                                "SELECT id, created_at, user_id, subscription_id, "
                                "       agent_log_id, level, title, body "
                                "FROM agent_user_alerts "
                                "WHERE id > %s AND read_at IS NULL "
                                "ORDER BY id LIMIT 20",
                                (last_max_id,))
                        rows = cur.fetchall()
                finally:
                    try: db._putconn(conn)
                    except Exception: pass
            else:
                rows = []

            for row in rows:
                aid, created, uid, sub_id, log_id, level, title, body = row
                last_max_id = max(last_max_id, int(aid))
                payload = {
                    "id": int(aid),
                    "created_at": str(created),
                    "user_id": uid,
                    "subscription_id": sub_id,
                    "agent_log_id": log_id,
                    "level": level,
                    "title": title,
                    "body": body,
                }
                yield f"event: alert\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_heartbeat = now
        except Exception as e:
            logger.warning(f"[Agent SSE] polling 예외: {e}")

        # heartbeat — 30초 무알림 시 keepalive
        if now - last_heartbeat > SSE_HEARTBEAT_SEC:
            yield f": heartbeat {int(now)}\n\n"
            last_heartbeat = now

        await asyncio.sleep(SSE_POLL_INTERVAL_SEC)


@agent_router.get("/stream")
async def stream_alerts(
    request: Request,
    user_id: Optional[str] = Query(None),
    since_id: int = Query(0, ge=0, description="이 id 보다 큰 알림만 push"),
):
    """Server-Sent Events — agent_user_alerts unread row 실시간 push.

    클라이언트는 `since_id` 를 마지막 받은 id 로 지정해 재연결 시 누락 방지.
    """
    return StreamingResponse(
        _alerts_event_generator(request, user_id, since_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx buffering 비활성
        },
    )
