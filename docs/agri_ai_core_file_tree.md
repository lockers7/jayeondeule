# agri_ai_core 소스코드 파일 트리

**총 71개 실행 Python 파일** (`__init__.py` / `__main__.py` 제외) │ 2026-04-17

---

## 계층 구조 (Top-Down, 상호/역참조 금지)

```
L0  엔트리포인트        scheduler.py · api/*
L1  공용 초기화         startup.py
L2  AI 디스패처         src/ai/query_handler_simple.py
L3  3단계 파이프라인    src/ai/pipeline/*
L4  AI facade · 기능    src/ai/llm_client.py · src/ai/learning/* · src/ai/rag/*
L5  AI 도구 · 독립기능  src/ai/{embedder,reranker,tools_*,mcp_*,llm_transport,...}
                        src/lotto/* · src/opinet/* · src/voice/*
L6  데이터 · 하드웨어   src/chroma/* · src/postgresql/* · src/control/*
L7  기반 유틸           src/utils/* · config/* · logs.py
```

**호출 방향 규칙**
- 상위 → 하위: 허용
- 동급 ↔ 동급: 허용
- 하위 → 상위: **금지** (모듈레벨 · 함수내 lazy 모두)

---

## 검증 결과 (AST 기반 전수 분석)

| 항목 | 결과 |
|------|------|
| 모듈레벨 순환 참조 | **0건** ✓ |
| lazy import 포함 순환 참조 | **0건** ✓ |
| 모듈레벨 역호출 (하위→상위) | **0건** ✓ |
| lazy import 역호출 | **0건** ✓ |

하위 계층이 상위 서비스를 필요로 하는 경우는 **의존성 주입(DI)** 으로 해결:
- `src/postgresql/connection.py`: `set_mcp_query_fn()` 훅 → `startup.py` 주입
- `src/chroma/operations.py`: `set_embed_fn()` 훅 → `startup.py` 주입
- `src/control/task_scheduler.py`: `setup_default_jobs(opinet_collect_func=, lotto_collect_func=)` 인자 → `startup.py` 주입

---

## 파일 트리

