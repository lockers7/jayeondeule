# ════════════════════════════════════════════════════════════════════
# FastAPI 애플리케이션 — REST API 서버, LLM 질의, RAG·알림 SSE 엔드포인트.
# --->
# verify_api_key             : X-API-Key 헤더 검증 (선택적 인증)
# _try_parse_json            : 바이트/문자열 JSON 파싱, 실패 시 fallback
# JsonLoggingMiddleware.dispatch : /api/* 요청·응답을 web/api 로그에 기록
# lifespan                   : 앱 lifecycle — 시작/종료 시 DB·스케줄러 등 초기화
# _is_private_ip             : 사설 IP 여부 판정 (geo 조회용)
# _to_korean                 : 영문 region/city → 한국어 명칭 매핑
# geo_location               : GET  /geo                          — 클라이언트 IP 기반 지역
# health_check               : GET  /health                       — 헬스체크
# alerts_recent              : GET  /api/v1/alerts/recent         — 최근 알림 목록
# alerts_publish             : POST /api/v1/alerts/publish        — 운영/디버그용 알림 수동 발행
# alerts_stream              : GET  /api/v1/alerts/stream         — SSE 알림 스트림 (Last-Event-ID 지원)
# alerts_stats               : GET  /api/v1/alerts/stats          — alert_bus 관측성 통계
# pg_pool_stats              : GET  /api/v1/system/pg_pool        — PG 커넥션 풀 상태
# get_ai_judgment            : GET  /api/v1/ai-judgment/{f}/{h}   — 현재 센서값 기반 AI 환경 판단
# get_stats                  : GET  /api/v1/stats                 — 통계 수집기 스냅샷
# query_llm                  : POST /api/v1/query                 — 단발 LLM 질의 (4단계 step 로그)
# query_llm_stream           : POST /api/v1/query/stream          — SSE 토큰 스트림 LLM 질의
# rag_perform                : POST /api/v1/rag/perform           — 첨부파일 RAG 처리 (스트리밍 업로드)
# rag_save                   : POST /api/v1/rag/save              — 대화내역 RAG 저장
# get_conversation_history   : GET  /api/v1/conversation/history  — 세션 최근 Q&A 쌍 조회
# get_available_models       : GET  /api/v1/admin/models          — Ollama 설치 모델 목록
# change_model               : POST /api/v1/admin/models          — .env MODEL_NAME 변경 (즉시 적용)
# lotto_recommend            : POST /api/v1/lotto/recommend       — 로또 추천 번호 생성
# lotto_algorithm            : GET  /api/v1/lotto/algorithm       — 추천 알고리즘 설명
# lotto_analyze_batch        : POST /api/v1/lotto/analyze-batch   — 미분석 회차 LLM 일괄 분석
# lotto_analyze_draw         : POST /api/v1/lotto/analyze-draw    — 단일 회차 즉시 분석
# ════════════════════════════════════════════════════════════════════
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
# [2026-04-28] AI 결정 피드백 API (M15)
from agri_ai_core.api.ai_feedback_router import ai_feedback_router

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


# ────────────────────────────────────────────────────────────────────
# X-API-Key 헤더 검증 — AGRI_API_KEY 미설정 시 인증 우회 (개발 모드).
# ────────────────────────────────────────────────────────────────────
async def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ────────────────────────────────────────────────────────────────────
# 바이트/문자열을 JSON 파싱 — 실패 시 fallback 문자열 반환 (예외 미발생).
# ────────────────────────────────────────────────────────────────────
def _try_parse_json(data, fallback="(non-JSON)"):
    if not data:
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return fallback


