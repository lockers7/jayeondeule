#!/usr/bin/env python3
"""자연들에 스마트팜 시스템 (agri_ai_core) 파일 목록 PDF 생성"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from datetime import date

# ── 폰트 등록 ──
FONT_DIR = "/workspace/jayeondeule/docs"
pdfmetrics.registerFont(TTFont("NanumGothic", f"{FONT_DIR}/NanumGothic-Regular.ttf"))
pdfmetrics.registerFont(TTFont("NanumGothicBold", f"{FONT_DIR}/NanumGothic-Bold.ttf"))

# ── 색상 ──
HEADER_BG = colors.HexColor("#4A4A4A")
HEADER_FG = colors.white
ROW_ALT = colors.HexColor("#F5F5F5")
BORDER_COLOR = colors.HexColor("#CCCCCC")

# ── 스타일 ──
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="Title_KR", fontName="NanumGothicBold", fontSize=16,
                          alignment=1, spaceAfter=4))
styles.add(ParagraphStyle(name="Sub_KR", fontName="NanumGothic", fontSize=9,
                          alignment=1, spaceAfter=12, textColor=colors.HexColor("#555555")))
styles.add(ParagraphStyle(name="Section_KR", fontName="NanumGothicBold", fontSize=13,
                          spaceBefore=16, spaceAfter=8))
styles.add(ParagraphStyle(name="Cell", fontName="NanumGothic", fontSize=7.5, leading=10))
styles.add(ParagraphStyle(name="CellBold", fontName="NanumGothicBold", fontSize=7.5, leading=10))
styles.add(ParagraphStyle(name="CellCenter", fontName="NanumGothic", fontSize=7.5,
                          leading=10, alignment=1))

TODAY = date.today().strftime("%Y-%m-%d")


def P(text, style="Cell"):
    return Paragraph(str(text), styles[style])


def PC(text):
    return Paragraph(str(text), styles["CellCenter"])


# ════════════════════════════════════════
# 1) 파일 목록 데이터
# ════════════════════════════════════════
FILE_ROWS = [
    # (순번, 업무구분, 디렉토리, 파일명, 파일기능설명, 비고)
    (1,  "시작", "/", "scheduler.py", "스케줄러 프로세스 진입점", "최초실행 (PID관리)"),
    (2,  "시작", "/", "startup.py", "앱 초기화/종료 (Ollama·ChromaDB·PG 연결)", "initialize_app()"),
    (3,  "시작", "/", "__init__.py", "패키지 공통 export (settings, logger, db)", "v1.0.0"),
    (4,  "설정", "config/", "settings.py", "환경변수 기반 앱 설정 로드 (싱글톤)", ".env 연동"),
    (5,  "설정", "config/", "constants.py", "전역 상수·임계값·스케줄링 주기 정의", ""),
    (6,  "설정", "config/", "mappers.py", "릴레이·센서 필드 매핑 딕셔너리", "재배사별 매핑"),
    (7,  "로그", "/", "logs.py", "통합 로깅 (일별 로테이션·크기 관리)", "모듈별 로거 생성"),
    (8,  "DB", "src/postgresql/", "connection.py", "PostgreSQL 연결풀 싱글톤 관리", "psycopg2"),
    (9,  "DB", "src/postgresql/", "queries.py", "SQL 쿼리 정의 (CREATE·SELECT·INSERT)", ""),
    (10, "DB", "src/postgresql/", "reader.py", "DB 데이터 조회 (센서·릴레이·생육·설정)", ""),
    (11, "벡터DB", "src/chroma/", "config.py", "ChromaDB 호스트·포트·컬렉션명 설정", "port:8000"),
    (12, "벡터DB", "src/chroma/", "client.py", "ChromaDB REST API 통신·컬렉션 자동생성", "heartbeat 체크"),
    (13, "벡터DB", "src/chroma/", "collections.py", "컬렉션별 접근 함수 (farm·doc·conv·web)", "4개 컬렉션"),
    (14, "벡터DB", "src/chroma/", "operations.py", "벡터 CRUD (임베딩·검색·업서트·삭제)", ""),
    (15, "벡터DB", "src/chroma/", "utils.py", "메타데이터 정제·임베딩 차원 관리", ""),
    (16, "벡터DB", "src/chroma/", "loader.py", "대량 데이터 벡터DB 일괄 로드", "배치 로딩"),
    (17, "스케줄", "src/control/", "task_scheduler.py", "APScheduler 기반 백그라운드 작업 관리", "8개 기본작업 등록"),
    (18, "수동환경제어", "src/control/", "control_common.py", "제어 공통상수·임계값·핀매핑·포맷팅", "64케이스 기초"),
    (19, "수동환경제어", "src/control/", "manual_control.py", "센서 기반 자동환경제어 (온도·습도·CO2)", "10초 주기"),
    (20, "AI환경제어", "src/control/", "ai_control.py", "LLM 기반 종합분석 환경제어·비상모니터링", "5분 주기"),
    (21, "릴레이관리", "src/control/", "relay_manager.py", "릴레이 값 설정·상태 조회·상태 로깅", "DB 릴레이 갱신"),
    (22, "스케줄제어", "src/control/", "schedule_control.py", "조명·관수 시간대별 자동 스케줄 제어", "5분 주기"),
    (23, "생육RAG", "src/ai/learning/", "growth_rag_processor.py", "생육 데이터 기반 인과관계 RAG 문서 생성", "0시·12시 실행"),
    (24, "학습", "src/ai/learning/", "data_analyzer.py", "센서 데이터 패턴 분석", ""),
    (25, "학습", "src/ai/learning/", "model_trainer.py", "AI 모델 재학습 처리", ""),
    (26, "AI/LLM", "src/ai/", "llm_client.py", "Ollama LLM 통신·Tool Use·응답필터링", "핵심 모듈"),
    (27, "AI/LLM", "src/ai/", "query_handler_simple.py", "Tool Use 방식 질의처리 (동기·SSE스트림)", "핵심 모듈"),
    (28, "AI/LLM", "src/ai/", "tools_definition.py", "LLM용 도구(함수) 스키마 정의", "4개 도구 정의"),
    (29, "AI/LLM", "src/ai/", "tools_executor.py", "LLM 요청 도구 실행 (웹검색·DB·VectorDB)", "핵심 모듈"),
    (30, "MCP통신", "src/ai/", "mcp_client.py", "MCP서버 통신 (web-search·postgres·fetch)", "JSON-RPC"),
    (31, "대화관리", "src/ai/", "conversation_store.py", "PostgreSQL 기반 멀티턴 대화 저장·조회", "인메모리 폴백"),
    (32, "통계", "src/ai/", "stats_collector.py", "LLM 응답시간·도구사용·검색성공률 수집", "Thread-safe"),
    (33, "RAG", "src/ai/rag/", "embedder.py", "텍스트→벡터 임베딩 변환 (bge-m3, 1024dim)", "동적 타임아웃"),
    (34, "RAG", "src/ai/rag/", "chunker.py", "문서 의미단위 청킹 (파일명 프리픽스 포함)", "1000자·200겹침"),
    (35, "RAG", "src/ai/rag/", "document_processor.py", "문서 처리 파이프라인 및 벡터DB 저장", "문서유형·작물 자동감지"),
    (36, "RAG", "src/ai/rag/", "reranker.py", "LLM 기반 검색결과 재정렬 (관련성 점수)", "거리 기반 폴백"),
    (37, "RAG", "src/ai/rag/", "document_enricher.py", "LLM 기반 문서 요약·QA 생성·메타강화", "백그라운드 스레드"),
    (38, "파일처리", "src/ai/", "file_processor.py", "업로드 파일 읽기 (CSV·Excel·PDF·텍스트)", "100MB 제한"),
    (39, "API", "api/", "__main__.py", "Uvicorn으로 FastAPI 서버 실행 진입점", "port:8002"),
    (40, "API", "api/", "app.py", "REST API 라우팅·인증·미들웨어·엔드포인트", "핵심 모듈"),
    (41, "API", "api/", "models.py", "Pydantic 요청/응답 데이터 모델 정의", ""),
    (42, "음성처리", "api/", "voice_router.py", "음성 입출력 엔드포인트 (STT·TTS)", "FastAPI Router"),
    (43, "음성처리", "src/voice/", "stt_engine.py", "음성→텍스트 변환 (faster-whisper)", "CPU int8 양자화"),
    (44, "음성처리", "src/voice/", "tts_engine.py", "텍스트→음성 변환", ""),
    (45, "유틸리티", "src/utils/", "conversion.py", "단위·데이터타입 변환 (safe_float 등)", ""),
    (46, "유틸리티", "src/utils/", "validators.py", "센서값 정제·부울 파싱·유효성 검사", ""),
    (47, "유틸리티", "src/utils/", "date_utils.py", "날짜·시간 처리 유틸리티", ""),
]

# ════════════════════════════════════════
# 2) 스케줄러 작업 목록
# ════════════════════════════════════════
SCHEDULER_ROWS = [
    (1, "수동 환경제어", "10초", "control_all_manual()"),
    (2, "AI 환경제어", "5분", "control_all_ai()"),
    (3, "생육 RAG 처리 (낮)", "매일 12:00", "run_growth_rag()"),
    (4, "생육 RAG 처리 (자정)", "매일 00:05", "run_growth_rag(is_midnight=True)"),
    (5, "조명·관수 스케줄 제어", "5분", "control_all_schedules()"),
    (6, "통계 수집", "10분", "StatsCollector.collect()"),
    (7, "로그 정리", "매일 00:00", "cleanup_all_logs()"),
    (8, "오래된 청크 삭제", "매일 03:00", "chunk_cleanup_job()"),
]

# ════════════════════════════════════════
# 3) API 엔드포인트 목록
# ════════════════════════════════════════
API_ROWS = [
    (1, "GET", "/health", "서버 상태 확인"),
    (2, "GET", "/api/v1/stats", "시스템 통계 조회"),
    (3, "POST", "/api/v1/query", "LLM 질의 (동기)"),
    (4, "POST", "/api/v1/query/stream", "LLM 질의 (SSE 스트리밍)"),
    (5, "POST", "/api/v1/rag/perform", "RAG 검색 수행"),
    (6, "POST", "/api/v1/rag/save", "RAG 데이터 저장"),
    (7, "POST", "/api/v1/voice/stt", "음성→텍스트 변환"),
    (8, "POST", "/api/v1/voice/tts", "텍스트→음성 변환"),
]


# ════════════════════════════════════════
# 테이블 공통 스타일
# ════════════════════════════════════════
def base_table_style(n_rows, col_count):
    """공통 테이블 스타일 생성"""
    cmds = [
        # 헤더
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "NanumGothicBold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        # 본문
        ("FONTNAME", (0, 1), (-1, -1), "NanumGothic"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
        # 그리드
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#333333")),
    ]
    # 줄무늬
    for i in range(1, n_rows + 1):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    return TableStyle(cmds)


# ════════════════════════════════════════
# 페이지 번호
# ════════════════════════════════════════
def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("NanumGothic", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    page_num = canvas.getPageNumber()
    canvas.drawCentredString(doc.pagesize[0] / 2, 12 * mm, f"- {page_num} -")
    canvas.restoreState()


# ════════════════════════════════════════
# PDF 생성
# ════════════════════════════════════════
def build_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
    )
    elements = []

    # ── 제목 ──
    elements.append(Paragraph("자연들에 스마트팜 시스템 (agri_ai_core) 파일 목록", styles["Title_KR"]))
    elements.append(Paragraph(
        f"기준경로: agri_ai_core/ | 총 파일 수: {len(FILE_ROWS)}개 | 작성일: {TODAY}",
        styles["Sub_KR"],
    ))

    # ── 파일 목록 테이블 (페이지 1-2) ──
    col_widths = [28, 62, 82, 135, 310, 110]  # 합계 ~727  (landscape A4 ≈ 267mm usable)
    header = [PC("순번"), PC("업무구분"), PC("디렉토리"), PC("파일명"), PC("파일기능설명"), PC("비고")]
    rows = [header]
    for r in FILE_ROWS:
        rows.append([PC(r[0]), PC(r[1]), P(r[2]), P(r[3], "CellBold"), P(r[4]), P(r[5])])

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(base_table_style(len(FILE_ROWS), 6))
    elements.append(t)

    # ── 페이지 3: 스케줄러 + API ──
    elements.append(PageBreak())

    # 스케줄러 테이블
    elements.append(Paragraph("스케줄러 등록 작업 목록", styles["Section_KR"]))
    s_header = [PC("순번"), PC("작업명"), PC("주기"), PC("실행 함수")]
    s_rows = [s_header]
    for r in SCHEDULER_ROWS:
        s_rows.append([PC(r[0]), P(r[1]), PC(r[2]), P(r[3])])
    s_widths = [40, 200, 100, 280]
    st = Table(s_rows, colWidths=s_widths)
    st.setStyle(base_table_style(len(SCHEDULER_ROWS), 4))
    elements.append(st)

    elements.append(Spacer(1, 20))

    # API 엔드포인트 테이블
    elements.append(Paragraph("API 엔드포인트 목록", styles["Section_KR"]))
    a_header = [PC("순번"), PC("메서드"), PC("경로"), PC("기능")]
    a_rows = [a_header]
    for r in API_ROWS:
        a_rows.append([PC(r[0]), PC(r[1]), P(r[2]), P(r[3])])
    a_widths = [40, 60, 240, 280]
    at = Table(a_rows, colWidths=a_widths)
    at.setStyle(base_table_style(len(API_ROWS), 4))
    elements.append(at)

    # ── 빌드 ──
    doc.build(elements, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"PDF 생성 완료: {output_path}")
    print(f"  파일 수: {len(FILE_ROWS)}개")
    print(f"  스케줄러 작업: {len(SCHEDULER_ROWS)}개")
    print(f"  API 엔드포인트: {len(API_ROWS)}개")


if __name__ == "__main__":
    build_pdf("/workspace/jayeondeule/docs/시스템파일목록.pdf")
