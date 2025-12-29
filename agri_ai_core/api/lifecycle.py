# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# API 서버 생명주기 관리 모듈
# 서버 시작 및 종료 시 실행되는 이벤트 핸들러를 관리하며,
# 데이터베이스 연결, 리소스 초기화 등을 담당합니다.
# --->
# on_startup: 시작 시 실행
# on_shutdown: 종료 시 실행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.database.chromadb.client import heartbeat, ensure_required_collections_exist
from agri_ai_core.llm.core.llm_client import initialize_background_warmup
from agri_ai_core.control.scheduler.task_scheduler import setup_scheduler, start_scheduler, stop_scheduler, setup_default_jobs
from agri_ai_core.control.relay.schedule_control import control_all_schedules

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 시작 시 실행
# 애플리케이션 시작 시 실행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def on_startup():
    try:
        logger.info("=" * 60)
        logger.info("AgriAI Core API 시작 초기화")
        logger.info("=" * 60)

        # 1. ChromaDB 연결 확인
        logger.info("[1/4] ChromaDB 연결 확인 중...")
        try:
            status = heartbeat()
            if "error" in status:
                logger.warning(f"ChromaDB 연결 경고: {status.get('error')}")
            else:
                logger.info("ChromaDB 연결 성공")
                # 필수 컬렉션 확인
                ensure_required_collections_exist()
                logger.info("필수 컬렉션 확인 완료")
        except Exception as e:
            logger.error(f"ChromaDB 연결 실패: {e}")

        # 2. LLM 워밍업
        logger.info("[2/4] LLM 워밍업 시작...")
        try:
            initialize_background_warmup()
            logger.info("LLM 백그라운드 워밍업 시작됨")
        except Exception as e:
            logger.warning(f"LLM 워밍업 실패: {e}")

        # 3. 스케줄러 설정
        logger.info("[3/4] 스케줄러 설정 중...")
        try:
            setup_scheduler()
            # 조명/관수 스케줄 제어 작업 등록 (매 1분)
            setup_default_jobs(schedule_control_func=control_all_schedules)
            start_scheduler()
            logger.info("스케줄러 시작됨 (조명/관수 스케줄 제어 포함)")
        except Exception as e:
            logger.warning(f"스케줄러 설정 실패: {e}")

        # 4. 초기 데이터 로드
        logger.info("[4/4] 초기 데이터 로드 중...")
        # 필요한 초기 데이터 로드 로직 추가 가능

        logger.info("=" * 60)
        logger.info("AgriAI Core API 시작 초기화 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"시작 초기화 중 오류: {e}")
        logger.error(traceback.format_exc())


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 종료 시 실행
# 애플리케이션 종료 시 실행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def on_shutdown():
    try:
        logger.info("=" * 60)
        logger.info("AgriAI Core API 종료 처리")
        logger.info("=" * 60)

        # 1. 스케줄러 중지
        logger.info("[1/2] 스케줄러 중지 중...")
        try:
            stop_scheduler()
            logger.info("스케줄러 중지됨")
        except Exception as e:
            logger.warning(f"스케줄러 중지 실패: {e}")

        # 2. 리소스 정리
        logger.info("[2/2] 리소스 정리 중...")
        # 필요한 리소스 정리 로직 추가 가능

        logger.info("=" * 60)
        logger.info("AgriAI Core API 종료 처리 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"종료 처리 중 오류: {e}")
        logger.error(traceback.format_exc())
