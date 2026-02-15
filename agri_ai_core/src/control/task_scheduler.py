# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 작업 스케줄러 모듈
# 주기적 작업, 예약 작업 등을 관리하고 실행하는 스케줄러를 제공하며,
# 시스템의 자동화된 작업들을 조율합니다.
# --->
# setup_scheduler: 스케줄러 설정
# start_scheduler: 스케줄러 시작
# stop_scheduler: 스케줄러 중지
# add_job: 작업 추가
# remove_job: 작업 제거
# setup_default_jobs: 기본 스케줄 작업 설정
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스케줄러 설정
# 스케줄러 초기화 및 설정
#
# Returns:
#     BackgroundScheduler: 스케줄러 인스턴스
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스케줄러 시작
# 스케줄러 시작
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스케줄러 중지
# 스케줄러 중지
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 작업 추가
# 스케줄러에 작업 추가
#
# Args:
#     job_id: 작업 ID
#     func: 실행할 함수
#     trigger_type: 트리거 유형 ("interval" 또는 "cron")
#     **trigger_kwargs: 트리거 설정
#
# Returns:
#     bool: 성공 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 작업 제거
# 스케줄러에서 작업 제거
#
# Args:
#     job_id: 작업 ID
#
# Returns:
#     bool: 성공 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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



# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 기본 스케줄 작업 설정
# 기본 스케줄 작업 설정
#
# Args:
#     data_export_func: 데이터 내보내기 함수
#     learning_func: 학습 함수
#     stats_func: 통계 처리 함수
#     schedule_control_func: 조명/관수밸브 스케줄 제어 함수
#
# Returns:
#     bool: 성공 여부
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def setup_default_jobs(data_export_func=None, learning_func=None, stats_func=None, schedule_control_func=None):
    try:
        # 데이터 내보내기 작업 (매 3분)
        if data_export_func:
            add_job(
                job_id="data_export_job",
                func=data_export_func,
                trigger_type="interval",
                minutes=3
            )

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

        # 조명/관수밸브 스케줄 제어 작업 (매 1분)
        if schedule_control_func:
            add_job(
                job_id="schedule_control_job",
                func=schedule_control_func,
                trigger_type="interval",
                minutes=1
            )

        logger.info("기본 스케줄 작업 설정 완료")
        return True

    except Exception as e:
        logger.error(f"기본 스케줄 작업 설정 중 오류: {e}")
        logger.error(traceback.format_exc())
        return False
