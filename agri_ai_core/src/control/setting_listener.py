# ════════════════════════════════════════════════════════════════════
# [Phase 5 · 2026-05-09] PostgreSQL LISTEN/NOTIFY 기반 즉시 변경 알림.
#
# 설계:
#   - DB 트리거(migration 004)가 setting 테이블 INSERT/UPDATE/DELETE 시
#     채널 'setting_changed' 로 NOTIFY 발화 (payload = {table, op, ts}).
#   - 본 모듈의 daemon thread 가 LISTEN 으로 수신 → table 별 callback 호출
#     (캐시 invalidate / 작업 재로드).
#   - 폴링 외 즉시 알림 — 변경 직후 다음 cycle 에서 새 값 사용.
#
# 호출 룰:
#   - startup.py 가 start() 1회 호출 (scheduler 프로세스 전용 권장).
#   - 다른 모듈은 register_callback(table, fn) 으로 추가 핸들러 등록.
# --->
# register_callback : 외부 모듈이 table 별 변경 callback 등록
# start             : daemon thread 시작 (idempotent)
# stop              : 그레이스풀 종료
# is_running        : 스레드 가동 상태
# _listen_loop      : 백그라운드 루프 — 재연결 자동
# _handle_notification : 수신 payload 파싱 + callback dispatch
# ════════════════════════════════════════════════════════════════════
import json
import select
import threading
import time
from typing import Callable, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# 기본 callback 매핑 (table_name → [func, ...]).
# register_callback() 으로 외부 모듈이 추가 등록 가능.
_CALLBACKS: Dict[str, List[Callable[[], None]]] = {}
_CALLBACKS_LOCK = threading.Lock()

_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None
_LISTEN_CHANNEL = 'setting_changed'
_RECONNECT_BACKOFF_SEC = 5


# ────────────────────────────────────────────────────────────────────
# 외부 모듈이 table 별 변경 callback 등록 (idempotent — 동일 callback 중복 X).
# ────────────────────────────────────────────────────────────────────
def register_callback(table_name: str, fn: Callable[[], None]) -> None:
    if not table_name or not callable(fn):
        return
    with _CALLBACKS_LOCK:
        lst = _CALLBACKS.setdefault(table_name, [])
        if fn not in lst:
            lst.append(fn)


# ────────────────────────────────────────────────────────────────────
# 등록된 callback 모두 제거 (테스트용).
# ────────────────────────────────────────────────────────────────────
def clear_callbacks() -> None:
    with _CALLBACKS_LOCK:
        _CALLBACKS.clear()


# ────────────────────────────────────────────────────────────────────
# 단일 NOTIFY payload 처리 — JSON 디코드 + 등록된 callback 모두 호출.
# 예외는 잡아 로그만 남김 (다른 callback / loop 영향 없음).
# ────────────────────────────────────────────────────────────────────
def _handle_notification(payload_str: str) -> None:
    try:
        payload = json.loads(payload_str)
    except Exception as e:
        logger.warning(f"[setting_listener] payload 파싱 실패 ({payload_str[:80]}): {e}")
        return
    table = payload.get('table')
    op = payload.get('op')
    if not table:
        return
    with _CALLBACKS_LOCK:
        cbs = list(_CALLBACKS.get(table, []))
    if not cbs:
        logger.debug(f"[setting_listener] {table} {op} — 등록된 callback 없음 (skip)")
        return
    for cb in cbs:
        try:
            cb()
        except Exception as ce:
            logger.warning(f"[setting_listener] callback 실패 {table}/{op}: {ce}")
    logger.info(f"[setting_listener] {table} {op} → callback {len(cbs)}건 실행")


# ────────────────────────────────────────────────────────────────────
# LISTEN 전용 raw connection 확보 — autocommit + 풀 외 별도 connection.
# 풀에서 빌리면 LISTEN 등록이 다른 cursor 사용 시 손실되므로 분리.
# ────────────────────────────────────────────────────────────────────
def _open_listen_connection():
    import psycopg2
    from agri_ai_core.config import settings as cfg
    db_cfg = cfg.database
    conn = psycopg2.connect(
        host=db_cfg.host, port=db_cfg.port,
        dbname=db_cfg.database, user=db_cfg.user, password=db_cfg.password,
    )
    conn.autocommit = True
    return conn


