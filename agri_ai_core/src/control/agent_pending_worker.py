# ══════════════════════════════════════════════════════════════════════════════
# Agent Pending Worker — agent_pending_actions 큐 실행 데몬 (Phase 3) [2026-05-25]
#
# 동작:
#   매 AGENT_WORKER_POLL_SEC (기본 2) 초마다
#     SELECT ... FOR UPDATE SKIP LOCKED — status='pending' AND execute_at<=NOW()
#     도구별 dispatch → 실제 하드웨어/DB 변경
#     성공/실패 결과를 status + exec_result + executed_at 으로 기록
#
# 안전 정책 (비상가드 disable 상태에서 agent 가 유일한 자동 대응 경로):
#   · execute_at < NOW() — 30초 사용자 취소권 보장
#   · status='cancelled' 인 row 는 절대 실행 안 함
#   · set_relay 는 relay_manager.set_relay_value 인터록 게이트 통과 (자동 보장)
#   · 실행 실패는 status='failed' 로 기록하되 worker 자체는 죽지 않음
#
# 환경 변수:
#   AGENT_WORKER_POLL_SEC : polling 주기 (기본 2초)
#   AGENT_WORKER_BATCH    : 한 cycle 에 처리할 row 최대 (기본 10)
#
# 사용법:
#   python -m agri_ai_core.src.control.agent_pending_worker
#
# 파일 시작 함수 목록:
#   _claim_due_actions  : pending + execute_at 도달 row 를 SKIP LOCKED 로 claim
#   _mark_executed      : status='executed' + exec_result 기록
#   _mark_failed        : status='failed' + exec_result 기록
#   _exec_set_relay     : relay_manager 호출
#   _exec_set_threshold : sensor_m_setting UPDATE
#   _exec_set_growth    : tools_admin.set_growth_stage 호출
#   _exec_send_alert    : 알림 (Phase 4 SSE 도입 전엔 logger + DB only)
#   _execute_action     : dispatch
#   _on_signal          : SIGTERM 핸들러
#   main                : polling loop 엔트리포인트
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

AGENT_WORKER_POLL_SEC = int(os.getenv("AGENT_WORKER_POLL_SEC", "2"))
AGENT_WORKER_BATCH    = int(os.getenv("AGENT_WORKER_BATCH",    "10"))

_STOP = False


def _on_signal(signum, frame):
    global _STOP
    logger.info(f"[Agent Worker] signal {signum} 수신 — polling 종료")
    _STOP = True


# ────────────────────────────────────────────────────────────────────
# 큐에서 실행 시점 도달한 row 를 SKIP LOCKED 로 claim — 단일 트랜잭션
# ────────────────────────────────────────────────────────────────────
def _claim_due_actions(limit: int = 10) -> List[Dict[str, Any]]:
    try:
        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
    except Exception as e:
        logger.error(f"[Agent Worker] DB import 실패: {e}")
        return []

    sql = (
        "SELECT id, tool_name, args, reason, trigger_type, agent_log_id "
        "FROM agent_pending_actions "
        "WHERE status='pending' AND execute_at <= NOW() "
        "ORDER BY id "
        "FOR UPDATE SKIP LOCKED "
        "LIMIT %s"
    )
    conn = db._getconn()
    if conn is None:
        return []
    try:
        # SELECT FOR UPDATE 는 트랜잭션 안에서만 의미가 있음 — claim 후 즉시 commit
        # 해서 다른 worker 가 이 row 보지 못하게 status='in_progress' 같은 단계 추가도
        # 검토했으나, polling 주기 짧고 worker 단일 (Phase 3) 가정 → SKIP LOCKED 만으로
        # 충분. 다중 worker 도입 시 본 함수 +"UPDATE SET status='claimed'" 추가.
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
            conn.commit()
        return [dict(r) for r in rows] if rows else []
    except Exception as e:
        logger.warning(f"[Agent Worker] _claim_due_actions 실패: {e}")
        try: conn.rollback()
        except Exception: pass
        return []
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _update_status(action_id: int, status: str,
                   exec_result: Dict[str, Any]) -> None:
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    sql = (
        "UPDATE agent_pending_actions "
        "SET status=%s, executed_at=NOW(), exec_result=%s::jsonb "
        "WHERE id=%s AND status='pending'"
    )
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (status,
                              json.dumps(exec_result, ensure_ascii=False, default=str),
                              action_id))
            conn.commit()
    except Exception as e:
        logger.warning(f"[Agent Worker] _update_status({action_id}) 실패: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _mark_executed(action_id: int, result: Dict[str, Any]) -> None:
    _update_status(action_id, "executed", result)


def _mark_failed(action_id: int, result: Dict[str, Any]) -> None:
    _update_status(action_id, "failed", result)


# ────────────────────────────────────────────────────────────────────
# 도구별 실제 실행 — 각 함수는 {success, message, ...} 반환
# ────────────────────────────────────────────────────────────────────
def _exec_set_relay(args: Dict[str, Any]) -> Dict[str, Any]:
    from agri_ai_core.src.control.relay_manager import set_relay_value
    farm_id  = int(args["farm_id"])
    house_id = int(args["house_id"])
    semantic = args["semantic"]
    on       = bool(args["on"])
    # set_relay_value 는 raw_mode=False (시멘틱 부분갱신) + 인터록 게이트 자동 통과
    # skip_emergency_guard 는 default=True (2026-05-17 사용자 정책)
    try:
        ret = set_relay_value(farm_id, house_id, {semantic: on}, raw_mode=False)
        # set_relay_value 반환 형식은 (success_bool, message) 또는 dict — defensive
        if isinstance(ret, tuple):
            ok = bool(ret[0])
            msg = ret[1] if len(ret) > 1 else ""
        elif isinstance(ret, dict):
            ok = bool(ret.get("success", True))
            msg = ret.get("message", "")
        else:
            ok = bool(ret)
            msg = str(ret)
        return {"success": ok, "message": msg,
                "applied": {"semantic": semantic, "on": on}}
    except Exception as e:
        return {"success": False, "message": f"set_relay_value 예외: {e}"}


def _exec_set_threshold(args: Dict[str, Any]) -> Dict[str, Any]:
    from agri_ai_core.src.postgresql.connection import db
    farm_id  = int(args["farm_id"])
    house_id = int(args["house_id"])
    key      = args["key"]
    value    = float(args["value"])

    # 화이트리스트 (worker 단계 재검증 — DB 직접 변경이므로 SQL injection 방어)
    from agri_ai_core.src.ai.tools_agent_write import VALID_THRESHOLD_KEYS
    if key not in VALID_THRESHOLD_KEYS:
        return {"success": False, "message": f"key 부적합: {key}"}

    # sensor_m_setting 의 최신 setn_dttm row UPDATE — trigger 가 updt_dttm + NOTIFY 처리
    sql = (
        f"UPDATE sensor_m_setting SET {key}=%s "
        "WHERE farm_id=%s AND hous_id=%s AND setn_dttm = ("
        "  SELECT MAX(setn_dttm) FROM sensor_m_setting "
        "  WHERE farm_id=%s AND hous_id=%s"
        ")"
    )
    conn = db._getconn()
    if conn is None:
        return {"success": False, "message": "DB connection 실패"}
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (value, farm_id, house_id, farm_id, house_id))
            affected = cur.rowcount
            conn.commit()
        if affected == 0:
            return {"success": False, "message": "sensor_m_setting row 없음 (운영자 셋팅 권장)"}
        return {"success": True, "message": f"{key} → {value} 적용 ({affected} row)",
                "applied": {"key": key, "value": value, "rows": affected}}
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        return {"success": False, "message": f"UPDATE 예외: {e}"}
    finally:
        try: db._putconn(conn)
        except Exception: pass


