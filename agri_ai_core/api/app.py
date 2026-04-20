# ═══════════════════════════════════════════════════════════════════════════════════
# FastAPI 애플리케이션: REST API 서버, LLM 질의, RAG 엔드포인트.
# --->
# verify_api_key: verify api key
# _try_parse_json: try parse json
# lifespan: lifespan
# _is_private_ip: is private ip
# _to_korean: to korean
# geo_location: 클라이언트 IP 기반 지역 정보 반환 (한글, 최소 구/시/군 단위)
# health_check: health check
# get_ai_judgment: 현재 센서값 기반 AI 환경 판단 조회 (실제 제어 없음)
# get_stats: get stats
# query_llm: query llm
# query_llm_stream: query llm stream
# rag_perform: rag perform
# rag_save: rag save
# get_conversation_history: 세션의 최근 대화 이력을 반환합니다 (최대 limit 개 Q&A 쌍)
# get_available_models: Ollama에 설치된 모델 목록과 현재 선택된 모델을 반환합니다
# change_model: 관리자 전용:
# dispatch: dispatch
# event_generator: event generator
# ═══════════════════════════════════════════════════════════════════════════════════
import json
import os
import time
from typing import Optional
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
from agri_ai_core.api.rpi_router import rpi_router

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


# ════════════════════════════════════════════════
# 바이트/문자열을 JSON 파싱, 실패 시 fallback 반환
# ════════════════════════════════════════════════
def _try_parse_json(data, fallback="(non-JSON)"):
    if not data:
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return fallback


# ═══════════════════════════════════════════════════════════════════
# SSE 스트리밍 질의 엔드포인트 — 실시간 status/token/done 이벤트 전송
# ═══════════════════════════════════════════════════════════════════
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

    # 애플리케이션 초기화 (DB, ChromaDB, 스케줄러, LLM 등)
    from agri_ai_core.startup import initialize_app, shutdown_app
    initialize_app()

    # [Phase 3] 알림 버스에 이벤트 루프 바인딩 (sync 스레드 → SSE 브리지)
    try:
        import asyncio as _asyncio
        from agri_ai_core.src.ai import alert_bus as _alert_bus
        _alert_bus.bind_event_loop(_asyncio.get_running_loop())
    except Exception as _e:
        logger.warning("[alert_bus] 이벤트 루프 바인딩 실패: %s", _e)

    yield

    # 애플리케이션 종료 처리
    shutdown_app()
    logger.info("[REST API] 종료")


app = FastAPI(
    title="AgriAI Core API",
    description="Smart Farm AI Assistant REST API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(voice_router)
app.include_router(rpi_router)
app.add_middleware(JsonLoggingMiddleware)

# CORS 미들웨어
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Accept", "Authorization"],
)


