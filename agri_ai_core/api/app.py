# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# FastAPI 애플리케이션 모듈
# REST API 서버 설정, 라우팅, 미들웨어, 수명주기 관리를 담당하며,
# LLM 질의(동기/SSE 스트리밍), RAG 검색/저장 엔드포인트를 제공합니다.
# --->
# verify_api_key: API 키 인증 미들웨어
# _try_parse_json: 바이트/문자열을 JSON 파싱, 실패 시 fallback 반환
# JsonLoggingMiddleware: SSE 스트리밍 질의 엔드포인트 — 실시간 status/token/done 이벤트 전송
# lifespan: FastAPI 앱 수명주기 관리 (시작/종료)
# health_check: 서버 상태 확인 엔드포인트
# get_stats: 통계 조회
# query_llm: LLM 질의 엔드포인트 (동기)
# query_llm_stream: LLM 질의 SSE 스트리밍 엔드포인트
# rag_perform: RAG 검색 수행 엔드포인트
# rag_save: RAG 문서 저장 엔드포인트
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import json
import os
import time
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Depends, HTTPException, Security, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, StreamingResponse

from agri_ai_core.logs import setup_logger, setup_web_logger, setup_api_logger
from agri_ai_core.api.models import (
    QueryRequest, QueryResponse,
    RagSaveRequest, RagResponse,
)
from agri_ai_core.api.voice_router import voice_router

logger = setup_logger(__name__)

# REST API 통신 JSON 로그 전용 (web_YYYY_MM_DD.log에 기록)
api_json_logger = setup_web_logger("api_json")

# API 전용 로거 (api.log에 기록 — 모든 API 경유 내용 로깅)
api_logger = setup_api_logger("api")