def _exec_set_growth(args: Dict[str, Any]) -> Dict[str, Any]:
    from agri_ai_core.src.ai.tools_admin import set_growth_stage as admin_set_growth
    farm_id  = str(args["farm_id"])
    house_id = str(args["house_id"])
    stage    = args["stage"]
    try:
        # tools_admin.set_growth_stage 는 auth_farm_id 도 받음 — agent 실행은 farm_id 와 동일
        ret = admin_set_growth(house_id=house_id, stage=stage,
                               farm_id=farm_id, auth_farm_id=farm_id)
        if isinstance(ret, dict):
            return ret
        return {"success": bool(ret), "applied": {"stage": stage}}
    except Exception as e:
        return {"success": False, "message": f"set_growth_stage 예외: {e}"}


def _exec_send_alert(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 3 — 알림은 worker 가 큐 row 자체에 status=executed 로 기록만.
    Phase 4 에서 web 백엔드 SSE 채널로 푸시 추가.
    """
    level   = args.get("level", "info")
    message = args.get("message", "")
    # 운영자 즉시 인지 가능하도록 logger level 매핑
    log_method = {"info": logger.info, "warning": logger.warning,
                  "critical": logger.error}.get(level, logger.info)
    log_method(f"[Agent Alert/{level}] {message}")
    return {"success": True, "message": "alert delivered (log + queue row)",
            "delivered_via": "log"}


_DISPATCH = {
    "set_relay":        _exec_set_relay,
    "set_threshold":    _exec_set_threshold,
    "set_growth_stage": _exec_set_growth,
    "send_user_alert":  _exec_send_alert,
}


def _execute_action(row: Dict[str, Any]) -> None:
    action_id = int(row["id"])
    tool_name = row["tool_name"]
    args      = row["args"] or {}
    handler = _DISPATCH.get(tool_name)
    if handler is None:
        result = {"success": False, "message": f"unknown tool: {tool_name}"}
        _mark_failed(action_id, result)
        logger.warning(f"[Agent Worker] id={action_id} unknown tool {tool_name}")
        return

    started = time.time()
    try:
        result = handler(args)
    except Exception as e:
        result = {"success": False, "message": f"handler 예외: {e}"}
    duration = round(time.time() - started, 3)
    result["duration_sec"] = duration

    if result.get("success"):
        _mark_executed(action_id, result)
        logger.info(f"[Agent Worker] id={action_id} {tool_name} 실행 완료 "
                    f"({duration}s) — {result.get('message', '')}")
    else:
        _mark_failed(action_id, result)
        logger.warning(f"[Agent Worker] id={action_id} {tool_name} 실패 "
                       f"— {result.get('message', '')}")


# ────────────────────────────────────────────────────────────────────
# 메인 — polling loop
# ────────────────────────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT,  _on_signal)

    logger.info(
        f"[Agent Worker] 시작 poll={AGENT_WORKER_POLL_SEC}s "
        f"batch={AGENT_WORKER_BATCH}"
    )

    while not _STOP:
        try:
            rows = _claim_due_actions(AGENT_WORKER_BATCH)
            for row in rows:
                if _STOP:
                    break
                _execute_action(row)
        except Exception as e:
            logger.error(f"[Agent Worker] cycle 예외: {e}")

        # 종료 신호 빠르게 응답하기 위해 1초 단위 sleep
        slept = 0
        while slept < AGENT_WORKER_POLL_SEC and not _STOP:
            time.sleep(1)
            slept += 1

    logger.info("[Agent Worker] 정상 종료")


if __name__ == "__main__":
    sys.exit(main() or 0)