```
agri_ai_core/
├── logs.py                         — 공용 로거 생성 + 일별 로테이션 + 오래된 로그 자동 정리
├── scheduler.py                    — 백그라운드 서비스 러너 (엔트리포인트)
├── startup.py                      — 애플리케이션 초기화 + 의존성 훅 주입
├──  api/
│   ├── app.py                      — FastAPI 앱: REST API 서버, LLM 질의, RAG 엔드포인트
│   ├── models.py                   — API 요청/응답 Pydantic 모델 정의
│   ├── rpi_router.py               — 라즈베리파이 관리 API: SSH 재시작 및 센서 상태 모니터링
│   └── voice_router.py             — 음성 API 라우터: STT/TTS REST API 엔드포인트
├──  config/
│   ├── constants.py                — 시스템 전역 상수, 임계값, 스케줄링, Ollama/모델 헬퍼
│   ├── mappers.py                  — 센서/릴레이 한글-영문 필드 매핑 및 house_id별 매핑 반환
│   └── settings.py                 — 환경변수 기반 설정 로드 (dataclass + lru_cache)
└──  src/
    ├──  ai/
    │   ├── conversation_store.py   — 대화 히스토리 저장소 (요약·벡터 저장)
    │   ├── embedder.py             — 텍스트 임베딩 생성: Ollama 기반 벡터 변환 및 캐시 관리
    │   ├── farm_cache.py           — 농장 이름 캐시 — farm_id → farm_name 매핑 (프로세스 수명)
    │   ├── file_processor.py       — 업로드 파일(CSV/Excel/PDF/텍스트)을 LLM 입력 형식으로 변환
    │   ├── llm_client.py           — LLM 클라이언트 facade — Tool Use 응답 생성
    │   ├── llm_message_utils.py    — LLM 메시지/응답 pure helper (직렬화, 추출, 정규화)
    │   ├── llm_response.py         — LLM 응답 후처리: 도구 결과 정제, 마크다운 표 정렬
    │   ├── llm_response_processing.py — 질문 분류, 응답 유형 판정, 재시도 검증, 대화 컨텍스트 구성
    │   ├── llm_transport.py        — Ollama 전송 계층 — 모델 선택, GPU 비율 산출, 3가지 전송 방식
    │   ├── llm_warmup.py           — LLM 워밍업 — 백그라운드에서 첫 호출로 모델 VRAM 적재
    │   ├── mcp_client.py           — MCP(Model Context Protocol) 클라이언트 — MCP 서버 공통 호출
    │   ├── mcp_utils.py            — MCP 순수 유틸리티 — 상태/통신 없는 pure helper
    │   ├── opinet_tools.py         — Opinet 유가정보 도구 — 전국/시도/시군구 평균/최저가 조회
    │   ├── query_handler_simple.py — LLM 쿼리 핸들러 — 질문 처리 및 SSE 스트리밍 (디스패처)
    │   ├── query_utils.py          — 질의 처리 공용 pure helper
    │   ├── reranker.py             — LLM 기반 Reranker: 벡터 검색 후보를 관련성 점수로 재정렬
    │   ├── stats_collector.py      — 질의 통계 수집기 — 응답시간, 도구 호출, 검색 성공률
    │   ├── tools_definition.py     — LLM Tool Use 도구 정의
    │   ├── tools_executor.py       — LLM Tool 실행기 — 검색/DB/릴레이 도구 실행
    │   ├── tools_search.py         — 웹 검색 및 URL 본문 가져오기
    │   ├── tools_utils.py          — 도구 실행 공용 pure helper (파싱·변환·AI 충돌 비교)
    │   ├── utils.py                — AI 공통 유틸리티 — Think-tag 제거, 한국어 감지
    │   ├──  learning/
    │   │   ├── data_analyzer.py    — 센서/릴레이 이력 통계 분석 + 최적 환경 조건 도출
    │   │   ├── growth_rag_processor.py — 생육 기반 인과 관계 RAG: 환경 통계와 생육 데이터 저장
    │   │   └── model_trainer.py    — 모델 학습 관리: 농장 데이터 분석 및 ChromaDB 저장
    │   ├──  pipeline/
    │   │   ├── answer_generator.py — 3단계 답변 작성: 수집 데이터 기반 답변 생성 및 출처 선별
    │   │   ├── data_collector.py   — 2단계 데이터 수집: 도구 실행 및 LLM 충분성 판단
    │   │   ├── prompts.py          — 3단계 파이프라인 전용 프롬프트 (분석→검증→답변)
    │   │   ├── question_analyzer.py— 1단계 질문유형 분석: 수집 계획 생성
    │   │   └── validators.py       — 2단계 LLM 기반 수집 데이터 충분성 판단
    │   └──  rag/
    │       ├── chunker.py          — 텍스트 청킹: 문서를 의미 단위 청크로 분할 저장
    │       ├── constants.py        — RAG 공용 상수 (DOC_TYPE_LABELS 단일 원천)
    │       ├── document_enricher.py— LLM 문서 요약 및 QA 쌍 생성
    │       └── document_processor.py — 문서 처리 파이프라인: 파싱·유형감지·청크저장·enrichment
    ├──  chroma/
    │   ├── client.py               — ChromaDB 클라이언트 계층 (REST v2, 컬렉션 ID 캐시)
    │   ├── collections.py          — ChromaDB 컬렉션 이름 반환 함수들
    │   ├── config.py               — ChromaDB 연결 설정 및 상수 정의
    │   ├── loader.py               — 미학습 데이터 조회 및 학습 상태 관리
    │   ├── operations.py           — 문서 저장/조회/삭제/업서트 + 벡터 유사도 검색 (embed_fn DI)
    │   └── utils.py                — 메타데이터 변환, JSON 직렬화, 문서 ID 생성
    ├──  control/
    │   ├── ai_control.py           — AI 릴레이 제어 모듈 (센서 트렌드 + LLM 판단)
    │   ├── control_common.py       — 제어 모듈 공통 상수, 매핑, 유틸리티
    │   ├── manual_control.py       — 환경제어 모듈 (수동 모드)
    │   ├── relay_manager.py        — 릴레이 제어 관리자
    │   ├── schedule_control.py     — 릴레이 스케줄 제어
    │   └── task_scheduler.py       — APScheduler 기반 작업 스케줄러 (job 함수 DI)
    ├──  lotto/
    │   ├── lotto_analyzer.py       — 로또 추천 vs 당첨 비교 분석기 (LLM 전용)
    │   ├── lotto_collector.py      — 로또 당첨번호 수집기 — 동행복권 API → DB 저장
    │   └── lotto_recommender.py    — 로또 추천 (LLM 전용) — 시간의 파동 통계 + 의도 해석
    ├──  opinet/
    │   └── opinet_collector.py     — Opinet 유가정보 수집기: 무료 API → PostgreSQL 저장
    ├──  postgresql/
    │   ├── connection.py           — PostgreSQL 커넥션 풀 싱글톤 + 세션 컨텍스트 (mcp_query_fn DI)
    │   ├── queries.py              — PostgreSQL SQL 쿼리 상수 정의
    │   └── reader.py               — PostgreSQL 데이터 조회 계층 (read-only)
    ├──  utils/
    │   ├── conversion.py           — 센서/릴레이 데이터 추출, 안전한 숫자 변환
    │   ├── date_utils.py           — 날짜 파싱 및 포맷 변환 함수
    │   ├── error_utils.py          — 예외 처리 유틸 — 공통 try/except 로깅 패턴 표준화
    │   ├── http_client.py          — HTTP JSON 클라이언트 (urllib 기반, AI/MCP 무의존 base util)
    │   ├── json_utils.py           — 예외 안전한 JSON 직렬화/역직렬화
    │   └── validators.py           — is_true, clean_sensor_value, parse_boolean 등
    └──  voice/
        ├── stt_engine.py           — STT(음성→텍스트) 엔진
        └── tts_engine.py           — TTS(텍스트→음성) 엔진
```

