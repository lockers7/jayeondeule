# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 백그라운드 서비스 러너
# ChromaDB 연결 확인, 스케줄러(조명/관수밸브) 등
# Streamlit과 별도 프로세스로 상시 실행됩니다.
# --->
# main: 백그라운드 서비스 시작 후 대기
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import signal
import sys

from agri_ai_core.startup import initialize_app, shutdown_app
from agri_ai_core.log_utils.log_handlers import setup_logger

logger = setup_logger(__name__)


def main():
    # 시그널 핸들러 등록
    def handle_signal(signum, frame):
        logger.info(f"시그널 {signum} 수신, 종료 처리 시작")
        shutdown_app()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # 초기화 실행
    initialize_app()

    # 스케줄러가 백그라운드 스레드로 동작하므로 메인 스레드는 대기
    logger.info("백그라운드 서비스 대기 중 (Ctrl+C로 종료)")
    signal.pause()


if __name__ == "__main__":
    main()