# ════════════════════════════════════════════════════════════════════
# JSON 로깅 미들웨어 — /api/* 요청·응답을 web/api 로그에 기록.
# /api/v1/query 와 /api/v1/voice/* 는 바이패스 (별도 로깅 또는 바이너리).
# StreamingResponse 는 body 미적재 (메모리 절약).
# ════════════════════════════════════════════════════════════════════
class JsonLoggingMiddleware(BaseHTTPMiddleware):
    # ────────────────────────────────────────────────────────────────
    # ASGI 요청 인터셉트 — request/response body 를 JSON 으로 직렬화 후
    # api_json_logger(web 로그) + api_logger(api 로그) 양쪽에 기록.
    # ────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────
# FastAPI lifespan — 시작 시 DB·ChromaDB·스케줄러·LLM 초기화, alert_bus
# 이벤트 루프 바인딩, Wave 7 Agent monitor Job 영속 복원. 종료 시 정리.
# ────────────────────────────────────────────────────────────────────
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

    # [Wave 7] Agent 모니터링 Job 영속 복원 — 서비스 재시작 후 active Job 재등록
    try:
        from agri_ai_core.src.ai.tools_agent import restore_active_jobs as _restore_agent_jobs
        _restored = _restore_agent_jobs()
        if _restored:
            logger.info("[Agent] 재시작 후 monitor Job %d건 복원", _restored)
    except Exception as _e:
        logger.warning("[Agent] monitor Job 복원 실패: %s", _e)

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
app.include_router(ai_feedback_router)  # [2026-04-28]
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