# ────────────────────────────────────────────────────────────────────
# 백그라운드 listen 루프 — 5초마다 stop 이벤트 검사 + 알림 폴링.
# 연결 끊김 시 자동 재연결 (backoff).
# ────────────────────────────────────────────────────────────────────
def _listen_loop() -> None:
    logger.info(f"[setting_listener] daemon thread 시작 (channel={_LISTEN_CHANNEL})")
    while _stop_event is not None and not _stop_event.is_set():
        try:
            conn = _open_listen_connection()
            with conn.cursor() as cur:
                cur.execute(f"LISTEN {_LISTEN_CHANNEL};")
            logger.info(f"[setting_listener] LISTEN {_LISTEN_CHANNEL} 등록 완료")

            while not _stop_event.is_set():
                if select.select([conn], [], [], 5) == ([], [], []):
                    continue   # 5초 timeout — stop_event 재검사
                conn.poll()
                while conn.notifies:
                    n = conn.notifies.pop(0)
                    _handle_notification(n.payload)
        except Exception as e:
            logger.warning(f"[setting_listener] 연결 실패 — {_RECONNECT_BACKOFF_SEC}초 후 재시도: {e}")
            # stop 이벤트 응답하면서 backoff
            for _ in range(_RECONNECT_BACKOFF_SEC):
                if _stop_event is not None and _stop_event.is_set():
                    break
                time.sleep(1)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    logger.info("[setting_listener] daemon thread 종료")


# ────────────────────────────────────────────────────────────────────
# 기본 callback 등록 — agri_ai_core 의 핵심 캐시들과 연결.
# import 사이클 방지 위해 callback 안에서 lazy import.
# ────────────────────────────────────────────────────────────────────
def _register_default_callbacks() -> None:
    def _invalidate_thresholds():
        from agri_ai_core.src.control import ai_thresholds
        ai_thresholds.clear_cache()

    def _invalidate_prompt_registry():
        from agri_ai_core.src import prompt_registry
        prompt_registry.clear_cache()

    def _reload_task_scheduler():
        # task_scheduler 의 polling job 이 다음 tick(<=30초) 에서 자동 reload 하지만
        # NOTIFY 수신 즉시 reload 호출하여 지연 0초 보장.
        from agri_ai_core.src.control import task_scheduler
        try:
            task_scheduler._reload_jobs_from_db()
        except Exception as e:
            logger.debug(f"[setting_listener] schedule reload 실패: {e}")

    register_callback('sensor_m_setting',     _invalidate_thresholds)
    register_callback('prompt_block_m',       _invalidate_prompt_registry)
    register_callback('tool_definition_m',    _invalidate_prompt_registry)
    register_callback('schedule_m_setting',   _reload_task_scheduler)
    # light_irrigation_s_setting / farm_m_info / farmhouse_m_info 는
    # 매 호출 DB 조회 패턴이라 별도 invalidate 불필요. 필요 시 추가 등록.


# ────────────────────────────────────────────────────────────────────
# daemon thread 시작 — idempotent. 기본 callback 자동 등록.
# ────────────────────────────────────────────────────────────────────
def start() -> bool:
    global _thread, _stop_event
    if _thread is not None and _thread.is_alive():
        logger.debug("[setting_listener] 이미 실행 중")
        return True
    _stop_event = threading.Event()
    _register_default_callbacks()
    _thread = threading.Thread(target=_listen_loop, daemon=True,
                               name='setting_listener')
    _thread.start()
    return True


# ────────────────────────────────────────────────────────────────────
# 그레이스풀 종료 — stop 이벤트 시그널 후 join.
# ────────────────────────────────────────────────────────────────────
def stop(timeout: float = 5.0) -> None:
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
    _thread = None
    _stop_event = None


# ────────────────────────────────────────────────────────────────────
# 가동 상태 (운영 진단용).
# ────────────────────────────────────────────────────────────────────
def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
