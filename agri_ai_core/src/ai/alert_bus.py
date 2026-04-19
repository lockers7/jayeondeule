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
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MAX_BUFFER = 200  # 최근 200건까지 보존
_buffer: deque = deque(maxlen=_MAX_BUFFER)
_subscribers: Set[asyncio.Queue] = set()
_lock = threading.Lock()
_loop_ref: Optional[asyncio.AbstractEventLoop] = None  # FastAPI 이벤트 루프 참조


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
