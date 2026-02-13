# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 초기화 모듈
# 시작 시 ChromaDB 연결, 스케줄러 설정 등을 수행합니다.
# --->
# initialize_app: 애플리케이션 시작 초기화
# shutdown_app: 애플리케이션 종료 처리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import traceback

from agri_ai_core.src.logs import setup_logger
from agri_ai_core.src.chroma import heartbeat, ensure_required_collections_exist
from agri_ai_core.src.control import setup_scheduler, start_scheduler, stop_scheduler, setup_default_jobs, control_all_schedules

logger = setup_logger(__name__)

_initialized = False


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 시작 초기화
# --->
# ChromaDB, 스케줄러 등 시스템 리소스를 초기화합니다.
# 중복 호출을 방지하여 Streamlit 리렌더링 시에도 한 번만 실행됩니다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def initialize_app():
    global _initialized
    if _initialized:
        return

    try:
        logger.info("=" * 60)
        logger.info("AgriAI Core 시작 초기화")
        logger.info("=" * 60)

        # 1. ChromaDB 연결 확인
        logger.info("[1/3] ChromaDB 연결 확인 중...")
        try:
            status = heartbeat()
            if "error" in status:
                logger.warning(f"ChromaDB 연결 경고: {status.get('error')}")
            else:
                logger.info("ChromaDB 연결 성공")
                ensure_required_collections_exist()
                logger.info("필수 컬렉션 확인 완료")
        except Exception as e:
            logger.error(f"ChromaDB 연결 실패: {e}")

        # 2. 스케줄러 설정
        logger.info("[2/3] 스케줄러 설정 중...")
        try:
            setup_scheduler()
            setup_default_jobs(schedule_control_func=control_all_schedules)
            start_scheduler()
            logger.info("스케줄러 시작됨 (조명/관수밸브 스케줄 제어 포함)")
        except Exception as e:
            logger.warning(f"스케줄러 설정 실패: {e}")

        # 3. 초기 데이터 로드
        logger.info("[3/3] 초기 데이터 로드 중...")

        logger.info("=" * 60)
        logger.info("AgriAI Core 시작 초기화 완료")
        logger.info("=" * 60)

        _initialized = True

    except Exception as e:
        logger.error(f"시작 초기화 중 오류: {e}")
        logger.error(traceback.format_exc())


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 애플리케이션 종료 처리
# --->
# 스케줄러 등 리소스를 정리합니다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def shutdown_app():
    try:
        logger.info("=" * 60)
        logger.info("AgriAI Core 종료 처리")
        logger.info("=" * 60)

        logger.info("[1/2] 스케줄러 중지 중...")
        try:
            stop_scheduler()
            logger.info("스케줄러 중지됨")
        except Exception as e:
            logger.warning(f"스케줄러 중지 실패: {e}")

        logger.info("[2/2] 리소스 정리 중...")

        logger.info("=" * 60)
        logger.info("AgriAI Core 종료 처리 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"종료 처리 중 오류: {e}")
        logger.error(traceback.format_exc())
