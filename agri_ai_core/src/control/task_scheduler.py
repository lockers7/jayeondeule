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
# _opinet_daily_job: 오피넷 일일 유가 수집 (내부 작업)
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
def _daily_log_cleanup():
    try:
        from agri_ai_core.logs import cleanup_all_logs
        cleanup_all_logs()
        logger.info("[스케줄] 일일 로그 정리 완료")
    except Exception as e:
        logger.error(f"[스케줄] 일일 로그 정리 실패: {e}")


# ════════════════════════════════════════════════════════════════════════════
# 매일 03:00에 실행 — farm_knowledge 컬렉션에서 180일 이상 된 오래된 청크 삭제
# ════════════════════════════════════════════════════════════════════════════
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


def setup_default_jobs(learning_func=None, stats_func=None,
                       manual_control_func=None, growth_rag_func=None):
    try:
        # 학습 작업 (매일 지정 시간)
        if learning_func:
            add_job(
                job_id="learning_job",
                func=learning_func,
                trigger_type="cron",
                hour=SCHEDULE_LEARNING_HOUR,
                minute=SCHEDULE_LEARNING_MINUTE
            )

        # 통계 처리 작업 (매 10분)
        if stats_func:
            add_job(
                job_id="stats_job",
                func=stats_func,
                trigger_type="interval",
                minutes=STATS_INTERVAL_MINUTES
            )

        # 수동/알고리즘 환경제어 + AI 비상모니터링 (매 5초)
        # 스케줄제어(조명/관수) + 수동/알고리즘 환경제어 + AI 비상제어
        # max_instances=1 설정으로 이전 실행 미완료 시 다음 실행 스킵
        if manual_control_func:
            add_job(
                job_id="relay_control_job",
                func=manual_control_func,
                trigger_type="interval",
                seconds=5
            )

        # AI 인공지능 환경제어: 별도 순환 루프 스레드로 운영 (startup.py에서 시작)
        # 재배사 순환 + 30초 delay 방식으로 변경되어 스케줄러 등록 불필요

        # 생육 RAG 작업 (일 2회: 12:00, 00:00)
        # 생육 데이터 입력 시점 기반으로 센서/릴레이 환경 통계를 RAG 데이터로 저장
        if growth_rag_func:
            add_job(
                job_id="growth_rag_job_noon",
                func=growth_rag_func,
                trigger_type="cron",
                hour=12,
                minute=0
            )
            add_job(
                job_id="growth_rag_job_midnight",
                func=lambda: growth_rag_func(is_midnight=True),
                trigger_type="cron",
                hour=0,
                minute=5   # 로그 정리(00:00) 직후
            )

        # 로그 정리 작업 (매일 00:00:00)
        # 100일 이전 로그 파일 삭제, 단일 파일 트리밍
        add_job(
            job_id="daily_log_cleanup",
            func=_daily_log_cleanup,
            trigger_type="cron",
            hour=0,
            minute=0
        )

        # 청크 정리 작업 (매일 03:00)
        # farm_knowledge 컬렉션에서 180일 이상 오래된 데이터 삭제
        add_job(
            job_id="chunk_cleanup_job",
            func=_chunk_cleanup_job,
            trigger_type="cron",
            hour=3,
            minute=0
        )

        # Opinet 유가정보 수집 (매일 10:00)
        def _opinet_daily_job():
            try:
                from agri_ai_core.src.opinet.opinet_collector import collect_all
                collect_all()
            except Exception as oe:
                logger.error(f"[Opinet] 일일 수집 실패: {oe}")

        add_job(
            job_id="opinet_daily_job",
            func=_opinet_daily_job,
            trigger_type="cron",
            hour=10,
            minute=0
        )

        # 로또 당첨번호 수집 (매주 토요일 22:00)
        def _lotto_weekly_job():
            try:
                from agri_ai_core.src.lotto.lotto_collector import update_lotto_db
                update_lotto_db()
            except Exception as le:
                logger.error(f"[로또수집] 주간 수집 실패: {le}")

        add_job(
            job_id="lotto_weekly_job",
            func=_lotto_weekly_job,
            trigger_type="cron",
            day_of_week="sat",
            hour=22,
            minute=0
        )

        logger.info("기본 스케줄 작업 설정 완료")
        return True

    except Exception as e:
        logger.error(f"기본 스케줄 작업 설정 중 오류: {e}")
        logger.error(traceback.format_exc())
        return False
