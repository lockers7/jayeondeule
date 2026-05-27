# ═══════════════════════════════════════════════════════════════
# 작업 스케줄러 모듈 (APScheduler 기반)
# 주기적 작업(학습/통계/환경제어/로그정리/외부수집)을 관리·실행한다.
# --->
# setup_scheduler: BackgroundScheduler 인스턴스 생성/설정
# start_scheduler: 스케줄러 시작 (이미 실행 중이면 무시)
# stop_scheduler: 스케줄러 정지 (graceful shutdown)
# add_job: 크론/인터벌 작업 등록
# remove_job: 등록된 작업 제거
# _daily_log_cleanup: 매일 자정 로그 정리 (내부 작업)
# _chunk_cleanup_job: RAG 청크 통합/정리 (내부 작업)
# setup_default_jobs: 기본 스케줄 작업 일괄 등록
# _lotto_weekly_job: 주간 로또 당첨번호 수집 + 분석 (내부 작업)
# ═══════════════════════════════════════════════════════════════
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import (
    STATS_INTERVAL_MINUTES,
    SCHEDULE_LEARNING_HOUR,
    SCHEDULE_LEARNING_MINUTE
)

logger = setup_logger(__name__)

# 전역 스케줄러 인스턴스
_scheduler = None


# ══════════════════
# 스케줄러 설정
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# BackgroundScheduler 인스턴스 생성/설정 — 1회만 초기화 (idempotent).
# ────────────────────────────────────────────────────────────────────
def setup_scheduler():
    global _scheduler

    if _scheduler is not None:
        logger.warning("스케줄러가 이미 설정되어 있습니다.")
        return _scheduler

    try:
        _scheduler = BackgroundScheduler(
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 60
            }
        )

        logger.info("스케줄러 초기화 완료")
        return _scheduler

    except Exception as e:
        logger.error(f"스케줄러 설정 중 오류: {e}")
        logger.error(traceback.format_exc())
        return None


# ══════════════════
# 스케줄러 시작
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 스케줄러 시작 — 미설정 시 자동 setup. 이미 실행 중이면 무시.
# ────────────────────────────────────────────────────────────────────
def start_scheduler():
    global _scheduler

    if _scheduler is None:
        _scheduler = setup_scheduler()

    if _scheduler is None:
        logger.error("스케줄러를 시작할 수 없습니다.")
        return False

    try:
        if not _scheduler.running:
            _scheduler.start()
            logger.info("스케줄러 시작됨")
            return True
        else:
            logger.warning("스케줄러가 이미 실행 중입니다.")
            return True

    except Exception as e:
        logger.error(f"스케줄러 시작 중 오류: {e}")
        logger.error(traceback.format_exc())
        return False


# ══════════════════
# 스케줄러 중지
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 스케줄러 정지 — graceful shutdown(wait=True).
# ────────────────────────────────────────────────────────────────────
def stop_scheduler():
    global _scheduler

    if _scheduler is None:
        logger.warning("스케줄러가 설정되어 있지 않습니다.")
        return

    try:
        if _scheduler.running:
            _scheduler.shutdown(wait=True)
            logger.info("스케줄러 중지됨")
        else:
            logger.warning("스케줄러가 실행 중이 아닙니다.")

    except Exception as e:
        logger.error(f"스케줄러 중지 중 오류: {e}")
        logger.error(traceback.format_exc())


# ══════════════════
# 작업 추가
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 크론/인터벌 작업 등록 — job_id 중복 시 기존 제거 후 신규 등록.
# trigger_type: "interval" | "cron".
# ────────────────────────────────────────────────────────────────────
def add_job(job_id, func, trigger_type="interval", **trigger_kwargs):
    global _scheduler

    if _scheduler is None:
        _scheduler = setup_scheduler()

    if _scheduler is None:
        logger.error("스케줄러가 설정되어 있지 않아 작업을 추가할 수 없습니다.")
        return False

    try:
        # 기존 작업 제거
        existing_job = _scheduler.get_job(job_id)
        if existing_job:
            _scheduler.remove_job(job_id)
            logger.info(f"기존 작업 '{job_id}' 제거됨")

        # 트리거 생성
        if trigger_type == "interval":
            trigger = IntervalTrigger(**trigger_kwargs)
        elif trigger_type == "cron":
            trigger = CronTrigger(**trigger_kwargs)
        else:
            logger.error(f"지원하지 않는 트리거 유형: {trigger_type}")
            return False

        # 작업 추가
        _scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True
        )

        logger.info(f"작업 '{job_id}' 추가됨 (트리거: {trigger_type}, 설정: {trigger_kwargs})")
        return True

    except Exception as e:
        logger.error(f"작업 추가 중 오류: {e}")
        logger.error(traceback.format_exc())
        return False