# API Key 인증 (선택적)
API_KEY = os.getenv("AGRI_API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 업로드 디렉토리 및 보안 설정
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
UPLOAD_DIR = os.getenv("UPLOAD_PATH", os.path.join(PROJECT_ROOT, "upload"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024  # 기본 100MB
ALLOWED_EXTENSIONS = {".txt", ".csv", ".pdf", ".xlsx", ".xls", ".json", ".md"}


async def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ============================================================
# 바이트/문자열을 JSON 파싱, 실패 시 fallback 반환
# ============================================================
def _try_parse_json(data, fallback="(non-JSON)"):
    if not data:
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return fallback


# ============================================================
# SSE 스트리밍 질의 엔드포인트 — 실시간 status/token/done 이벤트 전송
# ============================================================
class JsonLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        start_time = time.time()
        client_ip = request.client.host if request.client else "-"

        # 모든 API 요청을 api.log에 기록 (INFO)
        api_logger.info("[API 요청] %s %s (client=%s)", request.method, request.url.path, client_ip)

        # DEBUG: 요청 헤더 상세
        api_logger.debug(
            "[API 요청 상세] %s %s query=%s headers=%s",
            request.method, request.url.path,
            str(request.query_params) if request.query_params else "{}",
            {k: v for k, v in request.headers.items() if k.lower() not in ("authorization", "x-api-key", "cookie")},
        )

        # /api/v1/query는 query_handler_simple.py에서 web 로그 기록 (중복 방지)
        # /api/v1/voice/는 바이너리(음성) 데이터이므로 JSON 로깅 바이패스
        is_bypass = (
            request.url.path in ("/api/v1/query", "/api/v1/query/stream")
            or request.url.path.startswith("/api/v1/voice/")
        )

        if is_bypass:
            response = await call_next(request)
            elapsed = round(time.time() - start_time, 3)
            api_logger.info(
                "[API 응답] %s %s (status=%d, %.3fs)",
                request.method, request.url.path, response.status_code, elapsed,
            )
            return response

        # 요청 body 읽기
        request_body = _try_parse_json(await request.body(), "(binary or non-JSON body)")

        # web 로그 (기존 유지)
        api_json_logger.info(
            "[REST API 요청] %s %s\n%s",
            request.method,
            request.url.path,
            json.dumps(request_body, ensure_ascii=False, indent=2) if isinstance(request_body, (dict, list)) else request_body,
        )

        # DEBUG: 요청 body를 api.log에도 기록
        if isinstance(request_body, (dict, list)):
            api_logger.debug(
                "[API 요청 body] %s %s\n%s",
                request.method, request.url.path,
                json.dumps(request_body, ensure_ascii=False, indent=2),
            )

        # 응답 처리
        response = await call_next(request)

        # StreamingResponse인 경우 body 읽지 않고 통과 (메모리 적재 방지)
        if isinstance(response, StreamingResponse):
            elapsed = round(time.time() - start_time, 3)
            api_logger.info(
                "[API 응답] %s %s (status=%d, %.3fs, streaming)",
                request.method, request.url.path, response.status_code, elapsed,
            )
            return response

        # 일반 응답 body 읽기
        response_body_bytes = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                response_body_bytes += chunk.encode("utf-8")
            else:
                response_body_bytes += chunk

        response_body = _try_parse_json(response_body_bytes, "(non-JSON response)")

        elapsed = round(time.time() - start_time, 3)

        # web 로그 (기존 유지)
        api_json_logger.info(
            "[REST API 응답] %s %s (status=%d)\n%s",
            request.method,
            request.url.path,
            response.status_code,
            json.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, (dict, list)) else response_body,
        )

        # api.log INFO: 응답 요약
        api_logger.info(
            "[API 응답] %s %s (status=%d, %.3fs, %dB)",
            request.method, request.url.path,
            response.status_code, elapsed, len(response_body_bytes),
        )

        # api.log DEBUG: 응답 body 상세
        if isinstance(response_body, (dict, list)):
            api_logger.debug(
                "[API 응답 body] %s %s\n%s",
                request.method, request.url.path,
                json.dumps(response_body, ensure_ascii=False, indent=2),
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Accept", "Authorization"],
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

        api_logger.debug(
            "[query] session=%s, farm=%s, house=%s, query=%s",
            session_id, request.farm_id, request.house_id,
            request.query[:200] if request.query else "",
        )

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
            sources = result_data.get("sources") or None
            tools_used = result_data.get("tools_used") or None
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

        api_logger.debug(
            "[query 완료] session=%s, %.3fs, type=%s, tools=%s, response=%s",
            session_id, processing_time, response_type, tools_used,
            response_text[:300] if response_text else "",
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
        api_logger.error("[query 오류] %s", e)
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
    from agri_ai_core.src.ai.query_handler_simple import query_llm_simple_stream

    session_id = request.session_id
    if not session_id:
        session_id = str(uuid.uuid4())

    api_logger.debug(
        "[query/stream] session=%s, farm=%s, house=%s, query=%s",
        session_id, request.farm_id, request.house_id,
        request.query[:200] if request.query else "",
    )

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

            # UUID 접두사로 파일명 충돌 방지
            base_name = os.path.basename(upload_file.filename or "upload")
            safe_name = f"{uuid.uuid4().hex[:8]}_{base_name}" if base_name else "upload"
            file_path = os.path.join(UPLOAD_DIR, safe_name)

            # 청크 단위 스트리밍 저장 — 전체 read() 대신 메모리 절약
            total_size = 0
            _CHUNK_SIZE = 1024 * 1024  # 1MB
            with open(file_path, "wb") as f:
                while True:
                    chunk = await upload_file.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_UPLOAD_SIZE:
                        f.close()
                        os.remove(file_path)
                        raise HTTPException(413, f"파일 크기 초과: {upload_file.filename} ({total_size // (1024*1024)}MB > {MAX_UPLOAD_SIZE // (1024*1024)}MB)")
                    f.write(chunk)

            file_paths.append({"filename": safe_name, "path": file_path})

        api_json_logger.info(
            "[REST API 요청] POST /api/v1/rag/perform\n%s",
            json.dumps({"files": [fp["filename"] for fp in file_paths], "farm_id": farm_id}, ensure_ascii=False, indent=2),
        )

        api_logger.debug(
            "[rag/perform] files=%s, farm_id=%s",
            [fp["filename"] for fp in file_paths], farm_id,
        )

        result_message = process_attached_files(file_paths, farm_id)
        processing_time = round(time.time() - start, 3)

        api_logger.debug("[rag/perform 완료] %.3fs, result=%s", processing_time, result_message[:200] if result_message else "")

        return RagResponse(
            success=True,
            message=result_message,
            processing_time=processing_time,
        )
    except Exception as e:
        logger.error(f"RAG 수행 오류: {e}")
        api_logger.error("[rag/perform 오류] %s", e)
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

        api_logger.debug(
            "[rag/save] farm=%s, messages=%d, farm_name=%s",
            request.farm_id, len(request.messages), request.farm_name,
        )

        result = llm_document_process(
            text_content=conversation_text,
            farm_id=request.farm_id,
        )

        # 공통 함수로 결과 포맷팅
        success, message = format_rag_save_result(result, len(request.messages))
        processing_time = round(time.time() - start, 3)

        api_logger.debug("[rag/save 완료] %.3fs, success=%s", processing_time, success)

        return RagResponse(
            success=success,
            message=message,
            processing_time=processing_time,
        )
    except Exception as e:
        logger.error(f"RAG 저장 오류: {e}")
        api_logger.error("[rag/save 오류] %s", e)
        return RagResponse(
            success=False,
            message=f"RAG 저장 중 오류: {str(e)}",
            processing_time=round(time.time() - start, 3),
        )
