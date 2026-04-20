# ══════════════════════════════════════════════════════════════════════════════
# 알림 버스 — AI 순환 루프/비상 제어에서 감지한 이벤트를 구독자(SSE)에게 push.
# 메모리 기반 ring buffer + asyncio.Queue 구독자 목록.
# --->
# publish: 이벤트 1건 발행 (모든 구독자에게 전파)
# subscribe: 구독자 등록 (asyncio.Queue 반환)
# unsubscribe: 구독자 해제
# get_recent: 최근 N건 조회 (신규 구독자가 놓친 이벤트 복구용)
# ══════════════════════════════════════════════════════════════════════════════
import asyncio
import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MAX_BUFFER = 200  # 최근 200건까지 보존 (메모리 ring buffer)
_buffer: deque = deque(maxlen=_MAX_BUFFER)
_subscribers: Set[asyncio.Queue] = set()
_lock = threading.Lock()
_loop_ref: Optional[asyncio.AbstractEventLoop] = None  # FastAPI 이벤트 루프 참조

# [E2] 영속 로깅 — alert_l_log 테이블 자동 생성 + DB 기록 (실패 시 조용히 삼켜
# 메모리 버퍼 경로는 그대로 유지. 기존 프로세스 훼손 금지 원칙 준수).
_PERSIST_ENABLED = os.getenv("ALERT_BUS_PERSIST", "1") not in ("0", "false", "False")
_PERSIST_MIN_LEVEL = os.getenv("ALERT_BUS_PERSIST_MIN_LEVEL", "warning")  # info/warning/critical
_LEVEL_ORDER = {"info": 0, "warning": 1, "critical": 2}
_table_ready = False
_table_ready_lock = threading.Lock()


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """FastAPI 시작 시 메인 이벤트 루프를 바인딩. manual_control(sync 스레드)에서 publish 할 때 사용."""
    global _loop_ref
    _loop_ref = loop
    logger.info("[alert_bus] FastAPI 이벤트 루프 바인딩 완료")


