import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

import uuid

from fastapi import FastAPI, Depends, HTTPException, Security, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, StreamingResponse

from agri_ai_core.logs import setup_logger, setup_web_logger
from agri_ai_core.api.models import (
    QueryRequest, QueryResponse,
    RagSaveRequest, RagResponse,
)
from agri_ai_core.api.voice_router import voice_router

logger = setup_logger(__name__)

# REST API 통신 JSON 로그 전용 (web_YYYY_MM_DD.log에 기록)
api_json_logger = setup_web_logger("api_json")

# API Key 인증 (선택적)
API_KEY = os.getenv("AGRI_API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 업로드 디렉토리 및 보안 설정
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
UPLOAD_DIR = os.getenv("UPLOAD_PATH", os.path.join(PROJECT_ROOT, "upload"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024  # 기본 100MB
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".xlsx"}


async def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _try_parse_json(data, fallback="(non-JSON)"):
    """바이트/문자열을 JSON 파싱, 실패 시 fallback 반환"""
    if not data:
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return fallback


class JsonLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # /api/v1/query는 query_handler_simple.py에서 web 로그 기록 (중복 방지)
        # /api/v1/voice/는 바이너리(음성) 데이터이므로 JSON 로깅 바이패스
        if request.url.path in ("/api/v1/query", "/api/v1/query/stream") or \
           request.url.path.startswith("/api/v1/voice/"):
            return await call_next(request)

        # 요청 body 읽기
        request_body = _try_parse_json(await request.body(), "(binary or non-JSON body)")

        api_json_logger.info(
            "[REST API 요청] %s %s\n%s",
            request.method,
            request.url.path,
            json.dumps(request_body, ensure_ascii=False, indent=2) if isinstance(request_body, (dict, list)) else request_body,
        )

        # 응답 처리
        response = await call_next(request)

        # 응답 body 읽기
        response_body_bytes = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                response_body_bytes += chunk.encode("utf-8")
            else:
                response_body_bytes += chunk

        response_body = _try_parse_json(response_body_bytes, "(non-JSON response)")

        api_json_logger.info(
            "[REST API 응답] %s %s (status=%d)\n%s",
            request.method,
            request.url.path,
            response.status_code,
            json.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, (dict, list)) else response_body,
        )

        return Response(
            content=response_body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_port = os.getenv("API_PORT", "8002")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_key_set = "설정됨" if API_KEY else "미설정(인증 없음)"
    logger.info("[REST API] 시작 (Host=%s, Port=%s, API Key=%s)", api_host, api_port, api_key_set)
    yield
    logger.info("[REST API] 종료")


app = FastAPI(
    title="AgriAI Core API",
    description="Smart Farm AI Assistant REST API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(voice_router)
app.add_middleware(JsonLoggingMiddleware)

# CORS 미들웨어
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/v1/stats")
async def get_stats(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai.stats_collector import get_stats_collector
    return get_stats_collector().get_stats()


@app.post("/api/v1/query", response_model=QueryResponse)
async def query_llm(request: QueryRequest, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai.query_handler_simple import query_llm_simple
    from agri_ai_core.src.ai.llm_client import clean_llm_response

    start = time.time()
    try:
        # session_id가 없으면 자동 생성
        session_id = request.session_id
        if not session_id:
            session_id = str(uuid.uuid4())

        result_data = None
        async for chunk in query_llm_simple(
            user_query=request.query,
            file_paths=None,
            farm_id=request.farm_id,
            house_id=request.house_id,
            farm_name=request.farm_name,
            house_name=request.house_name,
            session_id=session_id,
        ):
            result_data = chunk
            break

        # 구조화된 응답 처리
        if isinstance(result_data, dict):
            response_text = clean_llm_response(result_data.get("response", ""))
            sources = result_data.get("sources") or None  # API 응답에서 빈 목록은 null로 표시
            tools_used = result_data.get("tools_used") or None  # API 응답에서 빈 목록은 null로 표시
            response_type = result_data.get("response_type")
        else:
            response_text = clean_llm_response(str(result_data or ""))
            sources = None
            tools_used = None
            response_type = None

        processing_time = round(time.time() - start, 3)

        # 통계 기록
        from agri_ai_core.src.ai.stats_collector import get_stats_collector
        get_stats_collector().record_query(
            success=True,
            processing_time=processing_time,
            tools_used=tools_used,
            response_type=response_type,
        )

        return QueryResponse(
            success=True,
            response=response_text,
            processing_time=processing_time,
            session_id=session_id,
            sources=sources,
            tools_used=tools_used,
            response_type=response_type,
        )
    except Exception as e:
        logger.error(f"API 질의 오류: {e}")
        processing_time = round(time.time() - start, 3)

        from agri_ai_core.src.ai.stats_collector import get_stats_collector
        get_stats_collector().record_query(success=False, processing_time=processing_time)

        return QueryResponse(
            success=False,
            response=f"오류: {str(e)}",
            processing_time=processing_time,
        )


@app.post("/api/v1/query/stream")
async def query_llm_stream(request: QueryRequest, _=Depends(verify_api_key)):
    """SSE 스트리밍 질의 엔드포인트 — 실시간 status/token/done 이벤트 전송"""
    from agri_ai_core.src.ai.query_handler_simple import query_llm_simple_stream

    session_id = request.session_id
    if not session_id:
        session_id = str(uuid.uuid4())

    async def event_generator():
        async for chunk in query_llm_simple_stream(
            user_query=request.query,
            farm_id=request.farm_id,
            house_id=request.house_id,
            farm_name=request.farm_name,
            house_name=request.house_name,
            session_id=session_id,
        ):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성화
        },
    )


@app.post("/api/v1/rag/perform", response_model=RagResponse)
async def rag_perform(
    files: list[UploadFile] = File(...),
    farm_id: str = Form(default=None),
    _=Depends(verify_api_key),
):
    from agri_ai_core.src.ai.rag.document_processor import process_attached_files

    start = time.time()
    try:
        file_paths = []
        for upload_file in files:
            # 확장자 검증
            ext = os.path.splitext(upload_file.filename or "")[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(400, f"허용되지 않는 파일 형식: {ext} (허용: {', '.join(ALLOWED_EXTENSIONS)})")

            content = await upload_file.read()

            # 파일 크기 검증
            if len(content) > MAX_UPLOAD_SIZE:
                raise HTTPException(413, f"파일 크기 초과: {upload_file.filename} ({len(content) // (1024*1024)}MB > {MAX_UPLOAD_SIZE // (1024*1024)}MB)")

            # UUID 접두사로 파일명 충돌 방지
            base_name = os.path.basename(upload_file.filename or "upload")
            safe_name = f"{uuid.uuid4().hex[:8]}_{base_name}" if base_name else "upload"
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            with open(file_path, "wb") as f:
                f.write(content)
            file_paths.append({"filename": safe_name, "path": file_path})

        api_json_logger.info(
            "[REST API 요청] POST /api/v1/rag/perform\n%s",
            json.dumps({"files": [fp["filename"] for fp in file_paths], "farm_id": farm_id}, ensure_ascii=False, indent=2),
        )

        result_message = process_attached_files(file_paths, farm_id)

        return RagResponse(
            success=True,
            message=result_message,
            processing_time=round(time.time() - start, 3),
        )
    except Exception as e:
        logger.error(f"RAG 수행 오류: {e}")
        return RagResponse(
            success=False,
            message=f"RAG 수행 중 오류: {str(e)}",
            processing_time=round(time.time() - start, 3),
        )


@app.post("/api/v1/rag/save", response_model=RagResponse)
async def rag_save(request: RagSaveRequest, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai.rag.document_processor import (
        llm_document_process, messages_to_text, format_rag_save_result,
    )

    start = time.time()
    try:
        if not request.messages:
            return RagResponse(
                success=False,
                message="저장할 대화 내용이 없습니다.",
                processing_time=round(time.time() - start, 3),
            )

        # 공통 함수로 대화→텍스트 변환
        conversation_text = messages_to_text(
            request.messages, request.farm_name, request.house_name,
        )

        result = llm_document_process(
            text_content=conversation_text,
            farm_id=request.farm_id,
        )

        # 공통 함수로 결과 포맷팅
        success, message = format_rag_save_result(result, len(request.messages))
        return RagResponse(
            success=success,
            message=message,
            processing_time=round(time.time() - start, 3),
        )
    except Exception as e:
        logger.error(f"RAG 저장 오류: {e}")
        return RagResponse(
            success=False,
            message=f"RAG 저장 중 오류: {str(e)}",
            processing_time=round(time.time() - start, 3),
        )
