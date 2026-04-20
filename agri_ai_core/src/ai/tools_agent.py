# ══════════════════════════════════════════════════════════════════════════════
# Agent 모니터링 도구 — 사용자가 지시한 시간대에 주기적으로 재배사를 감시·알림.
# APScheduler 동적 Job 등록 + DB(agent_monitor_m_job) 영속화 하이브리드.
# --->
# schedule_monitor: 모니터링 Job 등록 (start/end/interval + house_ids + intent)
# list_monitors:    현재 등록된 Agent 모니터링 Job 조회
# cancel_monitor:   Job 취소
# restore_active_jobs: 서비스 시작 시 DB 로부터 active Job 재등록
# _ensure_agent_job_table:  agent_monitor_m_job 테이블 lazy CREATE IF NOT EXISTS
# _persist_agent_job: Job 등록 시 DB INSERT (메모리 meta 와 이중화)
# _mark_agent_job_cancelled: Job 취소 시 DB UPDATE cancelled_at
# ══════════════════════════════════════════════════════════════════════════════
import json
import threading
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.tools_utils import (
    normalize_id as _normalize_id,
    get_farm_house_ids as _get_farm_house_ids,
)

logger = setup_logger(__name__)

_AGENT_JOB_PREFIX = "agent_monitor_"
_AGENT_JOB_META: Dict[str, Dict[str, Any]] = {}  # job_id → {intent, start, end, houses, interval, created_at}

# [Wave 7] DB 영속화 — alert_l_log 와 동일한 lazy CREATE 패턴 사용
_agent_table_ready = False
_agent_table_lock = threading.Lock()