# ────────────────────────────────────────────────────────────────────
# 사설 IP 여부 판정 — geo 조회 시 사설 IP 면 ipwho.is 의 자기자신 IP 사용.
# 파싱 실패도 사설 취급 (보수적 동작).
# ────────────────────────────────────────────────────────────────────
def _is_private_ip(ip: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


# ────────────────────────────────────────────────────────────────────
# 영문 region/city → 한국어 행정구역명 매핑 (ipwho.is 응답 정규화).
# 미매핑 항목은 영문 원문 그대로 반환.
# ────────────────────────────────────────────────────────────────────
def _to_korean(region_en: str, city_en: str) -> tuple:
    region_kr = _KR_REGION.get(region_en, region_en)
    city_kr = _KR_CITY.get(city_en, city_en)
    return region_kr, city_kr


# ────────────────────────────────────────────────────────────────────
# 클라이언트 IP 기반 지역 정보 반환 (한글, 최소 구/시/군 단위).
# X-Real-IP / X-Forwarded-For 헤더 우선. ipwho.is 외부 API 사용.
# ────────────────────────────────────────────────────────────────────
@app.get("/geo")
async def geo_location(request: Request):
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


# ────────────────────────────────────────────────────────────────────
# 헬스체크 — {"status": "ok"} 단순 응답.
# ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════════════
# [Phase 3] Proactive 알림 — SSE 스트림 + 최근 알림 조회
# ════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────────
# 최근 알림 목록 — 신규 구독자가 놓친 이벤트 확인용.
# level 미지정 시 전체. limit 기본 50.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/alerts/recent")
async def alerts_recent(limit: int = 50, level: Optional[str] = None):
    from agri_ai_core.src.ai import alert_bus
    return {"alerts": alert_bus.get_recent(limit=limit, level=level)}


# ────────────────────────────────────────────────────────────────────
# 알림 수동 발행 — 운영/디버그용. 주로 Phase 3 통합 테스트에 사용.
# body: {level, category, farm_id, house_id, title, message, data?}
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/alerts/publish")
async def alerts_publish(request: Request):
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


# ────────────────────────────────────────────────────────────────────
# SSE 스트림 — AI 순환 루프 이상 감지 이벤트를 실시간 전송.
# [Wave 10] Last-Event-ID 헤더 지원 (재연결 시 놓친 이벤트 복원), 각
# 이벤트에 id: 필드 첨부 (SSE 표준 자동 재연결).
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/alerts/stream")
async def alerts_stream(request: Request):
    import asyncio as _asyncio
    import json as _json
    from fastapi.responses import StreamingResponse
    from agri_ai_core.src.ai import alert_bus

    last_event_id = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    queue = alert_bus.subscribe(maxsize=100)

    # ────────────────────────────────────────────────────────────────
    # SSE 이벤트 generator — connected 핸드셰이크 → Last-Event-ID 복원
    # → 큐 폴링 (25초 타임아웃 시 keep-alive 핑).
    # ────────────────────────────────────────────────────────────────
    async def _event_gen():
        try:
            # 초기 메시지
            yield f"event: connected\ndata: {_json.dumps({'timestamp': datetime.now().isoformat()})}\n\n"

            # [Wave 10] 재연결 시 Last-Event-ID 이후 이벤트 즉시 복원
            if last_event_id:
                replay = alert_bus.get_events_since(last_event_id, max_items=50)
                for evt in replay:
                    eid = evt.get("id", "")
                    yield f"id: {eid}\nevent: alert\ndata: {_json.dumps(evt, ensure_ascii=False)}\n\n"
                if replay:
                    logger.info("[alerts_stream] Last-Event-ID=%s 이후 %d건 복원", last_event_id, len(replay))

            while True:
                try:
                    evt = await _asyncio.wait_for(queue.get(), timeout=25.0)
                    eid = evt.get("id", "")
                    yield f"id: {eid}\nevent: alert\ndata: {_json.dumps(evt, ensure_ascii=False)}\n\n"
                except _asyncio.TimeoutError:
                    # keep-alive 핑
                    yield ": ping\n\n"
        finally:
            alert_bus.unsubscribe(queue)

    return StreamingResponse(_event_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ────────────────────────────────────────────────────────────────────
# alert_bus 관측성 통계 — published / dropped / subscribers / buffer_size.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/alerts/stats")
async def alerts_stats():
    from agri_ai_core.src.ai import alert_bus
    return {"success": True, **alert_bus.get_stats()}


# ────────────────────────────────────────────────────────────────────
# [Wave 11] PostgreSQL 커넥션 풀 실시간 상태 (min/max/in_use/idle).
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/system/pg_pool")
async def pg_pool_stats():
    from agri_ai_core.src.postgresql.connection import db as _db
    stats = _db.get_pool_stats()
    return {"success": True, **stats}


# ────────────────────────────────────────────────────────────────────
# 현재 센서값 기반 AI 환경 판단 조회 — 실제 제어 없이 판단 결과만 반환.
# manual_control.get_ai_environment_judgment 를 to_thread 로 호출.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/ai-judgment/{farm_id}/{house_id}")
async def get_ai_judgment(farm_id: str, house_id: str):
    from agri_ai_core.src.control.manual_control import get_ai_environment_judgment
    import asyncio

    result = await asyncio.to_thread(get_ai_environment_judgment, farm_id, house_id)
    if result is None:
        return {"success": False, "message": "AI 판단을 수행할 수 없습니다. (센서 데이터 없음)"}
    return {"success": True, **result}


# ────────────────────────────────────────────────────────────────────
# 통계 수집기 스냅샷 — query/RAG 호출 카운트·평균 응답 시간 등.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/stats")
async def get_stats(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai.stats_collector import get_stats_collector
    return get_stats_collector().get_stats()


# ────────────────────────────────────────────────────────────────────
# 단발 LLM 질의 — query_handler_simple 1회 호출, 4단계 step 로그 기록.
# session_id 미지정 시 UUID4 자동 생성. tool_calls_detail 로 도구 호출 추적.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/query", response_model=QueryResponse)
async def query_llm(request: QueryRequest, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai.query_handler_simple import query_llm_simple
    from agri_ai_core.src.ai.llm_client import clean_llm_response
    # [2026-04-28] LLM 대화 단계 로그 — AI/ALGO 와 동일 포맷
    from agri_ai_core.src.control.ai_step_logger import AiStepLogger

    start = time.time()
    try:
        # session_id가 없으면 자동 생성
        session_id = request.session_id
        if not session_id:
            session_id = str(uuid.uuid4())

        scope = f"[대화 {session_id[:8]}]"
        steps = AiStepLogger(scope=scope, total=4, prefix='LLM')

        # ─── [LLM 1/4] 요청 접수 ───
        steps.step("질의 접수",
                   extra=f"farm={request.farm_id} house={request.house_id} "
                         f"len={len(request.query or '')}자")
        steps.detail(
            f"session={session_id}",
            f"farm_name={request.farm_name} / house_name={request.house_name}",
            f"speech_style={request.speech_style or 'male'} "
            f"auth_farm_id={request.auth_farm_id}",
            f"질의 본문: {request.query or ''}",
        )

        api_logger.debug(
            "[query] session=%s, farm=%s, house=%s, query=%s",
            session_id, request.farm_id, request.house_id,
            request.query[:200] if request.query else "",
        )

        # ─── [LLM 2/4] LLM 처리 (query_handler_simple) ───
        steps.step("LLM 처리 호출", extra="query_handler_simple → tools/RAG/chat")
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

        # ─── [LLM 3/4] 응답 정제·메타 ───
        steps.step("응답 정제·메타",
                   extra=f"type={response_type} tools={len(tools_used) if tools_used else 0} "
                         f"sources={len(sources) if sources else 0} "
                         f"resp={len(response_text or '')}자 ({processing_time}s)")
        steps.detail(
            f"response_type={response_type}",
            f"tools_used={tools_used}",
            f"sources={sources}",
            f"tool_calls_detail={tool_calls_detail}",
            f"응답 본문 (최대 800자): {response_text or ''}",
        )

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

        # ─── [LLM 4/4] 응답 반환 ───
        steps.step("응답 반환", extra=f"success=True · {processing_time}s")
        steps.done(summary=f"{len(response_text or '')}자 응답 / {processing_time}s")

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

        try:
            steps.warn("응답 반환", reason=f"예외 발생: {e}")
        except Exception:
            pass

        return QueryResponse(
            success=False,
            response=f"오류: {str(e)}",
            processing_time=processing_time,
        )


# ────────────────────────────────────────────────────────────────────
# SSE 토큰 스트림 LLM 질의 — query_handler_simple_stream 결과를 chunk
# 단위로 SSE 전송. 마지막에 [DONE] 마커. nginx 버퍼링 비활성화 헤더 포함.
# ────────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # SSE 이벤트 generator — query_llm_simple_stream chunk 를 data: 로 직렬화.
    # ────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────
# 첨부파일 RAG 처리 — 다중 파일 업로드(스트리밍·1MB 청크) → 확장자/크기
# 검증 → process_attached_files 위임. UUID 접두사로 파일명 충돌 방지.
# ────────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────
# 대화내역 RAG 저장 — 메시지 목록을 텍스트로 변환 후 llm_document_process
# 위임. format_rag_save_result 로 success/message 정규화 응답.
# ────────────────────────────────────────────────────────────────────
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

# ────────────────────────────────────────────────────────────────────
# 세션의 최근 대화 이력 조회 — 최대 limit 개 Q&A 쌍 반환.
# conversation_store.get_recent_turns 위임. 실패 시 history=[] 로 graceful.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/conversation/history")
async def get_conversation_history(session_id: str, limit: int = 10, _=Depends(verify_api_key)):
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

# ────────────────────────────────────────────────────────────────────
# Ollama 설치 모델 목록 + 현재 선택된 모델 반환 (관리자 전용).
# 임베딩 모델(bge/nomic/embed) 은 응답에서 제외.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/models")
async def get_available_models(_=Depends(verify_api_key)):
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


# ────────────────────────────────────────────────────────────────────
# .env MODEL_NAME 변경 (관리자 전용) — MODEL_PREFIX 도 콜론 앞부분으로 자동 갱신.
# os.environ 즉시 갱신 + LLM 클라이언트 모델 캐시 초기화 → 다음 호출부터 적용.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/admin/models")
async def change_model(request: Request, _=Depends(verify_api_key)):
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

        # ─── ollama 강제 swap — 재시작 후 새 모델만 로드 ───
        # 진행 중 LLM 호출이 keep_alive=-1 로 옛 모델 영구 상주를 계속 갱신하는
        # race condition 회피. ollama 재시작으로 큐를 강제 비우고 .env 의 새 모델로
        # 단일 로드 보장. sudo 비번은 user_m_info.sudo_passwd 에서 읽어 사용
        # (사용자가 비번 변경 시 본 컬럼만 업데이트하면 즉시 반영).
        try:
            import subprocess, urllib.request, json as _json, time as _time
            if old_model != new_model:
                # DB 에서 sudo 비번 조회 (auth_lvel 가장 높은 사용자)
                _sudo_pw = None
                try:
                    from agri_ai_core.src.postgresql.connection import db
                    _conn = db._getconn()
                    if _conn:
                        try:
                            with _conn.cursor() as _cur:
                                _cur.execute("""
                                    SELECT sudo_passwd FROM user_m_info
                                    WHERE sudo_passwd IS NOT NULL AND dlte_yn='N'
                                    ORDER BY auth_lvel DESC LIMIT 1
                                """)
                                _row = _cur.fetchone()
                                if _row and _row[0]:
                                    _sudo_pw = _row[0]
                        finally:
                            try: db._putconn(_conn)
                            except Exception: pass
                except Exception as _db_err:
                    logger.warning(f"[관리자] sudo 비번 DB 조회 실패: {_db_err}")

                # ollama 재시작 — NOPASSWD 우선 시도, 실패 시 DB 비번으로 sudo -S
                try:
                    if _sudo_pw:
                        subprocess.run(
                            ['sudo', '-S', '-p', '', '/usr/bin/systemctl', 'restart', 'ollama.service'],
                            input=f'{_sudo_pw}\n', text=True,
                            timeout=20, check=True,
                            capture_output=True,
                        )
                        logger.info("[관리자] ollama 재시작 완료 (DB sudo 비번) — 옛 모델 강제 unload")
                    else:
                        subprocess.run(
                            ['sudo', '-n', '/usr/bin/systemctl', 'restart', 'ollama.service'],
                            timeout=20, check=True,
                        )
                        logger.info("[관리자] ollama 재시작 완료 (NOPASSWD) — 옛 모델 강제 unload")
                except Exception as _e:
                    logger.warning(f"[관리자] ollama 재시작 실패: {_e} — keep_alive 폴백 시도")
                # 재시작 후 안정화 대기
                _time.sleep(4)

            # 새 모델 강제 load — keep_alive=-1 (영구 상주)
            ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
            try:
                req = urllib.request.Request(
                    f"{ollama_url}/api/generate",
                    data=_json.dumps({
                        "model": new_model, "prompt": "hi", "stream": False,
                        "options": {"num_predict": 3},
                        "keep_alive": -1,
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=240).read()
                logger.info(f"[관리자] 새 모델 load 완료: {new_model}")
            except Exception as _e:
                logger.warning(f"[관리자] 새 모델 load 실패: {_e}")
        except Exception as _swap_err:
            logger.warning(f"[관리자] ollama swap 처리 실패: {_swap_err}")

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


# ════════════════════════════════════════════════════════════════════
# sudo 비밀번호 변경 — 시스템(Linux jayeondeule) + DB(user_m_info) 동기화
# body: { "old_password":"...", "new_password":"..." }
# 1. 현 sudo_passwd 검증 (DB 의 가장 높은 auth_lvel 사용자 row)
# 2. 시스템 chpasswd 로 jayeondeule 계정 비번 변경 (현 sudo 비번으로 sudo -S)
# 3. user_m_info.sudo_passwd 모든 관리자 row 업데이트
# 두 가지를 단일 트랜잭션처럼 동기화 — 중간 실패 시 롤백 안내.
# ════════════════════════════════════════════════════════════════════
@app.post("/api/v1/admin/sudo-password")
async def change_sudo_password(request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    old_pw = (body.get("old_password") or "").strip()
    new_pw = (body.get("new_password") or "").strip()

    if not old_pw or not new_pw:
        raise HTTPException(400, "old_password 와 new_password 가 필요합니다.")
    if len(new_pw) < 8:
        raise HTTPException(400, "new_password 는 8자 이상이어야 합니다.")

    # (1) 현 sudo_passwd 검증
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT user_id, sudo_passwd FROM user_m_info
                    WHERE sudo_passwd IS NOT NULL AND dlte_yn='N'
                    ORDER BY auth_lvel DESC LIMIT 1
                """)
                row = cur.fetchone()
                if not row or not row[1]:
                    raise HTTPException(400, "현 sudo 비밀번호가 DB 에 등록돼 있지 않습니다.")
                current_sudo = row[1]
        finally:
            try: db._putconn(conn)
            except Exception: pass

        if old_pw != current_sudo:
            raise HTTPException(401, "old_password 가 일치하지 않습니다.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 검증 실패: {e}")

    # (2) 시스템 jayeondeule 계정 비번 변경
    # sudo -S 와 chpasswd input 을 bash -c + echo 로 분리 (단일 stdin 공유 시 부분 실패)
    try:
        import subprocess, shlex
        cmd = f'echo {shlex.quote(f"jayeondeule:{new_pw}")} | /usr/sbin/chpasswd'
        result = subprocess.run(
            ['sudo', '-S', '-p', '', 'bash', '-c', cmd],
            input=f'{old_pw}\n', text=True,
            timeout=15, capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr or result.stdout or 'unknown'
            raise HTTPException(500, f"시스템 비밀번호 변경 실패: {err[:200]}")
        logger.info("[관리자] 시스템 jayeondeule 비밀번호 변경 완료")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "시스템 비밀번호 변경 timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"시스템 비밀번호 변경 예외: {e}")

    # (3) DB user_m_info.sudo_passwd 모든 관리자 row 업데이트
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패 (시스템 비번은 이미 변경됨 — 수동 DB 갱신 필요)")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_m_info SET sudo_passwd=%s
                    WHERE sudo_passwd IS NOT NULL AND dlte_yn='N'
                """, (new_pw,))
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        logger.info(f"[관리자] DB sudo_passwd {affected}건 업데이트 완료")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 비밀번호 업데이트 실패: {e} (시스템 비번은 이미 변경됨)")

    api_logger.info("[admin/sudo-password] sudo 비밀번호 변경 완료 (시스템+DB 동기화)")

    return {
        "success": True,
        "message": "sudo 비밀번호 변경 완료 (시스템 + DB 동기화). 다음 모델 변경부터 새 비번 사용.",
        "db_updated_rows": affected,
    }


# ════════════════════════════════════════════════════════════════════
# sudo 비밀번호 강제 변경 — old_password 검증 없이 즉시 동기화
# 사용처: Spring Boot UserService 가 사용자 관리 화면에서 admin 비번 변경 시
# 시스템 jayeondeule 비번도 같이 변경하기 위해 호출. 외부 노출 금지 — Spring 만.
# ════════════════════════════════════════════════════════════════════
@app.post("/api/v1/admin/sudo-password/force")
async def force_change_sudo_password(request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    new_pw = (body.get("new_password") or "").strip()
    if not new_pw:
        raise HTTPException(400, "new_password 가 필요합니다.")
    if len(new_pw) < 4:
        raise HTTPException(400, "new_password 는 4자 이상이어야 합니다.")

    # 현 sudo_passwd 조회 (chpasswd 의 sudo -S input 으로 사용)
    current_sudo = None
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sudo_passwd FROM user_m_info
                    WHERE sudo_passwd IS NOT NULL AND dlte_yn='N'
                    ORDER BY auth_lvel DESC LIMIT 1
                """)
                row = cur.fetchone()
                if row and row[0]:
                    current_sudo = row[0]
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 조회 실패: {e}")

    if not current_sudo:
        raise HTTPException(500, "현 sudo_passwd 가 DB 에 없음 — chpasswd 호출 불가")

    # 시스템 jayeondeule 비번 변경
    # sudo -S 의 stdin 비번 처리와 chpasswd input 을 bash -c + echo 로 분리.
    # 한 stdin 으로 둘 다 받으면 chpasswd 가 sudo 비번 줄까지 user:pass 로 해석해 부분 실패.
    try:
        import subprocess, shlex
        cmd = f'echo {shlex.quote(f"jayeondeule:{new_pw}")} | /usr/sbin/chpasswd'
        result = subprocess.run(
            ['sudo', '-S', '-p', '', 'bash', '-c', cmd],
            input=f'{current_sudo}\n', text=True,
            timeout=15, capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr or result.stdout or 'unknown'
            raise HTTPException(500, f"시스템 chpasswd 실패: {err[:200]}")
        logger.info("[관리자/force] 시스템 jayeondeule 비번 변경 완료")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "chpasswd timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"chpasswd 예외: {e}")

    # DB sudo_passwd 갱신
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_m_info SET sudo_passwd=%s
                    WHERE sudo_passwd IS NOT NULL AND dlte_yn='N'
                """, (new_pw,))
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        logger.info(f"[관리자/force] DB sudo_passwd {affected}건 갱신")
    except Exception as e:
        raise HTTPException(500, f"DB 업데이트 실패: {e} (시스템 비번은 이미 변경됨)")

    api_logger.info("[admin/sudo-password/force] 동기화 완료 (Spring → FastAPI)")
    return {"success": True, "db_updated_rows": affected}


# ════════════════════════════════════════════════════════════
# 로또 추천 API
# ════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# 로또 추천 번호 생성 — body.prompt 로 사용자 의도 받아 generate_recommendation.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/lotto/recommend")
async def lotto_recommend(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = body.get("prompt", "")
    from agri_ai_core.src.lotto.lotto_recommender import generate_recommendation
    result = generate_recommendation(prompt)
    return {"success": True, "data": result}


# ────────────────────────────────────────────────────────────────────
# 로또 추천 알고리즘 설명 텍스트 반환.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/lotto/algorithm")
async def lotto_algorithm():
    from agri_ai_core.src.lotto.lotto_recommender import get_algorithm_description
    return {"success": True, "data": get_algorithm_description()}


# ────────────────────────────────────────────────────────────────────
# 미분석 회차 LLM 일괄 분석 — start(기본 501)~end 범위를 백그라운드 실행.
# threading.Thread(daemon=True) 로 즉시 응답, 본 작업은 비동기 진행.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/lotto/analyze-batch")
async def lotto_analyze_batch(request: Request):
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

    # ────────────────────────────────────────────────────────────────
    # 백그라운드 워커 — run_batch 동기 호출, 예외는 로그로만 보고.
    # ────────────────────────────────────────────────────────────────
    def _worker():
        try:
            run_batch(start=start, end=end)
        except Exception as e:
            logger.error(f"[로또분석] 배치 실행 중 오류: {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"success": True, "data": {"message": f"배치 분석 시작 (start={start}, end={end})"}}


# ────────────────────────────────────────────────────────────────────
# 단일 회차 즉시 분석 — body.draw_no 회차를 동기 분석.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/lotto/analyze-draw")
async def lotto_analyze_draw(request: Request):
    body = await request.json()
    draw_no = int(body.get("draw_no"))
    from agri_ai_core.src.lotto.lotto_analyzer import analyze_draw
    ok = analyze_draw(draw_no)
    return {"success": ok, "data": {"draw_no": draw_no}}


