# ════════════════════════════════════════════════════════════════════
# agent_event_listener — 이벤트 트리거 LISTEN daemon
#
# 설계:
#   PostgreSQL 채널 'agent_event' 를 LISTEN.
#   migration 008 의 DB 트리거가 아래 이벤트 발생 시 NOTIFY:
#     · sensor_threshold  : 센서값이 임계 ±10% 버퍼 진입
#     · llm_keep_streak   : 동일 호기에서 LLM keep 5회 연속
#
#   수신 즉시 해당 farm_id 의 default agent_subscriptions 에
#     next_run_at = NOW()
#   을 UPDATE → agent_scheduler 의 다음 polling(~60초)에서 run_agent 실행.
#   사용자 주기 구독은 요청 주기를 보존해야 하므로 기본값으로 즉시화하지 않는다.
#
#   추가로 Python 측에서 주기적(HEARTBEAT_CHECK_SEC, 기본 5분) 으로
#   sensor_l_recording 의 최신 INSERT 시각을 폴링 → 5분 이상 공백이면
#   직접 이벤트 처리 (DB INSERT 0건 5분+ 감지 이벤트).
#
# 실행:
#   python -m agri_ai_core.src.control.agent_event_listener
#   또는 systemd unit agent_event_listener.service 로 관리.
#
# 환경변수:
#   AGENT_EVENT_FARM_IDS        : 모니터링 농장 ID 쉼표 구분 (기본 "1")
#   AGENT_EVENT_COOLDOWN_SEC    : 동일 이벤트 재발화 억제 초 (기본 300)
#   AGENT_EVENT_HEARTBEAT_SEC   : DB 단절 체크 주기 초 (기본 300)
#   AGENT_EVENT_RECONNECT_SEC   : 재연결 backoff 초 (기본 5)
# --->
# _open_listen_conn         : LISTEN 전용 autocommit 커넥션 생성
# _trigger_subscriptions    : farm_id 의 active subscription next_run_at 즉시 화
# _handle_event             : NOTIFY payload 파싱 + 쿨다운 + trigger 호출
# _heartbeat_check_loop     : 별도 thread — DB 단절 주기 감시
# _listen_loop              : 메인 LISTEN loop (재연결 포함)
# main                      : 엔트리포인트 — signal 등록 + 두 루프 기동
# ════════════════════════════════════════════════════════════════════
import json
import os
import select
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

# ── 환경변수 ──────────────────────────────────────────────────────────
AGENT_EVENT_FARM_IDS = [
    int(x.strip())
    for x in os.getenv("AGENT_EVENT_FARM_IDS", "1").split(",")
    if x.strip()
]
AGENT_EVENT_COOLDOWN_SEC   = int(os.getenv("AGENT_EVENT_COOLDOWN_SEC",  "300"))
AGENT_EVENT_HEARTBEAT_SEC  = int(os.getenv("AGENT_EVENT_HEARTBEAT_SEC", "300"))
AGENT_EVENT_RECONNECT_SEC  = int(os.getenv("AGENT_EVENT_RECONNECT_SEC",  "5"))
AGENT_EVENT_TRIGGER_USER_SUBS = os.getenv("AGENT_EVENT_TRIGGER_USER_SUBS", "0") == "1"

_LISTEN_CHANNEL = "agent_event"

# 쿨다운 상태 — 키: (event_type, farm_id, house_id) / 값: 마지막 발화 epoch
_cooldown: dict = {}
_cooldown_lock = threading.Lock()

# 종료 신호
_stop_event = threading.Event()


# ────────────────────────────────────────────────────────────────────
# LISTEN 전용 커넥션 — 풀 공유 불가(LISTEN 등록이 풀 반환 시 소실).
# autocommit=True 필수 (트랜잭션 블록 내에서 LISTEN 미작동).
# ────────────────────────────────────────────────────────────────────
def _open_listen_conn():
    import psycopg2
    from agri_ai_core.config import settings as cfg
    db_cfg = cfg.database
    conn = psycopg2.connect(
        host=db_cfg.host,
        port=db_cfg.port,
        dbname=db_cfg.database,
        user=db_cfg.user,
        password=db_cfg.password,
    )
    conn.autocommit = True
    return conn


