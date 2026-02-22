import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Security, UploadFile, File, Form, Request
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from agri_ai_core.logs import setup_logger, setup_web_logger
from agri_ai_core.api.models import (
    QueryRequest, QueryResponse,
    RagSaveRequest, RagResponse,
)

logger = setup_logger(__name__)

# REST API 통신 JSON 로그 전용 (web_YYYY_MM_DD.log에 기록)
api_json_logger = setup_web_logger("api_json")

# API Key 인증 (선택적)
API_KEY = os.getenv("AGRI_API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 업로드 디렉토리
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
UPLOAD_DIR = os.getenv("UPLOAD_PATH", os.path.join(PROJECT_ROOT, "upload"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


class JsonLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # /api/v1/query는 query_handler_simple.py에서 web 로그 기록 (중복 방지)
        if request.url.path == "/api/v1/query":
            return await call_next(request)

        # 요청 body 읽기
        body_bytes = await request.body()
        request_body = None
        if body_bytes:
            try:
                request_body = json.loads(body_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError):
                request_body = "(binary or non-JSON body)"

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

        response_body = None
        try:
            response_body = json.loads(response_body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_body = "(non-JSON response)"

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

app.add_middleware(JsonLoggingMiddleware)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/v1/query", response_model=QueryResponse)
async def query_llm(request: QueryRequest, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai.query_handler_simple import query_llm_simple
    from agri_ai_core.src.ai.llm_client import clean_llm_response

    start = time.time()
    try:
        response_text = ""
        async for chunk in query_llm_simple(
            user_query=request.query,
            file_paths=None,
            farm_id=request.farm_id,
            house_id=request.house_id,
            farm_name=request.farm_name,
            house_name=request.house_name,
        ):
            response_text = chunk
            break

        response_text = clean_llm_response(response_text)
        return QueryResponse(
            success=True,
            response=response_text,
            processing_time=round(time.time() - start, 3),
        )
    except Exception as e:
        logger.error(f"API 질의 오류: {e}")
        return QueryResponse(
            success=False,
            response=f"오류: {str(e)}",
            processing_time=round(time.time() - start, 3),
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
            file_path = os.path.join(UPLOAD_DIR, upload_file.filename)
            content = await upload_file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            file_paths.append({"filename": upload_file.filename, "path": file_path})

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