# ══════════════════
# 작업 제거
# ══════════════════
# ────────────────────────────────────────────────────────────────────
# 등록된 작업 제거. 존재하지 않으면 False.
# ────────────────────────────────────────────────────────────────────
def remove_job(job_id):
    global _scheduler

    if _scheduler is None:
        logger.warning("스케줄러가 설정되어 있지 않습니다.")
        return False

    try:
        job = _scheduler.get_job(job_id)
        if job:
            _scheduler.remove_job(job_id)
            logger.info(f"작업 '{job_id}' 제거됨")
            return True
        else:
            logger.warning(f"작업 '{job_id}'를 찾을 수 없습니다.")
            return False

    except Exception as e:
        logger.error(f"작업 제거 중 오류: {e}")
        logger.error(traceback.format_exc())
        return False



# ═════════════════════════
# 매일 00:00 로그 정리 작업
# ═════════════════════════
# ────────────────────────────────────────────────────────────────────
# 매일 00:00 로그 정리 — 100일 이전 파일 삭제 + 단일 파일 트리밍.
# ────────────────────────────────────────────────────────────────────
def _daily_log_cleanup():
    try:
        from agri_ai_core.logs import cleanup_all_logs
        cleanup_all_logs()
        logger.info("[스케줄] 일일 로그 정리 완료")
    except Exception as e:
        logger.error(f"[스케줄] 일일 로그 정리 실패: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PostgreSQL 커넥션 풀 상태 주기 로깅 (기본 5분)
# 사용률 경고 임계(기본 80%) 초과 시 WARNING 레벨, 정상은 INFO.
# ═══════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# PostgreSQL 커넥션 풀 상태 주기 로깅 (기본 5분).
# 사용률 ≥ 80% 시 WARNING, 정상은 INFO. 풀 미초기화 시 조용히 skip.
# ────────────────────────────────────────────────────────────────────
def _pg_pool_heartbeat():
    try:
        from agri_ai_core.src.postgresql.connection import db as _db
        stats = _db.get_pool_stats()
        if not stats.get("initialized"):
            return   # 아직 풀 없음 (쿼리 발생 전) — 조용히 skip
        in_use = stats.get("in_use")
        idle = stats.get("idle")
        pmax = stats.get("max") or 0
        if in_use is not None and pmax > 0:
            util = in_use / pmax
            msg = (f"[PG_POOL] in_use={in_use} idle={idle} "
                   f"min={stats.get('min')} max={pmax} "
                   f"util={util*100:.0f}%")
            if util >= 0.8:
                logger.warning(msg + " (80% 초과 — 풀 확장 검토)")
            else:
                logger.info(msg)
        else:
            logger.info(f"[PG_POOL] min={stats.get('min')} max={pmax} "
                         f"(in_use/idle 측정 불가 — psycopg2 내부 접근 실패)")
    except Exception as e:
        logger.debug(f"[PG_POOL] 하트비트 실패: {e}")


# ════════════════════════════════════════════════════════════════════════════
# 매일 03:00에 실행 — farm_knowledge 컬렉션에서 180일 이상 된 오래된 청크 삭제
# ════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 매일 03:00 RAG 청크 정리 — farm_knowledge 컬렉션의 180일 초과 데이터 삭제.
# ────────────────────────────────────────────────────────────────────
def _chunk_cleanup_job():
    try:
        from datetime import datetime, timedelta
        from agri_ai_core.src.chroma.collections import farm_knowledge_collection
        from agri_ai_core.src.chroma.operations import get_documents, delete_document

        collection_name = farm_knowledge_collection()
        if not collection_name:
            return

        cutoff_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        logger.info(f"[스케줄] 청크 정리 시작 — 기준일: {cutoff_date} 이전 데이터 삭제 대상")

        # 전체 문서 조회 (메타데이터만)
        result = get_documents(collection_name, include=["metadatas"], limit=10000)
        if "error" in result:
            logger.warning(f"[스케줄] 청크 정리 — 문서 조회 실패: {result['error']}")
            return

        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])

        delete_ids = []
        for doc_id, meta in zip(ids, metadatas):
            if not isinstance(meta, dict):
                continue
            record_dt = meta.get("record_datetime", "")
            if isinstance(record_dt, str) and len(record_dt) >= 10:
                if record_dt[:10] < cutoff_date:
                    delete_ids.append(doc_id)

        if delete_ids:
            # chroma/operations.py의 delete_document 직접 활용 (MCP 직접 의존 제거)
            _CHUNK_DELETE_BATCH_SIZE = 100
            total_deleted = 0
            for i in range(0, len(delete_ids), _CHUNK_DELETE_BATCH_SIZE):
                batch = delete_ids[i:i + _CHUNK_DELETE_BATCH_SIZE]
                result = delete_document(collection_name, batch)
                if result.get("success"):
                    total_deleted += len(batch)

            logger.info(f"[스케줄] 청크 정리 완료 — {total_deleted}/{len(delete_ids)}건 삭제")
        else:
            logger.info("[스케줄] 청크 정리 — 삭제 대상 없음")

    except Exception as e:
        logger.error(f"[스케줄] 청크 정리 실패: {e}")
        logger.error(traceback.format_exc())