# ────────────────────────────────────────────────────────────────────
# farm_id 의 default agent_subscriptions next_run_at = NOW() 업데이트.
# 사용자 주기 구독은 기본적으로 요청 주기를 유지한다.
# ────────────────────────────────────────────────────────────────────
def _trigger_subscriptions(farm_id: int, house_id: Optional[int], event_type: str) -> int:
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception as e:
        logger.warning(f"[EventListener] DB import 실패: {e}")
        return 0

    conn = db._getconn()
    if conn is None:
        logger.debug(f"[EventListener] DB 커넥션 획득 실패 (farm={farm_id}) — 다음 이벤트 시 재시도")
        return 0
    try:
        with conn.cursor() as cur:
            # house_id 가 있으면 해당 호기 + 전체(NULL) subscription 모두 즉시화
            if house_id is not None:
                user_filter = "" if AGENT_EVENT_TRIGGER_USER_SUBS else "  AND intent = '__default_cron__' "
                cur.execute(
                    "UPDATE agent_subscriptions "
                    "SET next_run_at = NOW() "
                    "WHERE active = TRUE "
                    "  AND farm_id = %s "
                    "  AND (house_id = %s OR house_id IS NULL) "
                    f"{user_filter}"
                    "  AND next_run_at > NOW()",
                    (farm_id, house_id),
                )
            else:
                user_filter = "" if AGENT_EVENT_TRIGGER_USER_SUBS else "  AND intent = '__default_cron__' "
                cur.execute(
                    "UPDATE agent_subscriptions "
                    "SET next_run_at = NOW() "
                    "WHERE active = TRUE "
                    "  AND farm_id = %s "
                    f"{user_filter}"
                    "  AND next_run_at > NOW()",
                    (farm_id,),
                )
            updated = cur.rowcount
            conn.commit()
        if updated > 0:
            logger.info(
                f"[EventListener] 이벤트={event_type} farm={farm_id} house={house_id} "
                f"→ subscription {updated}건 next_run_at 즉시화"
            )
        else:
            logger.debug(
                f"[EventListener] 이벤트={event_type} farm={farm_id} — "
                f"즉시화 대상 subscription 없음 (이미 due 또는 미등록)"
            )
        return updated
    except Exception as e:
        logger.warning(f"[EventListener] _trigger_subscriptions 실패: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            db._putconn(conn)
        except Exception:
            pass


# ────────────────────────────────────────────────────────────────────
# NOTIFY payload 처리 — JSON 파싱 + 쿨다운 체크 + subscription 즉시화.
# 예외는 잡아 루프를 보호.
# ────────────────────────────────────────────────────────────────────
def _handle_event(payload_str: str) -> None:
    try:
        payload = json.loads(payload_str)
    except Exception as e:
        logger.debug(f"[EventListener] payload 파싱 skip ({payload_str[:80]}): {e}")
        return

    event_type = payload.get("event")
    farm_id    = payload.get("farm_id")
    house_id   = payload.get("house_id")

    if not event_type or farm_id is None:
        logger.debug(f"[EventListener] 필수 필드 누락 — 스킵: {payload_str[:80]}")
        return

    # farm_id 가 모니터링 대상 아니면 스킵
    if int(farm_id) not in AGENT_EVENT_FARM_IDS:
        logger.debug(f"[EventListener] farm={farm_id} — 모니터링 대상 아님")
        return

    # 쿨다운 체크 — 같은 (event, farm, house) 가 COOLDOWN 초 내 재발화 억제
    cooldown_key = (event_type, int(farm_id), house_id)
    now_ts = time.time()
    with _cooldown_lock:
        last_ts = _cooldown.get(cooldown_key, 0.0)
        if now_ts - last_ts < AGENT_EVENT_COOLDOWN_SEC:
            remaining = int(AGENT_EVENT_COOLDOWN_SEC - (now_ts - last_ts))
            logger.debug(
                f"[EventListener] 쿨다운 중 — {event_type} farm={farm_id} "
                f"house={house_id} 잔여 {remaining}초"
            )
            return
        _cooldown[cooldown_key] = now_ts

    # 이벤트 유형별 로그
    if event_type == "sensor_threshold":
        sensor    = payload.get("sensor", "?")
        value     = payload.get("value")
        threshold = payload.get("threshold")
        direction = payload.get("direction", "?")
        logger.info(
            f"[EventListener] 센서 임계 근접 — farm={farm_id} house={house_id} "
            f"sensor={sensor} value={value} threshold={threshold} direction={direction}"
        )
    elif event_type == "llm_keep_streak":
        streak = payload.get("streak", 5)
        logger.info(
            f"[EventListener] LLM keep 연속 {streak}회 — farm={farm_id} house={house_id}"
        )
    elif event_type == "db_no_insert":
        minutes = payload.get("minutes", "?")
        logger.warning(
            f"[EventListener] DB INSERT 없음 {minutes}분+ — farm={farm_id} house={house_id}"
        )
    else:
        logger.info(f"[EventListener] 알 수 없는 이벤트={event_type} payload={payload_str[:120]}")

    # subscription 즉시화
    _trigger_subscriptions(
        farm_id=int(farm_id),
        house_id=int(house_id) if house_id is not None else None,
        event_type=event_type,
    )


# ────────────────────────────────────────────────────────────────────
# heartbeat 감시 루프 — AGENT_EVENT_HEARTBEAT_SEC 마다 각 farm/house 의
# sensor_l_recording 최신 INSERT 시각 체크.
# 5분 이상 공백 감지 시 _handle_event 로 직접 이벤트 주입.
# ────────────────────────────────────────────────────────────────────
def _heartbeat_check_loop() -> None:
    logger.info(
        f"[EventListener] heartbeat 감시 시작 "
        f"(주기={AGENT_EVENT_HEARTBEAT_SEC}초 / farms={AGENT_EVENT_FARM_IDS})"
    )
    while not _stop_event.is_set():
        # HEARTBEAT_CHECK_SEC 동안 1초 단위로 stop 체크
        for _ in range(AGENT_EVENT_HEARTBEAT_SEC):
            if _stop_event.is_set():
                break
            time.sleep(1)
        if _stop_event.is_set():
            break

        try:
            _run_heartbeat_check()
        except Exception as e:
            logger.warning(f"[EventListener] heartbeat 체크 예외: {e}")

    logger.info("[EventListener] heartbeat 감시 종료")


def _run_heartbeat_check() -> None:
    try:
        from agri_ai_core.src.postgresql.connection import db
    except Exception:
        return
    conn = db._getconn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for farm_id in AGENT_EVENT_FARM_IDS:
                # 각 farm 내 호기별 최신 INSERT 시각 조회.
                # hous_id=0(공통/가상 호기 — 코드베이스 관례상 제외 대상)은 감시 제외.
                cur.execute(
                    "SELECT hous_id, MAX(recd_dttm) AS last_ts "
                    "FROM sensor_l_recording "
                    "WHERE farm_id = %s AND hous_id != 0 "
                    "GROUP BY hous_id",
                    (farm_id,),
                )
                rows = cur.fetchall()
                for row in rows:
                    house_id = row[0]
                    last_ts: Optional[datetime] = row[1]
                    if last_ts is None:
                        continue
                    gap_sec = (datetime.now() - last_ts).total_seconds()
                    # 5분(300초) 이상 공백
                    if gap_sec >= AGENT_EVENT_HEARTBEAT_SEC:
                        minutes = int(gap_sec // 60)
                        synthetic = json.dumps({
                            "event":    "db_no_insert",
                            "farm_id":  farm_id,
                            "house_id": house_id,
                            "minutes":  minutes,
                        })
                        logger.warning(
                            f"[EventListener] 데이터 단절 감지 farm={farm_id} "
                            f"house={house_id} — {minutes}분 공백"
                        )
                        _handle_event(synthetic)
        conn.commit()
    except Exception as e:
        logger.warning(f"[EventListener] _run_heartbeat_check 쿼리 실패: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            db._putconn(conn)
        except Exception:
            pass


# ────────────────────────────────────────────────────────────────────
# 메인 LISTEN 루프 — 연결 실패/끊김 시 backoff 후 재연결.
# select() 5초 타임아웃으로 stop_event 즉시 반응.
# ────────────────────────────────────────────────────────────────────
def _listen_loop() -> None:
    logger.info(
        f"[EventListener] LISTEN 루프 시작 (channel={_LISTEN_CHANNEL} "
        f"cooldown={AGENT_EVENT_COOLDOWN_SEC}초)"
    )
    conn = None
    while not _stop_event.is_set():
        try:
            conn = _open_listen_conn()
            with conn.cursor() as cur:
                cur.execute(f"LISTEN {_LISTEN_CHANNEL};")
            logger.info(f"[EventListener] LISTEN {_LISTEN_CHANNEL} 등록 완료")

            while not _stop_event.is_set():
                # 5초 타임아웃 — stop_event 즉시 반응 보장
                if select.select([conn], [], [], 5.0) == ([], [], []):
                    continue
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    _handle_event(notify.payload)

        except Exception as e:
            logger.warning(
                f"[EventListener] 연결 오류 → {AGENT_EVENT_RECONNECT_SEC}초 후 재연결: {e}"
            )
            # backoff 중에도 stop 이벤트 즉시 반응
            for _ in range(AGENT_EVENT_RECONNECT_SEC):
                if _stop_event.is_set():
                    break
                time.sleep(1)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None

    logger.info("[EventListener] LISTEN 루프 종료")


# ────────────────────────────────────────────────────────────────────
# 엔트리포인트 — SIGTERM/SIGINT 등록 + heartbeat thread + listen loop.
# ────────────────────────────────────────────────────────────────────
def main() -> None:
    def _on_signal(signum, frame):
        logger.info(f"[EventListener] signal {signum} 수신 — 종료 처리")
        _stop_event.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT,  _on_signal)

    logger.info(
        f"[EventListener] 시작 farms={AGENT_EVENT_FARM_IDS} "
        f"cooldown={AGENT_EVENT_COOLDOWN_SEC}초 "
        f"heartbeat={AGENT_EVENT_HEARTBEAT_SEC}초 "
        f"trigger_user_subs={AGENT_EVENT_TRIGGER_USER_SUBS}"
    )

    # heartbeat 감시 daemon thread 기동
    hb_thread = threading.Thread(
        target=_heartbeat_check_loop,
        daemon=True,
        name="event_listener_heartbeat",
    )
    hb_thread.start()

    # 메인 스레드에서 LISTEN 루프 실행 (재연결 포함)
    _listen_loop()

    logger.info("[EventListener] 정상 종료")


if __name__ == "__main__":
    sys.exit(main() or 0)
