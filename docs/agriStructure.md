# AGRI_AI_CORE 시스템 구조 문서

**작성일**: 2025-12-05
**분석 대상**: /workspace/jayeondeule 디렉토리 Python 모듈 (88개 파일)
**분석 도구**: Claude Code Agent (Sonnet 4.5)

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [기술 스택](#2-기술-스택)
3. [시스템 아키텍처](#3-시스템-아키텍처)
4. [디렉토리 구조](#4-디렉토리-구조)
5. [핵심 모듈 설명](#5-핵심-모듈-설명)
6. [데이터 흐름](#6-데이터-흐름)
7. [API 엔드포인트](#7-api-엔드포인트)
8. [데이터베이스 스키마](#8-데이터베이스-스키마)
9. [설정 및 환경변수](#9-설정-및-환경변수)
10. [실행 방법](#10-실행-방법)

---

## 1. 시스템 개요

AgriAI Core는 스마트팜 관리를 위한 AI 기반 통합 시스템입니다. PostgreSQL 기반의 센서/릴레이 데이터를 수집하고, ChromaDB 벡터 데이터베이스를 활용하여 LLM 기반 농장 관리 챗봇을 제공합니다.

### 주요 기능

| 기능 | 설명 |
|------|------|
| **데이터 수집** | PostgreSQL에서 센서/릴레이 데이터 수집 및 JSON 변환 |
| **데이터 변환** | JSON → ChromaDB 벡터 데이터베이스 변환 (ETL) |
| **AI 어시스턴트** | Ollama 기반 LLM 농장 관리 챗봇 |
| **릴레이 제어** | 농장 기기 자동/수동 제어 시스템 |
| **학습** | 데이터 분석 및 최적 조건 학습 |
| **웹 UI** | Streamlit 기반 웹 인터페이스 |
| **REST API** | FastAPI 기반 RESTful API 서버 |

---

## 2. 기술 스택

### 백엔드
- **프레임워크**: FastAPI 0.104+
- **언어**: Python 3.11+
- **비동기 처리**: asyncio, APScheduler
- **데이터 검증**: Pydantic

### 프론트엔드
- **UI 프레임워크**: Streamlit 1.28+
- **통신**: SSE (Server-Sent Events), REST API

### 데이터베이스
- **관계형 DB**: PostgreSQL 14+
- **벡터 DB**: ChromaDB 0.4+
- **연결 방식**: psycopg2 (PostgreSQL), chromadb-client (ChromaDB)

### AI/ML
- **LLM**: Ollama (llama3.2:latest)
- **임베딩**: 384차원 벡터 (Ollama embedding API)
- **RAG**: ChromaDB 벡터 검색 기반 컨텍스트 생성

### 인프라
- **프로세스 관리**: systemd
- **로깅**: Python logging with daily rotation
- **배포**: Docker (ChromaDB), 로컬 서비스 (FastAPI, Streamlit, Ollama)

---

## 3. 시스템 아키텍처

### 3.1 계층 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│         (API Routes, Streamlit UI, Runner Scripts)          │
├─────────────────────────────────────────────────────────────┤
│                   Business Logic Layer                      │
│              (LLM, Control, Learning Modules)               │
├─────────────────────────────────────────────────────────────┤
│                  Data Processing Layer                      │
│           (Data Ingestion, Data Pipeline Modules)           │
├─────────────────────────────────────────────────────────────┤
│                   Infrastructure Layer                      │
│         (Database, Logging, Shared Modules, Config)         │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 주요 의존성 관계

```
┌─────────────┐
│  API Routes │
└─────┬───────┘
      ├─→ LLM (query_handler)
      ├─→ Control (relay_controller)
      ├─→ Database (postgres, chromadb)
      └─→ Shared Modules (settings, exceptions)

┌─────────┐
│   LLM   │
└────┬────┘
     ├─→ Database (chromadb operations)
     ├─→ Control (relay_controller)
     ├─→ Data Pipeline (chroma_loader)
     └─→ Shared Modules (settings, validators, utils)

┌──────────┐
│ Control  │
└────┬─────┘
     ├─→ Database (postgres connection)
     ├─→ LLM (llm_client)
     └─→ Shared Modules (mappers, validators)

┌────────────────┐
│ Data Pipeline  │
└───────┬────────┘
        ├─→ Database (chromadb, postgres)
        ├─→ Data Ingestion (postgres_reader)
        └─→ Shared Modules (constants, mappers)

┌──────────┐
│ Learning │
└────┬─────┘
     ├─→ Database (chromadb, postgres)
     ├─→ Data Pipeline (chroma_loader)
     └─→ Shared Modules (settings, utils)

┌────────────┐
│ Streamlit  │
└─────┬──────┘
      ├─→ FastAPI (HTTP REST calls)
      └─→ Shared Modules (settings)
```

---

## 4. 디렉토리 구조

```
/workspace/jayeondeule/
│
├── run_to_fastapi.py                    # FastAPI 서버 런처
│
├── config.yaml                          # 메인 설정 파일
├── .env                                 # 환경변수 파일
│
├── logs/                                # 로그 디렉토리
│   ├── fastapi.log
│   ├── streamlit.log
│   └── llm_YYYY_MM_DD.log
│
├── agriAiCore                           # systemd 서비스 래퍼 스크립트
├── agriAiCore.service                   # systemd 서비스 파일
│
└── agri_ai_core/                        # 메인 패키지 (87개 파일)
    ├── __init__.py
    │
    ├── api/                             # FastAPI 관련 (9개)
    │   ├── main.py                      # 앱 생성
    │   ├── lifecycle.py                 # 시작/종료 이벤트
    │   ├── dependencies/
    │   └── routes/
    │       ├── chat.py                  # 챗 엔드포인트
    │       ├── farm.py                  # 농장 엔드포인트
    │       └── health.py                # 헬스체크
    │
    ├── control/                         # 제어 모듈 (7개)
    │   ├── relay/
    │   │   ├── relay_controller.py      # 릴레이 제어
    │   │   └── relay_manager.py         # 릴레이 관리
    │   └── scheduler/
    │       └── task_scheduler.py        # 스케줄러
    │
    ├── data_ingestion/                  # PostgreSQL → JSON (7개)
    │   ├── postgres_reader.py           # DB 읽기
    │   ├── json_exporter.py             # JSON 내보내기
    │   └── schemas/
    │       ├── sensor_schema.py
    │       └── relay_schema.py
    │
    ├── data_pipeline/                   # JSON → ChromaDB (10개)
    │   ├── json_loader.py               # JSON 로더
    │   ├── data_processor.py            # 데이터 처리 (3분 집계)
    │   ├── chroma_loader.py             # ChromaDB 로더
    │   ├── document_processor.py        # 문서 처리
    │   └── vectorization/
    │       ├── embedder.py              # 임베딩 생성
    │       └── chunker.py               # 문서 청킹
    │
    ├── database/                        # 데이터베이스 (8개)
    │   ├── postgres/
    │   │   ├── connection.py            # 연결 관리 (싱글톤)
    │   │   └── queries.py               # SQL 쿼리
    │   └── chromadb/
    │       ├── client.py                # 연결 관리
    │       ├── collections.py           # 컬렉션 이름
    │       └── operations.py            # CRUD 작업
    │
    ├── learning/                        # 학습 모듈 (4개)
    │   ├── data_analyzer.py             # 데이터 분석
    │   ├── model_trainer.py             # 모델 학습
    │   └── qa_generator.py              # QA 생성
    │
    ├── llm/                             # LLM 모듈 (14개)
    │   ├── core/
    │   │   └── llm_client.py            # Ollama 클라이언트
    │   ├── models/llama/                # LLaMA 모델
    │   ├── qa/
    │   │   └── query_handler.py         # 질의 처리
    │   └── routing/
    │       └── query_analyzer.py        # 질의 분석
    │
    ├── log_utils/                       # 로깅 (3개)
    │   └── log_handlers.py              # 일별 로테이션 핸들러
    │
    ├── shared_modules/                  # 공통 모듈 (13개)
    │   ├── common/
    │   │   ├── constants.py             # 상수 정의
    │   │   ├── mappers.py               # 센서/릴레이 매핑
    │   │   └── validators.py            # 데이터 검증
    │   ├── config/
    │   │   └── settings.py              # Pydantic 설정
    │   ├── exceptions/
    │   │   └── custom_exceptions.py     # 예외 클래스
    │   └── utils/
    │       ├── conversion.py            # 데이터 변환
    │       ├── date_utils.py            # 날짜 유틸
    │       └── text_utils.py            # 텍스트 유틸
    │
    ├── ui/                              # Streamlit UI (11개)
    │   └── streamlit_app/
    │       ├── main.py                  # 메인 앱
    │       ├── session_manager.py       # 세션 관리
    │       ├── chat_handler.py          # 채팅 처리
    │       ├── sidebar.py               # 사이드바
    │       ├── file_handler.py          # 파일 처리
    │       └── location_handler.py      # 위치 처리
    │
    ├── run_api.py                       # FastAPI 진입점
    └── run_streamlit.py                 # Streamlit 진입점
```

**총 파일 수**: 88개 Python 파일

---

## 5. 핵심 모듈 설명

### 5.1 API 모듈 (`agri_ai_core/api/`)

**역할**: FastAPI 기반 REST API 서버

**주요 컴포넌트**:

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱 생성, 라우터 등록, 싱글톤 관리 |
| `lifecycle.py` | 시작/종료 이벤트 핸들러 (DB 연결, 스케줄러) |
| `routes/chat.py` | 챗 엔드포인트 (일반, 스트리밍, 파일 포함) |
| `routes/farm.py` | 농장 데이터 엔드포인트 (상태, 릴레이 제어) |
| `routes/health.py` | 헬스체크 엔드포인트 |

**등록된 라우터**:
- `/api/v1/health` - 헬스체크
- `/api/v1/chat` - 챗
- `/api/v1/farm` - 농장 데이터
- `/get_default_farm_info` - 레거시 호환

### 5.2 Control 모듈 (`agri_ai_core/control/`)

**역할**: 농장 기기 릴레이 제어 및 스케줄링

**주요 함수**:

| 모듈 | 함수 | 설명 |
|------|------|------|
| `relay_controller.py` | `execute_relay_command()` | 릴레이 명령 실행 |
| | `detect_and_execute_relay_commands()` | 텍스트에서 릴레이 명령 감지 |
| | `get_single_house_status()` | 재배사 상태 조회 |
| `relay_manager.py` | `set_relay_value()` | 릴레이 값 설정 (PostgreSQL 업데이트) |
| | `get_relay_status()` | 릴레이 상태 조회 |
| `task_scheduler.py` | `setup_scheduler()` | APScheduler 설정 및 시작 |

### 5.3 Data Ingestion 모듈 (`agri_ai_core/data_ingestion/`)

**역할**: PostgreSQL → JSON 데이터 추출

**데이터 흐름**:
```
PostgreSQL
  ↓ read_units_data() (센서 + 릴레이)
  ↓ read_crops_data() (작물 생육)
JSON 파일 (./vector_cache/*.json)
```

**주요 함수**:

| 함수 | 설명 |
|------|------|
| `read_units_data()` | Units 데이터 조회 (센서 + 릴레이) |
| `read_crops_data()` | Crops 데이터 조회 (작물 생육) |
| `export_units_to_json()` | Units 데이터 JSON 내보내기 |
| `run_data_export()` | 전체 데이터 내보내기 실행 |

### 5.4 Data Pipeline 모듈 (`agri_ai_core/data_pipeline/`)

**역할**: JSON → ChromaDB 데이터 변환 및 저장

**데이터 처리**:
- **Units 데이터**: 3분 단위 집계 (align_to_3min)
- **Crops 데이터**: 초 단위 그대로 저장
- **임베딩**: Ollama API를 통한 384차원 벡터 생성

**주요 함수**:

| 함수 | 설명 |
|------|------|
| `json_to_vcdb()` | JSON → ChromaDB 변환 메인 함수 |
| `process_unit_data()` | Units 데이터 3분 집계 처리 |
| `embed_text()` | 텍스트 임베딩 생성 (Ollama) |
| `upsert_collection_data()` | ChromaDB 문서 업서트 |

### 5.5 Database 모듈 (`agri_ai_core/database/`)

**역할**: PostgreSQL 및 ChromaDB 연결 관리

#### PostgreSQL (`postgres/`)

**주요 클래스**:
- `DatabaseHandler`: 싱글톤 연결 관리자
  - `connect()`: DB 연결
  - `fetch_one()`: 단일 레코드 조회
  - `fetch_all()`: 복수 레코드 조회
  - `execute_query()`: CUD 쿼리 실행

**사용 예시**:
```python
with db_session() as database:
    result = database.fetch_one(query, vals)
```

#### ChromaDB (`chromadb/`)

**주요 함수**:

| 함수 | 설명 |
|------|------|
| `heartbeat()` | ChromaDB 연결 확인 |
| `create_collection()` | 컬렉션 생성 |
| `add_document()` | 문서 추가 |
| `query_documents()` | 벡터 검색 |

**문서 ID 생성 규칙**:
- Units: `units_{farm_id}_{house_id}_{timestamp}` (3분 버킷)
- Crops: `crops_{farm_id}_{house_id}_{timestamp}` (초 단위)

### 5.6 Learning 모듈 (`agri_ai_core/learning/`)

**역할**: 데이터 분석 및 최적 조건 학습

**주요 함수**:

| 함수 | 설명 |
|------|------|
| `analyze_farm_optimal_conditions()` | 농장 최적 조건 분석 |
| `analyze_farm_time_patterns()` | 시간 패턴 분석 |
| `process_stats_and_optimal_data()` | 통계 및 최적 데이터 처리 |
| `update_ollama_model()` | Ollama 모델 업데이트 |

### 5.7 LLM 모듈 (`agri_ai_core/llm/`)

**역할**: LLM 기반 질의 처리 및 응답 생성

#### 질의 처리 흐름

```
사용자 질의
  ↓
analyze_query_unified()      # 질의 분석
  ↓ (특수 명령, 농장 정보, 날짜 추출)
prepare_query_context()      # RAG 컨텍스트 준비
  ↓ (ChromaDB 벡터 검색)
get_llm_response()           # LLM 응답 생성 (Ollama)
  ↓ (스트리밍)
detect_and_execute_relay_commands()  # 릴레이 명령 감지/실행
  ↓
최종 응답 반환
```

**주요 함수**:

| 모듈 | 함수 | 설명 |
|------|------|------|
| `query_analyzer.py` | `analyze_query_unified()` | 통합 질의 분석 |
| `query_handler.py` | `query_llm_unified()` | 통합 LLM 질의 처리 |
| `llm_client.py` | `get_llm_response()` | LLM 응답 생성 (스트리밍) |

### 5.8 Shared Modules (`agri_ai_core/shared_modules/`)

**역할**: 공통 기능, 설정, 예외 처리

#### 주요 서브모듈

| 모듈 | 역할 |
|------|------|
| `config/settings.py` | Pydantic 기반 설정 관리 (싱글톤) |
| `common/mappers.py` | 센서/릴레이 한글-영문 매핑 |
| `common/validators.py` | 데이터 검증 함수 |
| `exceptions/custom_exceptions.py` | 커스텀 예외 클래스 |
| `utils/date_utils.py` | 날짜 관련 유틸리티 |
| `utils/text_utils.py` | 텍스트 처리 유틸리티 |

**설정 클래스 구조**:
```python
AppSettings
  ├── DatabaseSettings (PostgreSQL)
  ├── VectorStoreSettings (ChromaDB)
  ├── ModelSettings (Ollama)
  ├── CollectionSettings (컬렉션 이름)
  └── LoggingSettings (로그 경로/레벨)
```

### 5.9 UI 모듈 (`agri_ai_core/ui/streamlit_app/`)

**역할**: Streamlit 기반 웹 인터페이스

**주요 컴포넌트**:

| 파일 | 역할 |
|------|------|
| `main.py` | 메인 앱 진입점 |
| `session_manager.py` | 세션 상태 관리, FastAPI 호출 |
| `chat_handler.py` | 채팅 처리, SSE 스트리밍 |
| `sidebar.py` | 사이드바 (농장/재배사 선택) |
| `file_handler.py` | 파일 업로드 처리 |

**세션 상태 구조**:
```python
st.session_state = {
    "farm_id": "1",
    "farm_name": "자연들에 농장",
    "house_id": "1",
    "house_name": "상황버섯1호재배사",
    "messages": [],
    "uploaded_files": {},
}
```

---

## 6. 데이터 흐름

### 6.1 사용자 질의 처리

```
사용자 입력 (Streamlit UI)
  ↓
POST /api/v1/chat/stream (FastAPI)
  ↓
query_analyzer.analyze_query_unified()
  ├─ 특수 명령 식별 (릴레이 제어)
  ├─ 농장 정보 추출
  ├─ 날짜/시간 추출
  └─ 질의 카테고리 추론
  ↓
prepare_query_context()
  └─ ChromaDB 벡터 검색 (RAG)
  ↓
get_llm_response() (Ollama API)
  └─ 스트리밍 응답 생성
  ↓
detect_and_execute_relay_commands()
  └─ relay_manager.set_relay_value()
      └─ PostgreSQL 업데이트
  ↓
SSE 스트리밍 → Streamlit UI 업데이트
```

### 6.2 데이터 파이프라인 (PostgreSQL → ChromaDB)

```
┌──────────────┐
│ PostgreSQL   │
└──────┬───────┘
       │
       ├─ read_units_data() ────┐
       │   (센서 + 릴레이)       │
       │                         │
       └─ read_crops_data() ─────┤
           (작물 생육)           │
                                 ↓
                         ┌───────────────┐
                         │ JSON 파일     │
                         │ (vector_cache)│
                         └───────┬───────┘
                                 │
                   fetch_data_from_json()
                                 │
                    ┌────────────┴────────────┐
                    ↓                         ↓
           process_unit_data()      process_crop_data()
           (3분 집계)                (초 단위)
                    │                         │
                    └────────────┬────────────┘
                                 │
                          embed_text()
                    (Ollama 임베딩 생성)
                                 │
                                 ↓
                    upsert_collection_data()
                                 │
                                 ↓
                         ┌──────────────┐
                         │  ChromaDB    │
                         │ (farm_data_  │
                         │  source)     │
                         └──────────────┘
```

### 6.3 학습 워크플로우

```
┌──────────────────────┐
│ ChromaDB             │
│ (source_collection)  │
└──────────┬───────────┘
           │
   get_unlearned_data()
   (learned=False 조회)
           │
           ├─ analyze_farm_optimal_conditions()
           │   └─ 온도, 습도, CO2, 광량 최적 조건 분석
           │
           └─ analyze_farm_time_patterns()
               └─ 릴레이 시간 패턴 분석
           │
           ↓
   upsert_collection_data()
   (learned_collection 저장)
           │
           ↓
   update_learned_source_data()
   (learned=True 플래그 업데이트)
```

### 6.4 릴레이 제어 워크플로우

```
사용자 명령: "조명 켜줘"
  ↓
analyze_query_unified()
  └─ 릴레이 제어 명령 감지
  ↓
detect_and_execute_relay_commands()
  ↓
execute_relay_command()
  └─ 릴레이 번호, 값 추출
  ↓
relay_manager.set_relay_value()
  └─ PostgreSQL UPDATE
      (RELAY_L_RECORDING 테이블)
  ↓
응답 생성 및 반환
  └─ "조명을 켰습니다."
```

---

## 7. API 엔드포인트

### 7.1 Health Check

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/v1/health` | 기본 헬스체크 |
| GET | `/api/v1/health/detailed` | 상세 헬스체크 (DB 연결 확인) |
| GET | `/api/v1/health/ready` | 준비 상태 확인 |
| GET | `/api/v1/health/live` | 생존 상태 확인 |

### 7.2 Chat

| Method | Endpoint | 설명 | Request Body |
|--------|----------|------|--------------|
| POST | `/api/v1/chat` | 일반 채팅 | `{query, farm_id, house_id}` |
| POST | `/api/v1/chat/stream` | 스트리밍 채팅 (SSE) | `{query, farm_id, house_id}` |
| POST | `/api/v1/chat/with-files` | 파일 포함 채팅 | `{query, farm_id, house_id, files}` |

### 7.3 Farm

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/get_default_farm_info` | 기본 농장 정보 조회 (레거시) |
| GET | `/api/v1/farm/{farm_id}/status` | 농장 상태 조회 |
| GET | `/api/v1/farm/{farm_id}/relay/status` | 릴레이 상태 조회 |
| POST | `/api/v1/farm/relay/control` | 릴레이 제어 |
| POST | `/api/v1/farm/mode` | 작동 모드 변경 (수동/자동) |

### 7.4 API Documentation

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |

---

## 8. 데이터베이스 스키마

### 8.1 PostgreSQL 테이블

| 테이블명 | 설명 | 주요 컬럼 |
|----------|------|-----------|
| `FARM_M_INFO` | 농장 마스터 | `farm_id`, `farm_name` |
| `FARMHOUSE_M_INFO` | 재배사 마스터 | `farm_id`, `hous_id`, `hous_name` |
| `SENSOR_L_RECORDING` | 센서 기록 | `farm_id`, `hous_id`, `reg_date`, 센서 값들 |
| `RELAY_L_RECORDING` | 릴레이 기록 | `farm_id`, `hous_id`, `reg_date`, 릴레이 값들 |
| `FARMHOUSE_L_CROPS` | 작물 생육 기록 | `farm_id`, `hous_id`, `reg_date`, 생육 데이터 |

### 8.2 ChromaDB 컬렉션

| 컬렉션명 | 설명 | 문서 ID 형식 |
|----------|------|--------------|
| `farm_data_source` | 원본 데이터 (Units + Crops) | `units_{farm_id}_{house_id}_{ts}` |
| `farm_data_learned` | 학습 완료 데이터 | 동일 |
| `farm_stats` | 통계 데이터 | - |
| `farm_optimal_condition` | 최적 조건 | - |
| `farm_documents` | 문서 | - |
| `job_status` | 작업 상태 | - |
| `self_learning` | 자가 학습 | - |
| `learning_pattern` | 학습 패턴 | - |

**메타데이터 구조** (farm_data_source):
```json
{
  "farm_id": "1",
  "house_id": "1",
  "data_type": "units",
  "reg_date": "2025-12-05 10:00:00",
  "learned": false,
  "temperature": 25.5,
  "humidity": 60.0,
  ...
}
```

---

## 9. 설정 및 환경변수

### 9.1 환경변수 (.env)

```bash
# PostgreSQL Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=smartfarm
DB_USER=postgres
DB_PASSWORD=password

# ChromaDB
CHROMA_HOST=localhost
CHROMA_PORT=8000

# Ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest
OLLAMA_TIMEOUT=120

# Logging
LOG_PATH=/workspace/jayeondeule/logs
LOG_LEVEL=INFO

# API
FASTAPI_URL=http://localhost:8088
STREAMLIT_PORT=8501

# Embedding
EMBEDDING_DIM=384
```

### 9.2 설정 파일 (config.yaml)

```yaml
database:
  host: localhost
  port: 5432
  database: smartfarm
  user: postgres

vector:
  chroma_host: localhost
  chroma_port: 8000

model:
  ollama_url: http://localhost:11434
  ollama_model: llama3.2:latest

logging:
  log_path: /workspace/jayeondeule/logs
  log_level: INFO
```

### 9.3 로그 파일 위치

```
/workspace/jayeondeule/logs/
├── fastapi.log              # FastAPI stdout
├── streamlit.log            # Streamlit stdout
└── llm_YYYY_MM_DD.log       # 일별 로테이션 LLM 로그
```

---

## 10. 실행 방법

### 10.1 systemd 서비스로 실행 (권장)

```bash
# 서비스 시작 (FastAPI + Streamlit 동시 시작)
sudo systemctl start agriAiCore.service

# 서비스 상태 확인
sudo systemctl status agriAiCore.service

# 서비스 중지
sudo systemctl stop agriAiCore.service

# 서비스 재시작
sudo systemctl restart agriAiCore.service

# 로그 확인
journalctl -u agriAiCore.service -f
```

### 10.2 래퍼 스크립트로 실행

```bash
# 서비스 시작
./agriAiCore start

# 서비스 상태 확인
./agriAiCore status

# 서비스 중지
./agriAiCore stop

# 서비스 재시작
./agriAiCore restart
```

### 10.3 개별 실행 (개발 환경)

```bash
# FastAPI 서버 실행
python run_to_fastapi.py
# 또는
python -m agri_ai_core.run_api

# Streamlit UI 실행 (별도 터미널)
python -m agri_ai_core.run_streamlit
```

### 10.4 데이터 파이프라인 실행

```python
# PostgreSQL → JSON
from agri_ai_core.data_ingestion.json_exporter import run_data_export
run_data_export()

# JSON → ChromaDB
from agri_ai_core.data_pipeline.json_loader import json_to_vcdb
json_to_vcdb()
```

### 10.5 학습 실행

```python
# 데이터 분석 및 최적 조건 학습
from agri_ai_core.learning.data_analyzer import process_stats_and_optimal_data
process_stats_and_optimal_data()

# Ollama 모델 업데이트
from agri_ai_core.learning.model_trainer import update_ollama_model
update_ollama_model()
```

---

## 부록: 주요 SQL 쿼리

### A.1 농장-재배사 목록 조회
```sql
SELECT farm_id, farm_name, hous_id, hous_name
FROM FARM_M_INFO
JOIN FARMHOUSE_M_INFO USING (farm_id)
ORDER BY farm_id, hous_id
```

### A.2 Units 데이터 조회 (센서 + 릴레이)
```sql
SELECT
    s.farm_id, s.hous_id, s.reg_date,
    s.temp_out, s.temp_in, s.humi_out, s.humi_in,
    s.co2, s.water_temp, s.light_level,
    r.value1, r.value2, r.value3, ...
FROM SENSOR_L_RECORDING s
LEFT JOIN RELAY_L_RECORDING r
    ON s.farm_id = r.farm_id
    AND s.hous_id = r.hous_id
    AND s.reg_date = r.reg_date
WHERE s.reg_date > %s
ORDER BY s.reg_date
```

### A.3 Crops 데이터 조회
```sql
SELECT
    farm_id, hous_id, reg_date,
    growth_status, leaf_count, leaf_length,
    remarks
FROM FARMHOUSE_L_CROPS
WHERE reg_date > %s
ORDER BY reg_date
```

### A.4 릴레이 값 설정
```sql
UPDATE RELAY_L_RECORDING
SET value{relay_no} = %s, reg_date = NOW()
WHERE farm_id = %s AND hous_id = %s
```

---

**문서 끝**

**최종 업데이트**: 2025-12-05
**분석 도구**: Claude Code Agent (Sonnet 4.5)
**분석 범위**: 88개 Python 파일
**페이지 수**: 약 15페이지 (A4 기준)
