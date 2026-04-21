# ════════════════════════════════════════════════════════════════════
# REST API 서버 실행 진입점 — `python -m agri_ai_core.api` 로 Uvicorn 기동.
# --->
# main : 환경변수(API_HOST/API_PORT/API_LOG_LEVEL) 로드 후 Uvicorn 기동
# ════════════════════════════════════════════════════════════════════
import os
import uvicorn


# ────────────────────────────────────────────────────────────────────
# Uvicorn 기반 FastAPI 서버 기동 — agri_ai_core.api.app:app 을 호스팅.
# 환경변수 API_HOST(0.0.0.0)/API_PORT(8002)/API_LOG_LEVEL(info) 로 구성.
# ────────────────────────────────────────────────────────────────────
def main():
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8002"))
    log_level = os.getenv("API_LOG_LEVEL", "info")

    uvicorn.run(
        "agri_ai_core.api.app:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