def publish(
    level: str,
    category: str,
    farm_id: Any,
    house_id: Any,
    title: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """알림 발행. sync 컨텍스트(AI 순환 루프 스레드)에서 호출해도 안전.

    Args:
        level: 'info' | 'warning' | 'critical'
        category: 'temp' | 'humidity' | 'co2' | 'water' | 'control' | 'system'
        farm_id, house_id: 대상 식별자
        title: 짧은 제목 (50자 이내)
        message: 설명문 (1~3줄)
        data: 추가 구조화 데이터 (선택)

    Returns:
        발행된 이벤트 dict
    """
    evt = {
        "id": f"alt_{int(time.time()*1000)}",
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "category": category,
        "farm_id": str(farm_id) if farm_id is not None else None,
        "house_id": str(house_id) if house_id is not None else None,
        "title": title,
        "message": message,
        "data": data or {},
    }

    with _lock:
        _buffer.append(evt)
        subs = list(_subscribers)

    # [E2] 영속 DB 로깅 (warning 이상). 실패해도 기존 경로 영향 없음.
    _persist_event(evt)

    # sync 스레드에서 호출된 경우 asyncio.Queue.put_nowait 는 별도 루프가 필요
    for q in subs:
        try:
            if _loop_ref and _loop_ref.is_running():
                _loop_ref.call_soon_threadsafe(_safe_put, q, evt)
            else:
                # 폴백: 로컬 루프 시도
                try:
                    q.put_nowait(evt)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[alert_bus] 구독자 push 실패: {e}")

    logger.info(f"[ALERT {level.upper()}] {category}/house={house_id}: {title}")
    return evt


def _safe_put(queue: asyncio.Queue, evt: Dict[str, Any]) -> None:
    try:
        queue.put_nowait(evt)
    except asyncio.QueueFull:
        # 만석이면 가장 오래된 것 제거 후 삽입
        try:
            queue.get_nowait()
            queue.put_nowait(evt)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# [E2] 비상 알림 PostgreSQL 영속 로깅 (선택적)
# alert_l_log 테이블 — 서비스 재시작 시에도 과거 critical/warning 이력 보존
# ═══════════════════════════════════════════════════════════════════════════
_CREATE_ALERT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alert_l_log (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL,
    recd_dttm TIMESTAMP NOT NULL DEFAULT NOW(),
    level VARCHAR(16) NOT NULL,
    category VARCHAR(64) NOT NULL,
    farm_id VARCHAR(32),
    hous_id VARCHAR(32),
    title TEXT,
    message TEXT,
    data JSONB
);
CREATE INDEX IF NOT EXISTS idx_alert_l_log_dttm ON alert_l_log(recd_dttm DESC);
CREATE INDEX IF NOT EXISTS idx_alert_l_log_farm_level ON alert_l_log(farm_id, level, recd_dttm DESC);
"""


def _ensure_alert_table():
    """alert_l_log 테이블 lazy 생성. 실패해도 메모리 버퍼 경로는 영향 없음."""
    global _table_ready
    if _table_ready:
        return True
    with _table_ready_lock:
        if _table_ready:
            return True
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            with db_session() as db:
                db.execute_query(_CREATE_ALERT_TABLE_SQL, ())
            _table_ready = True
            logger.info("[alert_bus] alert_l_log 영속 테이블 준비 완료")
            return True
        except Exception as e:
            logger.warning(f"[alert_bus] alert_l_log 테이블 준비 실패 (메모리 버퍼만 사용): {e}")
            return False


def _persist_event(evt: Dict[str, Any]) -> None:
    """비상 알림을 DB 에 INSERT. 레벨 필터 + 예외 흡수."""
    if not _PERSIST_ENABLED:
        return
    evt_level = (evt.get("level") or "info").lower()
    if _LEVEL_ORDER.get(evt_level, 0) < _LEVEL_ORDER.get(_PERSIST_MIN_LEVEL, 1):
        return   # 설정된 최소 레벨 미만은 저장 생략 (기본: info 저장 안 함)
    if not _ensure_alert_table():
        return
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        payload = evt.get("data") or {}
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        with db_session() as db:
            db.execute_query(
                "INSERT INTO alert_l_log (event_id, recd_dttm, level, category, "
                "farm_id, hous_id, title, message, data) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    evt.get("id"),
                    evt.get("timestamp"),
                    evt_level,
                    evt.get("category"),
                    evt.get("farm_id"),
                    evt.get("house_id"),
                    evt.get("title"),
                    evt.get("message"),
                    payload_json,
                ),
            )
    except Exception as e:
        # DB 실패가 알림 발행을 막아서는 안 됨 (기존 프로세스 훼손 금지)
        logger.debug(f"[alert_bus] DB INSERT 실패: {e}")


def subscribe(maxsize: int = 100) -> asyncio.Queue:
    """신규 구독자 등록. 반환된 Queue를 SSE handler가 consume."""
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    with _lock:
        _subscribers.add(q)
    logger.info(f"[alert_bus] 구독자 등록 (현재 {len(_subscribers)}명)")
    return q


def unsubscribe(queue: asyncio.Queue) -> None:
    with _lock:
        _subscribers.discard(queue)
    logger.info(f"[alert_bus] 구독자 해제 (남은 {len(_subscribers)}명)")


def get_recent(limit: int = 50, level: Optional[str] = None) -> List[Dict[str, Any]]:
    """최근 알림 N건 조회. level 지정 시 해당 수준 이상만."""
    with _lock:
        items = list(_buffer)
    if level:
        order = {"info": 0, "warning": 1, "critical": 2}
        min_rank = order.get(level, 0)
        items = [e for e in items if order.get(e.get("level"), 0) >= min_rank]
    return items[-limit:]