_KR_REGION = {
    "Seoul": "서울특별시", "Busan": "부산광역시", "Daegu": "대구광역시",
    "Incheon": "인천광역시", "Gwangju": "광주광역시", "Daejeon": "대전광역시",
    "Ulsan": "울산광역시", "Sejong": "세종특별자치시",
    "Gyeonggi": "경기도", "Gyeonggi-do": "경기도",
    "Gangwon": "강원도", "Gangwon-do": "강원도",
    "North Chungcheong": "충청북도", "Chungcheongbuk-do": "충청북도",
    "South Chungcheong": "충청남도", "Chungcheongnam-do": "충청남도",
    "North Jeolla": "전라북도", "Jeollabuk-do": "전라북도",
    "South Jeolla": "전라남도", "Jeollanam-do": "전라남도",
    "North Gyeongsang": "경상북도", "Gyeongsangbuk-do": "경상북도",
    "South Gyeongsang": "경상남도", "Gyeongsangnam-do": "경상남도",
    "Jeju": "제주특별자치도", "Jeju-do": "제주특별자치도",
}
_KR_CITY = {
    # 서울 자치구
    "Gwanak-gu": "관악구", "Dongjak-gu": "동작구", "Gangnam-gu": "강남구",
    "Gangdong-gu": "강동구", "Gangbuk-gu": "강북구", "Gangseo-gu": "강서구",
    "Gwangjin-gu": "광진구", "Guro-gu": "구로구", "Geumcheon-gu": "금천구",
    "Nowon-gu": "노원구", "Dobong-gu": "도봉구", "Dongdaemun-gu": "동대문구",
    "Mapo-gu": "마포구", "Seodaemun-gu": "서대문구", "Seocho-gu": "서초구",
    "Seongdong-gu": "성동구", "Seongbuk-gu": "성북구", "Songpa-gu": "송파구",
    "Yangcheon-gu": "양천구", "Yeongdeungpo-gu": "영등포구", "Yongsan-gu": "용산구",
    "Eunpyeong-gu": "은평구", "Jongno-gu": "종로구", "Jung-gu": "중구",
    "Jungnang-gu": "중랑구",
    # 광역시 자치구 (부산 등)
    "Haeundae-gu": "해운대구", "Busanjin-gu": "부산진구", "Nam-gu": "남구",
    "Buk-gu": "북구", "Seo-gu": "서구", "Dong-gu": "동구",
    "Yeonsu-gu": "연수구", "Namdong-gu": "남동구", "Bupyeong-gu": "부평구",
    "Dalseo-gu": "달서구", "Suseong-gu": "수성구",
    # 주요 시
    "Suwon-si": "수원시", "Seongnam-si": "성남시", "Goyang-si": "고양시",
    "Yongin-si": "용인시", "Bucheon-si": "부천시", "Ansan-si": "안산시",
    "Anyang-si": "안양시", "Namyangju-si": "남양주시", "Hwaseong-si": "화성시",
    "Pyeongtaek-si": "평택시", "Uijeongbu-si": "의정부시", "Siheung-si": "시흥시",
    "Paju-si": "파주시", "Gimpo-si": "김포시", "Gwangmyeong-si": "광명시",
    "Gwangju-si": "광주시", "Hanam-si": "하남시", "Gunpo-si": "군포시",
    "Yangju-si": "양주시", "Osan-si": "오산시", "Icheon-si": "이천시",
    "Guri-si": "구리시", "Anseong-si": "안성시", "Pocheon-si": "포천시",
    "Uiwang-si": "의왕시", "Yeoju-si": "여주시", "Dongducheon-si": "동두천시",
    "Gapyeong-gun": "가평군", "Yangpyeong-gun": "양평군", "Yeoncheon-gun": "연천군",
    "Cheongju-si": "청주시", "Chungju-si": "충주시", "Cheonan-si": "천안시",
    "Asan-si": "아산시", "Gongju-si": "공주시", "Sejong-si": "세종시",
    "Jeonju-si": "전주시", "Iksan-si": "익산시", "Gunsan-si": "군산시",
    "Mokpo-si": "목포시", "Yeosu-si": "여수시", "Suncheon-si": "순천시",
    "Pohang-si": "포항시", "Gumi-si": "구미시", "Gyeongju-si": "경주시",
    "Changwon-si": "창원시", "Gimhae-si": "김해시", "Jinju-si": "진주시",
    "Yangsan-si": "양산시", "Geoje-si": "거제시",
    "Chuncheon-si": "춘천시", "Wonju-si": "원주시", "Gangneung-si": "강릉시",
    "Jeju-si": "제주시", "Seogwipo-si": "서귀포시",
}


def _is_private_ip(ip: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


def _to_korean(region_en: str, city_en: str) -> tuple:
    region_kr = _KR_REGION.get(region_en, region_en)
    city_kr = _KR_CITY.get(city_en, city_en)
    return region_kr, city_kr


@app.get("/geo")
async def geo_location(request: Request):
    """클라이언트 IP 기반 지역 정보 반환 (한글, 최소 구/시/군 단위)"""
    client_ip = (
        request.headers.get("X-Real-IP")
        or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip())
        or request.client.host
    )
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            # 사설 IP면 IP 없이 호출 → 서버 공인IP 기반 조회
            url = "https://ipwho.is/" if _is_private_ip(client_ip) else f"https://ipwho.is/{client_ip}"
            resp = await http.get(url)
            data = resp.json()
            if data.get("success", False):
                region_kr, city_kr = _to_korean(data.get("region", ""), data.get("city", ""))
                return {"region": region_kr, "city": city_kr, "ip": data.get("ip", client_ip)}
    except Exception:
        pass
    return {"region": "", "city": "", "ip": client_ip}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════════════
# [Phase 3] Proactive 알림 — SSE 스트림 + 최근 알림 조회
# ═════════════════════════════════════════════════════════════════════════════
@app.get("/api/v1/alerts/recent")
async def alerts_recent(limit: int = 50, level: Optional[str] = None):
    """최근 알림 목록 (신규 구독자가 놓친 이벤트 확인용)."""
    from agri_ai_core.src.ai import alert_bus
    return {"alerts": alert_bus.get_recent(limit=limit, level=level)}


