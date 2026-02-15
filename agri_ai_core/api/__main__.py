"""
REST API 서버 실행
Usage: python -m agri_ai_core.api
"""
import os
import uvicorn


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