_CREATE_AGENT_JOB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_monitor_m_job (
    job_id          VARCHAR(64) PRIMARY KEY,
    farm_id         VARCHAR(32) NOT NULL,
    intent          TEXT,
    start_dttm      TIMESTAMP NOT NULL,
    end_dttm        TIMESTAMP NOT NULL,
    interval_min    INTEGER NOT NULL,
    houses          JSONB NOT NULL,
    alert_on_normal BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    cancelled_at    TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_job_active
    ON agent_monitor_m_job(end_dttm, cancelled_at);
"""


def _parse_time(t: str, default_date: datetime = None) -> datetime:
    """'22:00' | '2026-04-19 22:00' | ISO 형식 파싱."""
    t = (t or "").strip()
    if not t:
        raise ValueError("시각이 비어있습니다")

    # ISO 형식
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue

    # HH:MM / H:MM — 오늘 기준
    if ":" in t and len(t) <= 5:
        h, m = map(int, t.split(":"))
        now = default_date or datetime.now()
        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # 이미 지난 시각이면 다음날
        if dt < now:
            dt += timedelta(days=1)
        return dt

    raise ValueError(f"시각 형식 인식 실패: {t}")


# ═══════════════════════════════════════════════════════════════════════════
# [Wave 7] DB 영속화 헬퍼 — agent_monitor_m_job 테이블
# ═══════════════════════════════════════════════════════════════════════════
def _ensure_agent_job_table() -> bool:
    """agent_monitor_m_job 테이블 lazy CREATE. 실패해도 in-memory 경로는 유지."""
    global _agent_table_ready
    if _agent_table_ready:
        return True
    with _agent_table_lock:
        if _agent_table_ready:
            return True
        try:
            from agri_ai_core.src.postgresql.connection import db_session
            with db_session() as db:
                db.execute_query(_CREATE_AGENT_JOB_TABLE_SQL, ())
            _agent_table_ready = True
            logger.info("[Agent] agent_monitor_m_job 영속 테이블 준비 완료")
            return True
        except Exception as e:
            logger.warning(f"[Agent] 테이블 준비 실패 (in-memory 만 사용): {e}")
            return False


def _persist_agent_job(job_id: str, farm_id: str, intent: str,
                         start_dt: datetime, end_dt: datetime,
                         interval_min: int, houses: list, alert_on_normal: bool) -> None:
    """Job 등록을 DB 에 기록. 실패 시 로그만."""
    if not _ensure_agent_job_table():
        return
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        houses_json = json.dumps([str(h) for h in (houses or [])], ensure_ascii=False)
        with db_session() as db:
            db.execute_query(
                "INSERT INTO agent_monitor_m_job "
                "(job_id, farm_id, intent, start_dttm, end_dttm, interval_min, "
                " houses, alert_on_normal, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW()) "
                "ON CONFLICT (job_id) DO NOTHING",
                (job_id, str(farm_id), intent, start_dt, end_dt, interval_min,
                 houses_json, bool(alert_on_normal)),
            )
    except Exception as e:
        logger.debug(f"[Agent] Job 영속화 실패 ({job_id}): {e}")


def _mark_agent_job_cancelled(job_id: str) -> None:
    """Job 취소를 DB 에 반영."""
    if not _ensure_agent_job_table():
        return
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            db.execute_query(
                "UPDATE agent_monitor_m_job SET cancelled_at=NOW() "
                "WHERE job_id=%s AND cancelled_at IS NULL",
                (job_id,),
            )
    except Exception as e:
        logger.debug(f"[Agent] Job 취소 영속화 실패 ({job_id}): {e}")


def restore_active_jobs() -> int:
    """서비스 시작 시 DB 에서 active(미취소 + end 미경과) Job 을 APScheduler 에 재등록.
    반환: 복원된 Job 개수. 호출처는 api/app.py lifespan 에서 이벤트 루프 바인딩 직후.

    멱등성: ON CONFLICT 없이 replace_existing=True 로 APScheduler 재등록.
    DB 에 있는데 이미 메모리에도 있는 경우(해당 프로세스가 방금 등록함) 덮어쓰기로 안전.
    """
    if not _ensure_agent_job_table():
        return 0
    restored = 0
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as db:
            rows = db.fetch_all(
                "SELECT job_id, farm_id, intent, start_dttm, end_dttm, interval_min, "
                "       houses, alert_on_normal "
                "FROM agent_monitor_m_job "
                "WHERE cancelled_at IS NULL AND end_dttm > NOW() "
                "ORDER BY start_dttm",
                as_dict=True,
            )
        now = datetime.now()
        for r in rows or []:
            try:
                # houses 가 JSONB → psycopg2 가 list 로 자동 파싱
                houses = r.get("houses") or []
                if isinstance(houses, str):
                    houses = json.loads(houses)
                start_dt = r["start_dttm"]
                interval_min = int(r["interval_min"])
                # [Wave 9] 재시작 gap 동안 놓친 tick 이 있는지 판정
                # 조건: Job 시작 시각이 이미 지났고, gap 이 interval 의 1.0배 이상이면
                #       최소 1회 tick 이 누락된 것으로 간주하고 복원 직후 1회 즉시 실행
                missed = (start_dt <= now
                          and (now - start_dt).total_seconds() >= interval_min * 60)
                _reregister_job(
                    job_id=r["job_id"],
                    farm_id=str(r["farm_id"]),
                    intent=r.get("intent") or "모니터링",
                    start_dt=start_dt,
                    end_dt=r["end_dttm"],
                    interval_min=interval_min,
                    houses=[str(h) for h in houses],
                    alert_on_normal=bool(r.get("alert_on_normal")),
                    fire_once_now=missed,
                )
                restored += 1
            except Exception as e:
                logger.error(f"[Agent] Job 복원 실패 ({r.get('job_id')}): {e}")
        if restored:
            logger.info(f"[Agent] 재시작 후 active Job {restored}건 복원")
    except Exception as e:
        logger.warning(f"[Agent] active Job 조회 실패: {e}")
    return restored


def _reregister_job(job_id: str, farm_id: str, intent: str,
                      start_dt: datetime, end_dt: datetime,
                      interval_min: int, houses: list, alert_on_normal: bool,
                      fire_once_now: bool = False) -> None:
    """APScheduler 에 Job 을 등록하고 _AGENT_JOB_META 에 메타데이터 캐시.
    fire_once_now=True 면 놓친 tick 보완 목적으로 복원 직후 1회 즉시 실행 (별도 스레드)."""
    from apscheduler.triggers.interval import IntervalTrigger
    from agri_ai_core.src.control.task_scheduler import _scheduler
    if _scheduler is None:
        logger.warning(f"[Agent] 스케줄러 미초기화 — Job {job_id} 등록 보류")
        return

    def _runner(_job_id=job_id, _farm=farm_id, _houses=houses,
                _intent=intent, _aon=alert_on_normal):
        _monitor_job_run(_job_id, _farm, _houses, _intent, _aon)

    # 현재 이후에만 트리거되도록 start_date 보정 (이미 지난 시각이면 다음 주기)
    eff_start = start_dt if start_dt > datetime.now() else datetime.now() + timedelta(seconds=5)
    trigger = IntervalTrigger(
        minutes=interval_min,
        start_date=eff_start,
        end_date=end_dt,
    )
    _scheduler.add_job(_runner, trigger=trigger, id=job_id, replace_existing=True)
    _AGENT_JOB_META[job_id] = {
        "intent": intent,
        "start": start_dt.isoformat() if hasattr(start_dt, "isoformat") else str(start_dt),
        "end": end_dt.isoformat() if hasattr(end_dt, "isoformat") else str(end_dt),
        "interval_min": interval_min,
        "houses": list(houses),
        "farm_id": farm_id,
        "alert_on_normal": alert_on_normal,
        "created_at": datetime.now().isoformat(),
    }

    # [Wave 9] 놓친 tick 보완: 복원 직후 1회 즉시 실행 (별도 스레드)
    # alert_on_normal 은 원본 설정 유지 → 이상 없으면 알림도 없음 (소음 없음)
    if fire_once_now:
        def _gap_catchup():
            try:
                _monitor_job_run(job_id, farm_id, list(houses),
                                  f"{intent} (재시작 gap 보완)", alert_on_normal)
            except Exception as _e:
                logger.error(f"[Agent] gap catchup 실행 오류 ({job_id}): {_e}")
        threading.Thread(target=_gap_catchup, daemon=True,
                          name=f"agent-gap-catchup-{job_id}").start()
        logger.info(f"[Agent] Job {job_id} 놓친 tick 감지 → 복원 직후 즉시 1회 실행 스레드 시작")


def _monitor_job_run(
    job_id: str,
    farm_id: str,
    house_ids: List[str],
    intent: str,
    alert_on_normal: bool = False,
) -> None:
    """APScheduler가 매 주기마다 호출하는 실행 함수. 센서 확인 + 이상시 알림 발행."""
    from agri_ai_core.src.ai.tools_data import get_farm_realtime_data
    from agri_ai_core.src.ai import alert_bus
    from agri_ai_core.src.control.control_common import (
        TEMP_LOW, TEMP_HIGH, TEMP_CRITICAL_LOW, TEMP_CRITICAL_HIGH,
        HUMIDITY_LOW, HUMIDITY_HIGH, HUMIDITY_CRITICAL_LOW, HUMIDITY_CRITICAL_HIGH,
        CO2_HIGH, CO2_CRITICAL_HIGH,
    )

    for hid in house_ids:
        try:
            data = get_farm_realtime_data(house_id=hid, farm_id=farm_id, data_type="sensor")
            sensor = (data or {}).get("sensor") or {}
            t = sensor.get("indoor_temperature")
            h = sensor.get("indoor_humidity")
            c = sensor.get("co2")

            # 이상 판별
            anomalies = []
            if t is not None:
                if t < TEMP_CRITICAL_LOW or t > TEMP_CRITICAL_HIGH:
                    anomalies.append(("critical", f"온도 비상: {t}℃"))
                elif t < TEMP_LOW or t > TEMP_HIGH:
                    anomalies.append(("warning", f"온도 정상범위 이탈: {t}℃"))
            if h is not None:
                if h < HUMIDITY_CRITICAL_LOW or h > HUMIDITY_CRITICAL_HIGH:
                    anomalies.append(("critical", f"습도 비상: {h}%"))
                elif h < HUMIDITY_LOW or h > HUMIDITY_HIGH:
                    anomalies.append(("warning", f"습도 정상범위 이탈: {h}%"))
            if c is not None:
                if c > CO2_CRITICAL_HIGH:
                    anomalies.append(("critical", f"CO2 비상: {c}ppm"))
                elif c > CO2_HIGH:
                    anomalies.append(("warning", f"CO2 정상범위 이탈: {c}ppm"))

            if anomalies:
                # 가장 심각한 레벨로 발행
                level = "critical" if any(a[0] == "critical" for a in anomalies) else "warning"
                msg = " / ".join(a[1] for a in anomalies)
                alert_bus.publish(
                    level=level, category="agent_monitor",
                    farm_id=farm_id, house_id=hid,
                    title=f"[Agent] {hid}호 이상 감지",
                    message=f"{intent} → {msg}",
                    data={"job_id": job_id, "sensor": sensor, "anomalies": anomalies},
                )
            elif alert_on_normal:
                alert_bus.publish(
                    level="info", category="agent_monitor",
                    farm_id=farm_id, house_id=hid,
                    title=f"[Agent] {hid}호 정상",
                    message=f"{intent} → 온도 {t}℃ · 습도 {h}% · CO2 {c}ppm (정상)",
                    data={"job_id": job_id, "sensor": sensor},
                )
        except Exception as e:
            logger.error(f"[Agent] 모니터링 실행 오류 house={hid}: {e}\n{traceback.format_exc()}")


def schedule_monitor(
    intent: str,
    start_time: str,
    end_time: str,
    interval_min: int,
    house_ids: Any = None,
    farm_id: str = None,
    alert_on_normal: bool = False,
) -> Dict[str, Any]:
    """사용자 지정 시간대에 주기적 센서 감시+알림 Job 등록.

    Args:
        intent: 사용자 의도 한 줄 (알림에 포함)
        start_time: 시작 시각 ('HH:MM' | 'YYYY-MM-DD HH:MM' | ISO)
        end_time: 종료 시각
        interval_min: 주기(분). 최소 1분, 최대 1440분(24시간)
        house_ids: 리스트(예: ['1','2','3']) 또는 콤마 구분 문자열 또는 'all'/'전체'
        farm_id: 농장 ID
        alert_on_normal: True면 이상 없을 때도 매 주기 정상 상태 알림 발행

    Returns:
        {success, job_id, start, end, interval_min, houses, intent}
    """
    from agri_ai_core.src.control.task_scheduler import add_job
    from apscheduler.triggers.interval import IntervalTrigger

    if not intent:
        intent = "모니터링"

    try:
        start_dt = _parse_time(start_time)
        end_dt = _parse_time(end_time, default_date=start_dt)
        if end_dt <= start_dt:
            # 종료가 더 작으면 다음날
            end_dt += timedelta(days=1)

        if interval_min < 1 or interval_min > 1440:
            return {"success": False, "error": "interval_min은 1~1440 범위여야 합니다"}

        target_farm = _normalize_id(farm_id) or "1"
        farm_houses = _get_farm_house_ids(target_farm) or []

        # house_ids 정규화 — 재배사 목록은 농장별로 가변이므로 DB 동적 조회 사용
        if isinstance(house_ids, str):
            s = house_ids.strip().lower()
            if s in ("all", "전체", "모든", "모든재배사", "전재배사", "전체재배사"):
                houses = farm_houses
            else:
                houses = [x.strip() for x in house_ids.split(",") if x.strip()]
        elif isinstance(house_ids, list):
            houses = [str(x) for x in house_ids]
        else:
            houses = farm_houses  # 기본: 해당 농장 전 재배사

        if not houses:
            return {"success": False, "error": f"농장(farm_id={target_farm})의 감시 대상 재배사를 찾을 수 없습니다"}

        job_id = f"{_AGENT_JOB_PREFIX}{int(datetime.now().timestamp() * 1000)}"

        # Closure 로 인자 바인딩
        def _runner(_job_id=job_id, _farm=target_farm, _houses=houses,
                    _intent=intent, _aon=alert_on_normal):
            _monitor_job_run(_job_id, _farm, _houses, _intent, _aon)

        # APScheduler 동적 등록
        trigger = IntervalTrigger(
            minutes=interval_min,
            start_date=start_dt,
            end_date=end_dt,
        )
        from agri_ai_core.src.control.task_scheduler import _scheduler
        if _scheduler is None:
            return {"success": False, "error": "스케줄러가 초기화되지 않았습니다 (FastAPI 재시작 필요)"}

        _scheduler.add_job(_runner, trigger=trigger, id=job_id, replace_existing=True)

        _AGENT_JOB_META[job_id] = {
            "intent": intent,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "interval_min": interval_min,
            "houses": houses,
            "farm_id": target_farm,
            "alert_on_normal": alert_on_normal,
            "created_at": datetime.now().isoformat(),
        }

        # [Wave 7] DB 영속화 (재시작 후 restore_active_jobs 가 복원)
        _persist_agent_job(
            job_id=job_id, farm_id=target_farm, intent=intent,
            start_dt=start_dt, end_dt=end_dt, interval_min=interval_min,
            houses=houses, alert_on_normal=alert_on_normal,
        )

        logger.info(
            f"[Agent] 모니터링 Job 등록: {job_id} "
            f"{start_dt}~{end_dt} {interval_min}분 houses={houses} intent='{intent}'"
        )

        # 시작 직후 1회 즉시 실행 (즉각 피드백용)
        try:
            _monitor_job_run(job_id, target_farm, houses, f"{intent} (즉시실행)", alert_on_normal=True)
        except Exception:
            pass

        return {
            "success": True,
            "job_id": job_id,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "interval_min": interval_min,
            "houses": houses,
            "intent": intent,
            "message": f"{start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')} 사이 {interval_min}분마다 "
                       f"{','.join(houses)}호 감시. 이상 감지 시 채팅에 알림 전송. 즉시 초기 점검 1회 실행.",
        }

    except Exception as e:
        logger.error(f"[Agent] schedule_monitor 오류: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


def list_monitors() -> Dict[str, Any]:
    """현재 등록된 Agent 모니터링 Job 목록 조회."""
    from agri_ai_core.src.control.task_scheduler import _scheduler
    if _scheduler is None:
        return {"success": False, "error": "스케줄러 미초기화"}

    active = []
    for j in _scheduler.get_jobs():
        if j.id.startswith(_AGENT_JOB_PREFIX):
            meta = _AGENT_JOB_META.get(j.id, {})
            active.append({
                "job_id": j.id,
                "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                **meta,
            })
    return {"success": True, "monitors": active, "count": len(active)}


def cancel_monitor(job_id: str) -> Dict[str, Any]:
    """특정 모니터링 Job 취소."""
    from agri_ai_core.src.control.task_scheduler import _scheduler
    if _scheduler is None:
        return {"success": False, "error": "스케줄러 미초기화"}
    try:
        existing = _scheduler.get_job(job_id)
        if not existing:
            # 메모리엔 없지만 DB 에만 있는 경우도 있으므로 DB 취소는 수행
            _mark_agent_job_cancelled(job_id)
            return {"success": False, "error": f"Job 없음: {job_id} (DB 취소 표시 완료)"}
        _scheduler.remove_job(job_id)
        _AGENT_JOB_META.pop(job_id, None)
        # [Wave 7] DB 취소 반영 (영속 복원 대상에서 제외)
        _mark_agent_job_cancelled(job_id)
        logger.info(f"[Agent] 모니터링 Job 취소: {job_id}")
        return {"success": True, "cancelled": job_id}
    except Exception as e:
        return {"success": False, "error": str(e)}