# ════════════════════════════════════════════════════════════════════════════
# SCHEDULE_M_SETTING 기반 동적 스케줄 등록
#
# 설계:
#   - DB row(task_name) → callable 매핑(_JOB_CALLABLES)으로 등록
#   - cron_expr 은 APScheduler CronTrigger.from_crontab() 으로 변환
#   - schedule_polling_job (30초 interval) 가 updt_dttm 변경 감지 시 reload
#   - DB 조회 실패 시 코드 default 폴백 (안전장치)
#   - ai_control_loop 은 별도 스레드 운영 — 본 모듈에서 등록 X
# ════════════════════════════════════════════════════════════════════════════
_JOB_CALLABLES = {}             # task_name -> callable (setup 시점 주입)
_LAST_SCHEDULE_UPDT = None      # 마지막으로 본 max(updt_dttm)
_SCHEDULE_POLLING_INTERVAL = 30 # schedule_m_setting polling 주기(초)


# ────────────────────────────────────────────────────────────────────
# 단일 row 를 APScheduler 에 등록 (cron 또는 interval).
# ────────────────────────────────────────────────────────────────────
def _add_job_from_row(row):
    task_name = row.get('task_name')
    func = _JOB_CALLABLES.get(task_name)
    if func is None:
        return False   # 호출자가 주입 안 한 callable — skip

    schedule_type = row.get('schedule_type')
    if schedule_type == 'interval':
        return add_job(
            job_id=task_name,
            func=func,
            trigger_type='interval',
            seconds=int(row['interval_seconds']),
        )
    if schedule_type == 'cron':
        try:
            trigger = CronTrigger.from_crontab(row['cron_expr'])
        except Exception as e:
            logger.error(f"[schedule] {task_name} cron 파싱 실패 ({row.get('cron_expr')}): {e}")
            return False
        try:
            existing = _scheduler.get_job(task_name) if _scheduler else None
            if existing:
                _scheduler.remove_job(task_name)
            _scheduler.add_job(func, trigger=trigger, id=task_name, replace_existing=True)
            logger.info(f"작업 '{task_name}' 추가됨 (cron: {row['cron_expr']})")
            return True
        except Exception as e:
            logger.error(f"[schedule] {task_name} 등록 실패: {e}")
            return False
    logger.warning(f"[schedule] {task_name} 알 수 없는 schedule_type={schedule_type}")
    return False


# ────────────────────────────────────────────────────────────────────
# DB 의 schedule_m_setting 전체를 다시 읽어 jobs 등록/제거.
# enabled=False 인 row 는 등록 해제. ai_control_loop 은 별도 스레드라 skip.
# ────────────────────────────────────────────────────────────────────
def _reload_jobs_from_db():
    global _LAST_SCHEDULE_UPDT
    try:
        from agri_ai_core.src.postgresql.reader import (
            read_schedule_settings, read_schedule_max_updt,
        )
        rows = read_schedule_settings() or []
    except Exception as e:
        logger.error(f"[schedule] DB 읽기 실패 — 기존 jobs 유지: {e}")
        return False

    if not rows:
        logger.warning("[schedule] schedule_m_setting 비어있음 — jobs 변경 없음")
        return False

    for row in rows:
        task_name = row.get('task_name')
        if task_name == 'ai_control_loop':
            continue   # 별도 스레드 — task_scheduler 등록 X (interval_seconds 만 read 해서 사용)
        if task_name not in _JOB_CALLABLES:
            continue   # 매핑 안 된 task — skip
        if not row.get('enabled', True):
            if _scheduler and _scheduler.get_job(task_name):
                remove_job(task_name)
                logger.info(f"[schedule] {task_name} 비활성 — 등록 해제")
            continue
        _add_job_from_row(row)

    try:
        _LAST_SCHEDULE_UPDT = read_schedule_max_updt()
    except Exception:
        pass
    return True


