# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# FastAPI 애플리케이션 초기화 및 설정 모듈
# CORS 설정, 라우터 등록, 미들웨어 구성 등 API 서버의
# 전체적인 구조를 설정하고 앱 인스턴스를 생성합니다.
# --->
# lifespan: 기능 설명 필요
# create_app: 기능 설명 필요
# get_app: 기능 설명 필요
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.api.routes import chat, farm, health
from agri_ai_core.api.lifecycle import on_startup, on_shutdown

logger = setup_logger(__name__)

_app = None


# 애플리케이션 라이프사이클 관리
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI 애플리케이션 시작")
    await on_startup()
    yield
    logger.info("FastAPI 애플리케이션 종료")
    await on_shutdown()


# FastAPI 앱 생성
def _build_app() -> FastAPI:
    app = FastAPI(
        title="AgriAI Core API",
        description="스마트팜 AI 어시스턴트 API",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(farm.router, prefix="/api/v1", tags=["farm"])

    # 레거시 호환성을 위해 루트 경로에도 일부 엔드포인트 등록
    app.include_router(farm.router, tags=["farm-legacy"])

    logger.info("FastAPI 애플리케이션 생성 완료")
    return app


# FastAPI 앱 인스턴스 반환 (싱글톤)
def create_app() -> FastAPI:
    global _app
    if _app is None:
        _app = _build_app()
    return _app


# FastAPI 앱 인스턴스 반환
def get_app() -> FastAPI:
    return create_app()
