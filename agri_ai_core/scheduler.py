# ════════════════════════════════════════════════════════════════════
# 백그라운드 서비스 러너 — ChromaDB 연결 확인, 스케줄러(조명/관수) 등.
# `python -m agri_ai_core.scheduler` 로 데몬 모드 기동 (FastAPI 외 사용).
# --->
# main : SIGTERM/SIGINT 핸들러 등록 후 initialize_app() 실행, signal.pause()
# ════════════════════════════════════════════════════════════════════
import signal
import sys

from agri_ai_core.startup import initialize_app, shutdown_app
from agri_ai_core.logs    import setup_logger

logger = setup_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# 백그라운드 데몬 진입점 — SIGTERM/SIGINT 시 shutdown_app() 후 종료.
# 메인 스레드는 signal.pause() 로 대기 (스케줄러는 별도 스레드 동작).
# ────────────────────────────────────────────────────────────────────
def main():
    # ────────────────────────────────────────────────────────────────
    # 시그널 핸들러 — 종료 시 리소스 정리 후 sys.exit(0).
    # ────────────────────────────────────────────────────────────────
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
