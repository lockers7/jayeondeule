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
# kakao_auth_url             : GET  /api/v1/admin/kakao/auth-url  — 카카오 연동 인증 URL 발급
# kakao_callback             : GET  /api/v1/admin/kakao/callback  — 인증 code → 토큰 저장
# kakao_status               : GET  /api/v1/admin/kakao/status    — 연동 상태 조회
# kakao_test                 : POST /api/v1/admin/kakao/test      — 테스트 메시지 발송
# get_available_models       : GET  /api/v1/admin/models          — Ollama 설치 모델 목록
# change_model               : POST /api/v1/admin/models          — .env MODEL_NAME 변경 (즉시 적용)
# list_control_prompts       : GET  /api/v1/admin/control-prompts        — LLM 제어 프롬프트 전체 조회
# get_control_prompt         : GET  /api/v1/admin/control-prompts/{id}   — 단건 조회
# update_control_prompt      : PUT  /api/v1/admin/control-prompts/{id}   — 단건 갱신
# create_control_prompt      : POST /api/v1/admin/control-prompts        — 신규 등록
# delete_control_prompt      : DELETE /api/v1/admin/control-prompts/{id} — 단건 삭제
# lotto_recommend            : POST /api/v1/lotto/recommend       — 로또 추천 번호 생성
# lotto_algorithm            : GET  /api/v1/lotto/algorithm       — 추천 알고리즘 설명
# lotto_analyze_batch        : POST /api/v1/lotto/analyze-batch   — 미분석 회차 LLM 일괄 분석
# lotto_analyze_draw         : POST /api/v1/lotto/analyze-draw    — 단일 회차 즉시 분석
# ════════════════════════════════════════════════════════════════════
import json
import os
import time
from datetime import datetime          # ⛔ alerts SSE(:453) 가 쓴다 — 지우면 스트림 즉사
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
# 이벤트 루프 바인딩, Agent monitor Job 영속 복원. 종료 시 정리.
# ────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    api_port = os.getenv("API_PORT", "8002")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_key_set = "설정됨" if API_KEY else "미설정(인증 없음)"
    logger.info("[REST API] 시작 (Host=%s, Port=%s, API Key=%s)", api_host, api_port, api_key_set)

    # 애플리케이션 초기화 (DB, ChromaDB, 스케줄러, LLM 등)
    # API 프로세스는 AI 루프 + cron 잡 모두 비활성 —
    #   Scheduler 단독 가동으로 Ollama 큐 동시 호출 경합 차단.
    from agri_ai_core.startup import initialize_app, shutdown_app
    initialize_app(start_ai_loop=False, register_jobs=False)

    # 알림 버스에 이벤트 루프 바인딩 (sync 스레드 → SSE 브리지)
    try:
        import asyncio as _asyncio
        from agri_ai_core.src.ai import alert_bus as _alert_bus
        _alert_bus.bind_event_loop(_asyncio.get_running_loop())
    except Exception as _e:
        logger.warning("[alert_bus] 이벤트 루프 바인딩 실패: %s", _e)

    # Agent 모니터링 Job 영속 복원 — 서비스 재시작 후 active Job 재등록
    try:
        from agri_ai_core.src.ai.tools_agent import restore_active_jobs as _restore_agent_jobs
        _restored = _restore_agent_jobs()
        if _restored:
            logger.info("[Agent] 재시작 후 monitor Job %d건 복원", _restored)
    except Exception as _e:
        logger.warning("[Agent] monitor Job 복원 실패: %s", _e)

    # 시스템 자기지식 자율 초기화 — 비었으면 시드, 있으면 감사(스키마 드리프트 자동 갱신).
    # 백그라운드(임베딩 지연이 기동을 막지 않도록) · best-effort.
    try:
        import threading as _threading
        from agri_ai_core.src.ai.system_knowledge import ensure_system_knowledge as _ensure_sk
        _threading.Thread(target=_ensure_sk, daemon=True).start()
    except Exception as _e:
        logger.warning("[시스템지식] 기동 초기화 스레드 실패: %s", _e)

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
app.include_router(ai_feedback_router)
# AI Agent 관리 — history/pending/trigger/subscriptions/alerts
from agri_ai_core.api.agent_router import agent_router
app.include_router(agent_router)
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
# Proactive 알림 — SSE 스트림 + 최근 알림 조회
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
# 알림 수동 발행 — 운영/디버그용.
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
# Last-Event-ID 헤더 지원 (재연결 시 놓친 이벤트 복원), 각
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

            # 재연결 시 Last-Event-ID 이후 이벤트 즉시 복원
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
# PostgreSQL 커넥션 풀 실시간 상태 (min/max/in_use/idle).
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
    # LLM 대화 단계 로그 — AI/ALGO 와 동일 포맷
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
            tool_calls_detail = result_data.get("tool_calls_detail") or None
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
            tool_calls_detail=tool_calls_detail,  # 도구 호출 감사 로그
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