@app.post("/api/v1/alerts/publish")
async def alerts_publish(request: Request):
    """운영/디버그용 — 알림을 수동 발행. 주로 Phase 3 통합 테스트에 사용.
    body: {level, category, farm_id, house_id, title, message, data?}
    """
    from agri_ai_core.src.ai import alert_bus
    body = await request.json()
    evt = alert_bus.publish(
        level=body.get("level", "info"),
        category=body.get("category", "manual"),
        farm_id=body.get("farm_id"),
        house_id=body.get("house_id"),
        title=body.get("title", "알림"),
        message=body.get("message", ""),
        data=body.get("data"),
    )
    return {"success": True, "event": evt}


@app.get("/api/v1/alerts/stream")
async def alerts_stream():
    """SSE: AI 순환 루프 이상 감지 이벤트를 실시간 스트림."""
    import asyncio as _asyncio
    import json as _json
    from fastapi.responses import StreamingResponse
    from agri_ai_core.src.ai import alert_bus

    queue = alert_bus.subscribe(maxsize=100)

    async def _event_gen():
        try:
            # 초기 메시지
            yield f"event: connected\ndata: {_json.dumps({'timestamp': datetime.now().isoformat()})}\n\n"
            while True:
                try:
                    evt = await _asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: alert\ndata: {_json.dumps(evt, ensure_ascii=False)}\n\n"
                except _asyncio.TimeoutError:
                    # keep-alive 핑
                    yield ": ping\n\n"
        finally:
            alert_bus.unsubscribe(queue)

    return StreamingResponse(_event_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.get("/api/v1/ai-judgment/{farm_id}/{house_id}")
async def get_ai_judgment(farm_id: str, house_id: str):
    """현재 센서값 기반 AI 환경 판단 조회 (실제 제어 없음)"""
    from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
    import asyncio

    result = await asyncio.to_thread(get_ai_environment_judgment, farm_id, house_id)
    if result is None:
        return {"success": False, "message": "AI 판단을 수행할 수 없습니다. (센서 데이터 없음)"}
    return {"success": True, **result}


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
            speech_style=request.speech_style or "male",
            auth_farm_id=request.auth_farm_id,
        ):
            result_data = chunk
            break

        # 구조화된 응답 처리
        if isinstance(result_data, dict):
            response_text = clean_llm_response(result_data.get("response", ""))
            sources = result_data.get("sources") or None
            tools_used = result_data.get("tools_used") or None
            response_type = result_data.get("response_type")
            tool_calls_detail = result_data.get("tool_calls_detail") or None  # [E1]
        else:
            response_text = clean_llm_response(str(result_data or ""))
            sources = None
            tools_used = None
            response_type = None
            tool_calls_detail = None

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
            tool_calls_detail=tool_calls_detail,  # [E1] 도구 호출 감사 로그
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
        "[query/stream] session=%s, farm=%s, house=%s, auth_farm=%s, query=%s",
        session_id, request.farm_id, request.house_id, request.auth_farm_id,
        request.query[:200] if request.query else "",
    )
    logger.info(f"[query/stream] auth_farm_id={request.auth_farm_id!r} farm_id={request.farm_id!r}")

    async def event_generator():
        async for chunk in query_llm_simple_stream(
            user_query=request.query,
            farm_id=request.farm_id,
            house_id=request.house_id,
            farm_name=request.farm_name,
            house_name=request.house_name,
            session_id=session_id,
            speech_style=request.speech_style or "male",
            auth_farm_id=request.auth_farm_id,
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

            file_paths.append({"filename": safe_name, "path": file_path, "original_name": base_name})

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


# ══════════════════
# 대화 이력 조회 API
# ══════════════════

@app.get("/api/v1/conversation/history")
async def get_conversation_history(session_id: str, limit: int = 10, _=Depends(verify_api_key)):
    """세션의 최근 대화 이력을 반환합니다 (최대 limit 개 Q&A 쌍)."""
    try:
        from agri_ai_core.src.ai.conversation_store import get_conversation_store
        store = get_conversation_store()
        rows = store.get_recent_turns(session_id, n_turns=limit)
        # [{"role": "user"|"assistant", "content": "..."}] 형태
        return {"success": True, "history": rows, "session_id": session_id}
    except Exception as e:
        logger.warning(f"[대화이력조회] 실패: {e}")
        return {"success": False, "history": [], "session_id": session_id}


# ══════════════════════════════
# 관리자 전용: LLM 모델 관리 API
# ══════════════════════════════

@app.get("/api/v1/admin/models")
async def get_available_models(_=Depends(verify_api_key)):
    """Ollama에 설치된 모델 목록과 현재 선택된 모델을 반환합니다."""
    import httpx

    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    current_model = os.getenv("MODEL_NAME", "")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            size_bytes = m.get("size", 0)
            size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0
            param_size = m.get("details", {}).get("parameter_size", "")
            models.append({
                "name": name,
                "size_gb": size_gb,
                "parameter_size": param_size,
            })

        # 임베딩 모델 제외 (bge, nomic 등)
        embedding_keywords = ["bge", "nomic", "embed"]
        models = [m for m in models if not any(kw in m["name"].lower() for kw in embedding_keywords)]

        return {
            "success": True,
            "current_model": current_model,
            "models": sorted(models, key=lambda x: x["name"]),
        }
    except Exception as e:
        logger.error(f"Ollama 모델 목록 조회 실패: {e}")
        return {"success": False, "error": str(e), "current_model": current_model, "models": []}


@app.post("/api/v1/admin/models")
async def change_model(request: Request, _=Depends(verify_api_key)):
    """관리자 전용: .env 파일의 MODEL_NAME을 변경합니다."""
    body = await request.json()
    new_model = (body.get("model_name") or "").strip()

    if not new_model:
        raise HTTPException(400, "model_name이 필요합니다.")

    env_path = os.path.join(PROJECT_ROOT, ".env")

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # MODEL_NAME 라인을 찾아서 교체
        found = False
        new_lines = []
        # MODEL_PREFIX도 자동 갱신 (콜론 앞 부분)
        new_prefix = new_model.split(":")[0] if ":" in new_model else new_model
        for line in lines:
            if line.startswith("MODEL_NAME="):
                new_lines.append(f"MODEL_NAME={new_model}\n")
                found = True
            elif line.startswith("MODEL_PREFIX="):
                new_lines.append(f"MODEL_PREFIX={new_prefix}\n")
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"MODEL_NAME={new_model}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        old_model = os.getenv("MODEL_NAME", "")

        # 런타임 환경변수 즉시 갱신 (get_model_name()이 os.environ을 최우선 참조)
        os.environ["MODEL_NAME"] = new_model
        os.environ["MODEL_PREFIX"] = new_prefix

        # LLM 클라이언트 모델 캐시 초기화 (다음 호출 시 새 모델 사용)
        try:
            from agri_ai_core.src.ai import llm_client as _llm
            with _llm._model_cache_lock:
                _llm._cached_model_name = None
            logger.info(f"[관리자] 모델 캐시 초기화 완료")
        except Exception as cache_err:
            logger.warning(f"[관리자] 모델 캐시 초기화 실패: {cache_err}")

        logger.info(f"[관리자] LLM 모델 변경: {old_model} → {new_model} (즉시 적용)")
        api_logger.info(f"[admin/models] 모델 변경: {old_model} → {new_model}")

        return {
            "success": True,
            "message": f"모델이 '{new_model}'로 변경되었습니다. 즉시 적용됩니다.",
            "old_model": old_model,
            "new_model": new_model,
        }
    except Exception as e:
        logger.error(f"모델 변경 실패: {e}")
        raise HTTPException(500, f"모델 변경 실패: {str(e)}")


# ════════════════════════════════════════════════════════════
# 로또 추천 API
# ════════════════════════════════════════════════════════════

@app.post("/api/v1/lotto/recommend")
async def lotto_recommend(request: Request):
    """로또 추천 번호 생성."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = body.get("prompt", "")
    from agri_ai_core.src.lotto.lotto_recommender import generate_recommendation
    result = generate_recommendation(prompt)
    return {"success": True, "data": result}


@app.get("/api/v1/lotto/algorithm")
async def lotto_algorithm():
    """로또 추천 알고리즘 설명."""
    from agri_ai_core.src.lotto.lotto_recommender import get_algorithm_description
    return {"success": True, "data": get_algorithm_description()}


@app.post("/api/v1/lotto/analyze-batch")
async def lotto_analyze_batch(request: Request):
    """501회부터 미분석 회차를 LLM으로 일괄 분석한다 (백그라운드 실행)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    start = int(body.get("start", 501))
    end = body.get("end")
    if end is not None:
        end = int(end)

    import threading
    from agri_ai_core.src.lotto.lotto_analyzer import run_batch

    def _worker():
        try:
            run_batch(start=start, end=end)
        except Exception as e:
            logger.error(f"[로또분석] 배치 실행 중 오류: {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"success": True, "data": {"message": f"배치 분석 시작 (start={start}, end={end})"}}


@app.post("/api/v1/lotto/analyze-draw")
async def lotto_analyze_draw(request: Request):
    """단일 회차를 즉시 분석한다."""
    body = await request.json()
    draw_no = int(body.get("draw_no"))
    from agri_ai_core.src.lotto.lotto_analyzer import analyze_draw
    ok = analyze_draw(draw_no)
    return {"success": ok, "data": {"draw_no": draw_no}}