---

## 주요 리팩토링 내역 (2026-04-17)

본 계층 구조를 달성하기 위한 구조적 변경:

1. **순환 참조 해소** — `src/ai/rag/constants.py`를 `DOC_TYPE_LABELS` 단일 원천으로 승격.
   `document_processor.py`·`document_enricher.py` 모두 `constants`에서 하향 import.

2. **HTTP 유틸 하위 계층 이관** — `mcp_http_request` / `_direct_http_json_request` 로직을
   `src/utils/http_client.py`로 이관. `chroma`·`postgresql`·`control`이 AI 계층을 우회.

3. **embedder / reranker 계층 상승** — `src/ai/rag/embedder.py` → `src/ai/embedder.py`,
   `src/ai/rag/reranker.py` → `src/ai/reranker.py` 이동. 여러 도구가 동급 레벨에서 호출 가능.

4. **의존성 주입 훅 도입**
   - `postgresql.connection.set_mcp_query_fn()` — AI의 MCP postgres 실행기 주입
   - `chroma.operations.set_embed_fn()` — AI의 임베딩 함수 주입
   - `control.task_scheduler.setup_default_jobs(opinet_collect_func=, lotto_collect_func=)`
   모두 `startup.py`에서 주입하여 하위 계층이 상위 모듈을 import하지 않도록 함.

5. **lotto 모듈 경로 정리** — `llm_client` facade 대신 동급 `llm_transport`·`llm_message_utils`
   를 직접 import하여 facade 우회 규칙 준수.