# ────────────────────────────────────────────────────────────────────
# polling tick — 30초마다 DB 의 max(updt_dttm) 변경 감지 시 reload.
# ────────────────────────────────────────────────────────────────────
def _schedule_polling_tick():
    global _LAST_SCHEDULE_UPDT
    try:
        from agri_ai_core.src.postgresql.reader import read_schedule_max_updt
        current = read_schedule_max_updt()
    except Exception as e:
        logger.debug(f"[schedule] polling 조회 실패: {e}")
        return
    if current is None:
        return
    if _LAST_SCHEDULE_UPDT is None or current > _LAST_SCHEDULE_UPDT:
        logger.info(f"[schedule] DB 변경 감지 ({_LAST_SCHEDULE_UPDT} → {current}) — 재등록")
        _reload_jobs_from_db()


# ────────────────────────────────────────────────────────────────────
# 기본 스케줄 작업 일괄 등록 — SCHEDULE_M_SETTING 기반.
# 호출자 주입 callable 을 task_name 별 매핑한 후 DB row 로 register.
# 시그니처는 기존과 동일(호환). DB 조회 실패 시 등록 0건이 될 수 있음.
# ────────────────────────────────────────────────────────────────────
def setup_default_jobs(learning_func=None, stats_func=None,
                       manual_control_func=None, growth_rag_func=None,
                       lotto_collect_func=None):
    global _JOB_CALLABLES
    try:
        # ── callable 매핑 — schedule_m_setting.task_name 과 1:1 ──
        try:
            from agri_ai_core.src.control.ai_camera_archive import (
                capture_all_active_houses, cleanup_old_images,
            )
        except ImportError as _cam_e:
            logger.warning(f"[스케줄] 카메라 아카이브 모듈 import 실패: {_cam_e}")
            capture_all_active_houses = None
            cleanup_old_images = None

        def _wrap_safe(name, fn):
            """callable 호출 시 예외 안전 wrapper."""
            if fn is None:
                return None
            def _inner(*a, **kw):
                try:
                    return fn(*a, **kw)
                except Exception as ee:
                    logger.error(f"[{name}] 실행 실패: {ee}")
            _inner.__name__ = name
            return _inner

        _JOB_CALLABLES = {
            'learning_job':            learning_func,
            'stats_job':               stats_func,
            'relay_control_job':      manual_control_func,
            'growth_rag_job_noon':    growth_rag_func,
            'growth_rag_job_midnight': (lambda: growth_rag_func(is_midnight=True)) if growth_rag_func else None,
            'daily_log_cleanup':      _daily_log_cleanup,
            'pg_pool_heartbeat':      _pg_pool_heartbeat,
            'chunk_cleanup_job':      _chunk_cleanup_job,
            'camera_archive_hourly':  capture_all_active_houses,
            'camera_archive_cleanup': cleanup_old_images,
            'lotto_weekly_job':       _wrap_safe('로또수집', lotto_collect_func),
            # 'ai_control_loop' 은 별도 스레드(_ai_control_loop)에서 직접 가동
        }

        # ── DB 기반 등록 ──
        ok = _reload_jobs_from_db()

        # 환경변수 PGDB_POOL_HEARTBEAT_MIN=0 호환 (기존 정책 보존)
        # — DB enabled 가 우선이지만 환경변수=0 이면 추가로 끔
        import os as _os
        if int(_os.getenv("PGDB_POOL_HEARTBEAT_MIN", "5") or 0) == 0:
            if _scheduler and _scheduler.get_job("pg_pool_heartbeat"):
                remove_job("pg_pool_heartbeat")
                logger.info("[schedule] pg_pool_heartbeat 환경변수 비활성")

        # ── polling job 자체 등록 (DB 변경 감지 → reload) ──
        add_job(
            job_id="_schedule_polling_job",
            func=_schedule_polling_tick,
            trigger_type="interval",
            seconds=_SCHEDULE_POLLING_INTERVAL,
        )

        if ok:
            logger.info(f"기본 스케줄 작업 설정 완료 (SCHEDULE_M_SETTING 기반, polling={_SCHEDULE_POLLING_INTERVAL}초)")
        else:
            logger.warning("기본 스케줄 작업 설정 — DB 로드 실패 또는 빈 결과 (polling 만 가동)")
        return True

    except Exception as e:
        logger.error(f"기본 스케줄 작업 설정 중 오류: {e}")
        logger.error(traceback.format_exc())
        return False