# ══════════════════════════════════════════════════════════════════
# 주식 자동매매 API — 수치는 PostgreSQL trading_*, 판단·분석·학습은 전용 VectorDB
#   (농장관리와 분리). 프론트 '주식자동매매' 화면이 사용.
# ══════════════════════════════════════════════════════════════════
@app.get("/api/v1/trading/candidates")
async def trading_candidates(scan_date: str = None, status: str = None, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "candidates": ts.list_candidates(scan_date, status)}


@app.get("/api/v1/trading/performance")
async def trading_performance(days: int = 30, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "performance": ts.list_performance(days)}


@app.get("/api/v1/trading/prompt")
async def trading_get_prompt(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "prompt": ts.get_user_prompt()}


@app.post("/api/v1/trading/prompt")
async def trading_set_prompt(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    body = await request.json()
    return ts.set_user_prompt(body.get("prompt", ""))


@app.get("/api/v1/trading/userdata")
async def trading_get_userdata(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "userdata": ts.get_user_data()}


@app.post("/api/v1/trading/userdata")
async def trading_set_userdata(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    body = await request.json()
    return ts.set_user_data(body.get("data", {}))


@app.get("/api/v1/trading/analysis")
async def trading_analysis(query: str = "매매 판단 분석", category: str = None, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    items = ts.list_trading_knowledge(category=category, limit=50) if category else ts.recall_trading_knowledge(query)
    return {"success": True, "analysis": items}


@app.get("/api/v1/trading/learning")
async def trading_learning(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "learning": ts.list_learning()}


@app.get("/api/v1/trading/portfolio")
async def trading_portfolio(scan_date: str = None, status: str = None, _=Depends(verify_api_key)):
    # 선정 후보의 섹터·이벤트유형 집중도(리스크 관점). status 미지정 시 전체.
    from agri_ai_core.src.ai import trading_store as ts
    cands = ts.list_candidates(scan_date, status)
    return {"success": True, "concentration": ts.portfolio_concentration(cands),
            "count": len(cands)}


@app.get("/api/v1/trading/factor-weights")
async def trading_get_factor_weights(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "weights": ts.get_factor_weights(),
            "labels": ts.FACTOR_LABELS}


@app.post("/api/v1/trading/factor-weights")
async def trading_set_factor_weights(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    body = await request.json()
    return ts.set_factor_weights(body.get("weights", {}))


@app.post("/api/v1/trading/learn")
async def trading_learn(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    body = await request.json()
    return ts.save_daily_learning(body.get("summary", ""))


@app.post("/api/v1/trading/run")
async def trading_run(request: Request, _=Depends(verify_api_key)):
    # 로컬 AI Agent(ReAct)로 마감스캔→종목선정→후보저장 실행. 사용자 프롬프트를 지시에 결합.
    import asyncio
    from agri_ai_core.src.ai import trading_store as ts
    from agri_ai_core.src.control.ai_monitor_agent import run_agent
    user_prompt = ts.get_user_prompt()
    learning_ctx = ts.build_learning_context(query="매매 종목 선정 이벤트 판단")   # 자가개선: 과거 학습 주입
    control_ctx = ts.build_control_context()   # Phase2 관리자 컨트롤(전략·제외·리스크) 주입
    trend_ctx = ts.build_trend_context()   # Phase3 최신 매매 방법론 주입(전통 TA 배제)
    task = ("장 마감 후 국내주식 자동매매 스캔이다. 오늘 공시(주요사항보고 등) 이벤트를 scan_stock_events 로 "
            "스캔해 호재 종목 중심으로 내일 매매 후보 3~7종목을 선정하고, 각 종목 매수가·목표가·손절가·"
            "기대수익률·확신도를 산정해 save_trade_candidate 로 저장한 뒤 request_trade_approval 로 승인요청하라. "
            "⛔실제 주문 금지."
            + (f"\n[사용자 전략 프롬프트] {user_prompt}" if user_prompt else "")
            + (f"\n{learning_ctx}" if learning_ctx else "")
            + (f"\n{control_ctx}" if control_ctx else "")
            + (f"\n{trend_ctx}" if trend_ctx else ""))
    try:
        res = await asyncio.to_thread(run_agent, task=task, farm_id=1, trigger_type="user", persist_db=False)
        candidates = ts.list_candidates()
        # 자가개선: 실행 결과를 학습 데이터로 자동 저장 → 다음 실행이 회상해 개선
        await asyncio.to_thread(ts.auto_learn_from_run, candidates, res.get("final"))
        return {"success": bool(res.get("success")), "final": res.get("final") or res.get("reason"),
                "steps": len(res.get("steps", [])), "candidates": candidates,
                "learning_injected": bool(learning_ctx)}
    except Exception as e:
        api_logger.error("[trading/run] %s", e)
        return {"success": False, "message": str(e)}


@app.post("/api/v1/trading/learn-performance")
async def trading_learn_performance(_=Depends(verify_api_key)):
    # 자가개선: 매매 실적을 집계해 인사이트 학습(다음 선정 개선)
    from agri_ai_core.src.ai import trading_store as ts
    return ts.learn_from_performance()


# ── Phase 2: 다양한 관리자 컨트롤 (전략·제외·승인 — AI 주입) ──
@app.get("/api/v1/trading/strategies")
async def trading_strategies(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "strategies": ts.list_strategies(), "active": ts.get_active_strategy()}


@app.post("/api/v1/trading/strategies")
async def trading_save_strategy(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    b = await request.json()
    return ts.save_strategy(b.get("name", ""), b.get("prompt_text", b.get("prompt", "")))


@app.post("/api/v1/trading/strategy/activate")
async def trading_activate_strategy(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    b = await request.json()
    return ts.activate_strategy(b.get("name", ""))


@app.post("/api/v1/trading/candidate/status")
async def trading_candidate_status(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    b = await request.json()
    return ts.set_candidate_status(b.get("scan_date"), b.get("stock_code", ""), b.get("status", "proposed"))


@app.get("/api/v1/trading/exclusions")
async def trading_get_exclusions(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "exclusions": ts.get_exclusions()}


@app.post("/api/v1/trading/exclusions")
async def trading_set_exclusions(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    b = await request.json()
    return ts.set_exclusions(b.get("exclusions", []))


@app.get("/api/v1/trading/control-context")
async def trading_control_context(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "context": ts.build_control_context()}

# ── Phase 3: 최신 매매 방법론(트렌드) — RAG 회상, 전통 TA 배제 ──
@app.get("/api/v1/trading/trends")
async def trading_trends(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai import trading_store as ts
    return {"success": True, "methodology": ts.list_trading_knowledge(category="방법론", limit=50),
            "trend_context": ts.build_trend_context()}


@app.post("/api/v1/trading/seed-trends")
async def trading_seed_trends(request: Request, _=Depends(verify_api_key)):
    from agri_ai_core.src.ai.trading_trend_seed import seed_trading_trends
    try:
        b = await request.json()
    except Exception:
        b = {}
    return seed_trading_trends(force=bool(b.get("force")))

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
# ════════════════════════════════════════════════════════════════════
# 카카오 '나에게 보내기' 알림 연동
# 관리자 1회 인증(auth-url 클릭 → 동의 → callback) 후 Agent/비상 알림 실시간 푸시.
# ════════════════════════════════════════════════════════════════════
@app.get("/api/v1/admin/kakao/auth-url")
async def kakao_auth_url(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai.kakao_notify import build_auth_url
    return build_auth_url()


@app.get("/api/v1/admin/kakao/callback")
async def kakao_callback(code: str = None, error: str = None):
    from fastapi.responses import HTMLResponse
    from agri_ai_core.src.ai.kakao_notify import exchange_code
    if error or not code:
        return HTMLResponse(f"<h3>카카오 인증 실패: {error or 'code 없음'}</h3>", status_code=400)
    r = exchange_code(code)
    if r.get("success"):
        return HTMLResponse("<h3>✅ 카카오 '나에게 보내기' 연동 완료 — 이 창을 닫으셔도 됩니다.</h3>")
    return HTMLResponse(f"<h3>연동 실패: {r.get('error')}</h3>", status_code=500)


@app.get("/api/v1/admin/kakao/status")
async def kakao_status(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai.kakao_notify import get_status
    return get_status()


@app.post("/api/v1/admin/kakao/test")
async def kakao_test(_=Depends(verify_api_key)):
    from agri_ai_core.src.ai.kakao_notify import send_to_me
    from datetime import datetime as _dt
    return send_to_me(f"🌱 자연들에 농장 알림 테스트 — {_dt.now().strftime('%m/%d %H:%M:%S')} 연동 정상")


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
# [프롬프트 자동화] 관리 API — prompt_block / tool_definition 편집
# ════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# prompt_block_m 전체 행 조회 (관리자 편집 화면용).
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/prompt-blocks")
async def list_prompt_blocks(_=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT block_id, name, body_text, placeholders, description,
                           active_yn, updt_dttm
                    FROM prompt_block_m ORDER BY block_id
                """)
                rows = cur.fetchall()
                return {
                    "success": True,
                    "blocks": [
                        {
                            "block_id": r[0], "name": r[1], "body_text": r[2],
                            "placeholders": r[3], "description": r[4],
                            "active_yn": r[5], "updt_dttm": r[6].isoformat() if r[6] else None,
                        }
                        for r in rows
                    ],
                }
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_block_m 단건 갱신 — 부분 필드 업데이트(body_text/active_yn/name/
# placeholders/description). 갱신 후 prompt_registry 캐시 즉시 무효화.
# body: 갱신할 키만 포함 (모두 선택, 최소 1개 필요).
# ────────────────────────────────────────────────────────────────────
@app.put("/api/v1/admin/prompt-blocks/{block_id}")
async def update_prompt_block(block_id: str, request: Request, _=Depends(verify_api_key)):
    import json as _json
    body = await request.json()

    # 갱신 가능 필드 화이트리스트 (None 이 아니면 갱신 대상)
    updatable = {
        "body_text": body.get("body_text"),
        "active_yn": body.get("active_yn"),
        "name": body.get("name"),
        "placeholders": body.get("placeholders"),
        "description": body.get("description"),
    }
    fields = {k: v for k, v in updatable.items() if v is not None}
    if not fields:
        raise HTTPException(400, "갱신할 필드가 하나도 없습니다.")
    if "active_yn" in fields and fields["active_yn"] not in ("Y", "N"):
        raise HTTPException(400, "active_yn 은 'Y' 또는 'N' 이어야 합니다.")

    # placeholders 는 jsonb — dict/list 면 직렬화
    if "placeholders" in fields and not isinstance(fields["placeholders"], str):
        fields["placeholders"] = _json.dumps(fields["placeholders"], ensure_ascii=False)

    set_clause = ", ".join(f"{k}=%s" for k in fields) + ", updt_dttm=NOW()"
    values = list(fields.values()) + [block_id]

    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE prompt_block_m SET {set_clause} WHERE block_id=%s",
                    values,
                )
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if affected == 0:
            raise HTTPException(404, f"block_id='{block_id}' 미존재")
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/prompt-blocks] 갱신: {block_id} 필드={list(fields.keys())}")
        return {"success": True, "block_id": block_id, "updated_fields": list(fields.keys())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"갱신 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_block_m 신규 등록 — Create.
# body: { block_id, name, body_text, placeholders?, description?, active_yn? }
# block_id 중복 시 409. active_yn 기본값 'Y'.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/admin/prompt-blocks")
async def create_prompt_block(request: Request, _=Depends(verify_api_key)):
    import json as _json
    body = await request.json()
    block_id = (body.get("block_id") or "").strip()
    name = (body.get("name") or "").strip()
    body_text = body.get("body_text") or ""
    placeholders = body.get("placeholders")
    description = body.get("description") or ""
    active_yn = body.get("active_yn", "Y")

    if not block_id:
        raise HTTPException(400, "block_id 는 필수입니다.")
    if not name:
        raise HTTPException(400, "name 은 필수입니다.")
    if active_yn not in ("Y", "N"):
        raise HTTPException(400, "active_yn 은 'Y' 또는 'N' 이어야 합니다.")
    if placeholders is None:
        placeholders_json = "{}"
    elif isinstance(placeholders, str):
        placeholders_json = placeholders
    else:
        placeholders_json = _json.dumps(placeholders, ensure_ascii=False)

    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM prompt_block_m WHERE block_id=%s",
                    (block_id,),
                )
                if cur.fetchone():
                    raise HTTPException(409, f"block_id='{block_id}' 이미 존재합니다.")
                cur.execute(
                    "INSERT INTO prompt_block_m "
                    "(block_id, name, body_text, placeholders, description, active_yn) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                    (block_id, name, body_text, placeholders_json, description, active_yn),
                )
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/prompt-blocks] 신규: {block_id} (name='{name}', active={active_yn})")
        return {"success": True, "block_id": block_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"등록 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_block_m 단건 삭제. 미존재 시 404.
# ────────────────────────────────────────────────────────────────────
@app.delete("/api/v1/admin/prompt-blocks/{block_id}")
async def delete_prompt_block(block_id: str, _=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM prompt_block_m WHERE block_id=%s",
                    (block_id,),
                )
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if affected == 0:
            raise HTTPException(404, f"block_id='{block_id}' 미존재")
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/prompt-blocks] 삭제: {block_id}")
        return {"success": True, "block_id": block_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"삭제 실패: {e}")


# ════════════════════════════════════════════════════════════
# ChromaDB prompt_chunk 컬렉션 관리 API (대화 LLM system prompt 영역)
# ════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# prompt_chunk 컬렉션 전체 목록. include 로 documents/metadatas 같이 반환.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/prompt-chunks")
async def list_prompt_chunks(_=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.chroma.operations import get_documents
        r = get_documents(
            "prompt_chunk",
            include=["documents", "metadatas"],
            limit=500,
        )
        if not isinstance(r, dict) or "error" in r:
            raise HTTPException(500, f"ChromaDB 조회 실패: {r}")
        ids = r.get("ids") or []
        docs = r.get("documents") or []
        metas = r.get("metadatas") or []
        chunks = []
        for i, _id in enumerate(ids):
            chunks.append({
                "chunk_id": _id,
                "content": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
            })
        # chunk_id 사전순 정렬 (안정 출력)
        chunks.sort(key=lambda c: c["chunk_id"])
        return {"success": True, "chunks": chunks, "total": len(chunks)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_chunk 단건 상세.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/prompt-chunks/{chunk_id}")
async def get_prompt_chunk(chunk_id: str, _=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.chroma.operations import get_documents
        r = get_documents(
            "prompt_chunk",
            ids=[chunk_id],
            include=["documents", "metadatas"],
        )
        if not isinstance(r, dict) or "error" in r:
            raise HTTPException(500, f"ChromaDB 조회 실패: {r}")
        ids = r.get("ids") or []
        if not ids:
            raise HTTPException(404, f"chunk_id='{chunk_id}' 미존재")
        docs = r.get("documents") or []
        metas = r.get("metadatas") or []
        return {
            "success": True,
            "chunk": {
                "chunk_id": ids[0],
                "content": docs[0] if docs else "",
                "metadata": metas[0] if metas else {},
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_chunk 신규 등록 (의미 검색용 임베딩은 운영 정책상 별도 채움 — 본 API
# 는 zero-embedding 으로 등록. content + metadata 직접 read 가 primary path).
# body: { chunk_id, content, metadata? }
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/admin/prompt-chunks")
async def create_prompt_chunk(request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    chunk_id = (body.get("chunk_id") or "").strip()
    content = body.get("content") or ""
    metadata = body.get("metadata") or {}
    if not chunk_id:
        raise HTTPException(400, "chunk_id 는 필수입니다.")
    if not isinstance(metadata, dict):
        raise HTTPException(400, "metadata 는 객체(JSON dict) 이어야 합니다.")

    try:
        from agri_ai_core.src.chroma.operations import get_documents, add_document
        # 중복 확인
        existing = get_documents(
            "prompt_chunk", ids=[chunk_id], include=["metadatas"]
        )
        if isinstance(existing, dict) and existing.get("ids"):
            raise HTTPException(409, f"chunk_id='{chunk_id}' 이미 존재합니다.")

        metadata.setdefault("chunk_id", chunk_id)
        result = add_document("prompt_chunk", chunk_id, content, metadata)
        if not isinstance(result, dict) or "error" in result:
            raise HTTPException(500, f"등록 실패: {result}")
        api_logger.info(f"[admin/prompt-chunks] 신규: {chunk_id}")
        return {"success": True, "chunk_id": chunk_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"등록 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_chunk 단건 갱신 — upsert 형태 (content/metadata 통째로 교체).
# body: { content?, metadata? } — 부분 갱신은 metadata 도 통째로 교체.
# 본문/메타 모두 변경되도록 기존 doc 을 가져와 병합한 뒤 upsert.
# ────────────────────────────────────────────────────────────────────
@app.put("/api/v1/admin/prompt-chunks/{chunk_id}")
async def update_prompt_chunk(chunk_id: str, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    new_content = body.get("content")
    new_metadata = body.get("metadata")
    if new_content is None and new_metadata is None:
        raise HTTPException(400, "content 또는 metadata 중 하나는 필요합니다.")
    if new_metadata is not None and not isinstance(new_metadata, dict):
        raise HTTPException(400, "metadata 는 객체(JSON dict) 이어야 합니다.")

    try:
        from agri_ai_core.src.chroma.operations import (
            get_documents, delete_document, add_document,
        )
        # 기존 doc 가져오기 (없으면 404)
        cur = get_documents(
            "prompt_chunk", ids=[chunk_id],
            include=["documents", "metadatas"],
        )
        if not isinstance(cur, dict) or not cur.get("ids"):
            raise HTTPException(404, f"chunk_id='{chunk_id}' 미존재")

        cur_docs = cur.get("documents") or []
        cur_metas = cur.get("metadatas") or []
        merged_content = new_content if new_content is not None else (cur_docs[0] if cur_docs else "")
        merged_meta = (cur_metas[0] if cur_metas else {}).copy()
        if new_metadata is not None:
            merged_meta = new_metadata  # 통째로 교체
        merged_meta["chunk_id"] = chunk_id  # 식별자 보존

        # ChromaDB 는 update 단일 호출이 안정적이지 않아 delete + add 패턴 사용
        del_r = delete_document("prompt_chunk", [chunk_id])
        if isinstance(del_r, dict) and "error" in del_r:
            raise HTTPException(500, f"기존 삭제 실패: {del_r}")
        add_r = add_document("prompt_chunk", chunk_id, merged_content, merged_meta)
        if not isinstance(add_r, dict) or "error" in add_r:
            raise HTTPException(500, f"재등록 실패: {add_r}")

        api_logger.info(f"[admin/prompt-chunks] 갱신: {chunk_id}")
        return {"success": True, "chunk_id": chunk_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"갱신 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# prompt_chunk 단건 삭제. 미존재 시 404.
# ────────────────────────────────────────────────────────────────────
@app.delete("/api/v1/admin/prompt-chunks/{chunk_id}")
async def delete_prompt_chunk(chunk_id: str, _=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.chroma.operations import get_documents, delete_document
        cur = get_documents("prompt_chunk", ids=[chunk_id], include=["metadatas"])
        if not isinstance(cur, dict) or not cur.get("ids"):
            raise HTTPException(404, f"chunk_id='{chunk_id}' 미존재")
        r = delete_document("prompt_chunk", [chunk_id])
        if isinstance(r, dict) and "error" in r:
            raise HTTPException(500, f"삭제 실패: {r}")
        api_logger.info(f"[admin/prompt-chunks] 삭제: {chunk_id}")
        return {"success": True, "chunk_id": chunk_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"삭제 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# tool_definition_m 전체 행 조회.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/tool-definitions")
async def list_tool_definitions(_=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tool_id, schema_json, description, category, priority,
                           active_yn, updt_dttm
                    FROM tool_definition_m ORDER BY priority, tool_id
                """)
                rows = cur.fetchall()
                return {
                    "success": True,
                    "tools": [
                        {
                            "tool_id": r[0], "schema_json": r[1], "description": r[2],
                            "category": r[3], "priority": r[4],
                            "active_yn": r[5], "updt_dttm": r[6].isoformat() if r[6] else None,
                        }
                        for r in rows
                    ],
                }
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# tool_definition_m active_yn 토글 — body: { "active_yn": "Y|N" }
# ────────────────────────────────────────────────────────────────────
@app.patch("/api/v1/admin/tool-definitions/{tool_id}")
async def toggle_tool_active(tool_id: str, request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    new_active = body.get("active_yn")
    if new_active not in ("Y", "N"):
        raise HTTPException(400, "active_yn 은 'Y' 또는 'N' 이어야 합니다.")
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tool_definition_m SET active_yn=%s, updt_dttm=NOW() WHERE tool_id=%s",
                    (new_active, tool_id),
                )
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if affected == 0:
            raise HTTPException(404, f"tool_id='{tool_id}' 미존재")
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/tool-definitions] 토글: {tool_id} → active_yn={new_active}")
        return {"success": True, "tool_id": tool_id, "active_yn": new_active}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"갱신 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# [프롬프트 자동화] 룰 후보 조회 — 최근 N일 ai_decision_log
# 정상 결정(action='change') 빈번 패턴을 사용자 학습 가능한 룰 텍스트로
# 합성하여 반환. 농장주가 검토 후 승인 API 로 ChromaDB 등록.
# query: farm_id (필수), house_id, days(=7), min_freq(=10), top_k(=20)
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/rule-candidates")
async def list_rule_candidates(
    farm_id: int,
    house_id: Optional[int] = None,
    days: int = 7,
    min_freq: int = 10,
    top_k: int = 20,
    _=Depends(verify_api_key),
):
    try:
        from agri_ai_core.src.control.ai_self_evolve import (
            analyze_decision_patterns, format_candidate_rule,
        )
        patterns = analyze_decision_patterns(
            farm_id=farm_id, house_id=house_id, days=days,
            min_freq=min_freq, top_k=top_k,
        )
        candidates = [
            {**format_candidate_rule(p), 'pattern': p}
            for p in patterns
        ]
        return {"success": True, "count": len(candidates), "candidates": candidates}
    except Exception as e:
        raise HTTPException(500, f"룰 후보 조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# [프롬프트 자동화] 룰 후보 승인 — ChromaDB domain_rule 등록.
# body: { title, content, category(선택), rule_id(선택),
#         farm_id(선택), house_id(선택) }
# 등록 후 prompt_registry 캐시 무효화 → 다음 LLM 호출부터 즉시 반영.
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/admin/rule-candidates/approve")
async def approve_rule_candidate(request: Request, _=Depends(verify_api_key)):
    body = await request.json()
    title = body.get("title")
    content = body.get("content")
    if not (title and content):
        raise HTTPException(400, "title 과 content 는 필수입니다.")
    category = body.get("category") or '운영노하우'
    rule_id = body.get("rule_id")
    farm_id = body.get("farm_id")
    house_id = body.get("house_id")

    try:
        from agri_ai_core.src.control.ai_self_evolve import register_approved_rule
        result = register_approved_rule(
            title=title, content=content, category=category,
            rule_id=rule_id, farm_id=farm_id, house_id=house_id,
            source='admin_approve',
        )
        if not result.get('success'):
            raise HTTPException(500, f"룰 등록 실패: {result.get('error')}")
        api_logger.info(f"[admin/rule-candidates] 승인: rule_id={result['rule_id']}")
        return {"success": True, "rule_id": result['rule_id']}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"룰 승인 처리 실패: {e}")


# ════════════════════════════════════════════════════════════
# LLM 제어 프롬프트 관리 API — control_prompt_m CRUD
# ════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
# control_prompt_m 전체 행 조회 (관리자 편집 화면용).
# category / growth_stage 쿼리 파라미터로 필터 가능.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/control-prompts")
async def list_control_prompts(
    category: Optional[str] = None,
    growth_stage: Optional[str] = None,
    _=Depends(verify_api_key),
):
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            conditions = []
            vals = []
            if category:
                conditions.append("category = %s")
                vals.append(category)
            if growth_stage:
                conditions.append("growth_stage = %s")
                vals.append(growth_stage)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT block_id, section_key, growth_stage, sort_order,
                               category, name, body_text, placeholders,
                               active_yn, description, updt_dttm
                        FROM control_prompt_m {where}
                        ORDER BY category, sort_order, block_id""",
                    vals,
                )
                rows = cur.fetchall()
                return {
                    "success": True,
                    "prompts": [
                        {
                            "block_id": r[0], "section_key": r[1],
                            "growth_stage": r[2], "sort_order": r[3],
                            "category": r[4], "name": r[5],
                            "body_text": r[6], "placeholders": r[7],
                            "active_yn": r[8], "description": r[9],
                            "updt_dttm": r[10].isoformat() if r[10] else None,
                        }
                        for r in rows
                    ],
                }
        finally:
            try: db._putconn(conn)
            except Exception: pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# control_prompt_m 단건 조회.
# ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/control-prompts/{block_id}")
async def get_control_prompt(block_id: str, _=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT block_id, section_key, growth_stage, sort_order,
                              category, name, body_text, placeholders,
                              active_yn, description, updt_dttm
                       FROM control_prompt_m WHERE block_id=%s""",
                    (block_id,),
                )
                r = cur.fetchone()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if not r:
            raise HTTPException(404, f"block_id='{block_id}' 미존재")
        return {
            "success": True,
            "prompt": {
                "block_id": r[0], "section_key": r[1],
                "growth_stage": r[2], "sort_order": r[3],
                "category": r[4], "name": r[5],
                "body_text": r[6], "placeholders": r[7],
                "active_yn": r[8], "description": r[9],
                "updt_dttm": r[10].isoformat() if r[10] else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# control_prompt_m 단건 갱신 — 부분 필드 업데이트.
# 갱신 후 prompt_registry _CTRL_BLOCK_CACHE 즉시 무효화.
# ────────────────────────────────────────────────────────────────────
@app.put("/api/v1/admin/control-prompts/{block_id}")
async def update_control_prompt(block_id: str, request: Request, _=Depends(verify_api_key)):
    import json as _json
    body = await request.json()

    updatable = {
        "body_text":    body.get("body_text"),
        "name":         body.get("name"),
        "section_key":  body.get("section_key"),
        "growth_stage": body.get("growth_stage"),
        "sort_order":   body.get("sort_order"),
        "category":     body.get("category"),
        "placeholders": body.get("placeholders"),
        "description":  body.get("description"),
        "active_yn":    body.get("active_yn"),
    }
    fields = {k: v for k, v in updatable.items() if v is not None}
    if not fields:
        raise HTTPException(400, "갱신할 필드가 하나도 없습니다.")
    if "active_yn" in fields and fields["active_yn"] not in ("Y", "N"):
        raise HTTPException(400, "active_yn 은 'Y' 또는 'N' 이어야 합니다.")
    if "placeholders" in fields and not isinstance(fields["placeholders"], str):
        fields["placeholders"] = _json.dumps(fields["placeholders"], ensure_ascii=False)

    set_clause = ", ".join(f"{k}=%s" for k in fields) + ", updt_dttm=NOW()"
    values = list(fields.values()) + [block_id]

    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE control_prompt_m SET {set_clause} WHERE block_id=%s",
                    values,
                )
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if affected == 0:
            raise HTTPException(404, f"block_id='{block_id}' 미존재")
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/control-prompts] 갱신: {block_id} 필드={list(fields.keys())}")
        return {"success": True, "block_id": block_id, "updated_fields": list(fields.keys())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"갱신 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# control_prompt_m 신규 등록.
# body: { block_id, section_key, category, name, body_text,
#         growth_stage?, sort_order?, placeholders?, description?, active_yn? }
# ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/admin/control-prompts")
async def create_control_prompt(request: Request, _=Depends(verify_api_key)):
    import json as _json
    body = await request.json()
    block_id    = (body.get("block_id") or "").strip()
    section_key = (body.get("section_key") or "").strip()
    category    = (body.get("category") or "").strip()
    name        = (body.get("name") or "").strip()
    body_text   = body.get("body_text") or ""
    growth_stage  = body.get("growth_stage")
    sort_order    = int(body.get("sort_order", 0))
    placeholders  = body.get("placeholders")
    description   = body.get("description") or ""
    active_yn     = body.get("active_yn", "Y")

    for field, val in [("block_id", block_id), ("section_key", section_key),
                       ("category", category), ("name", name)]:
        if not val:
            raise HTTPException(400, f"{field} 는 필수입니다.")
    if active_yn not in ("Y", "N"):
        raise HTTPException(400, "active_yn 은 'Y' 또는 'N' 이어야 합니다.")
    placeholders_json = (
        placeholders if isinstance(placeholders, str)
        else _json.dumps(placeholders or {}, ensure_ascii=False)
    )

    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM control_prompt_m WHERE block_id=%s", (block_id,))
                if cur.fetchone():
                    raise HTTPException(409, f"block_id='{block_id}' 이미 존재합니다.")
                cur.execute(
                    """INSERT INTO control_prompt_m
                       (block_id, section_key, growth_stage, sort_order,
                        category, name, body_text, placeholders, description, active_yn)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)""",
                    (block_id, section_key, growth_stage, sort_order,
                     category, name, body_text, placeholders_json, description, active_yn),
                )
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/control-prompts] 신규: {block_id}")
        return {"success": True, "block_id": block_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"등록 실패: {e}")


# ────────────────────────────────────────────────────────────────────
# control_prompt_m 단건 삭제.
# ────────────────────────────────────────────────────────────────────
@app.delete("/api/v1/admin/control-prompts/{block_id}")
async def delete_control_prompt(block_id: str, _=Depends(verify_api_key)):
    try:
        from agri_ai_core.src.postgresql.connection import db
        conn = db._getconn()
        if conn is None:
            raise HTTPException(500, "DB 연결 실패")
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM control_prompt_m WHERE block_id=%s", (block_id,))
                affected = cur.rowcount
            conn.commit()
        finally:
            try: db._putconn(conn)
            except Exception: pass
        if affected == 0:
            raise HTTPException(404, f"block_id='{block_id}' 미존재")
        try:
            from agri_ai_core.src.prompt_registry import clear_cache
            clear_cache()
        except Exception:
            pass
        api_logger.info(f"[admin/control-prompts] 삭제: {block_id}")
        return {"success": True, "block_id": block_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"삭제 실패: {e}")


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


