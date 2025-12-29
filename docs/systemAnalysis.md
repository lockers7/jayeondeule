# AGRI_AI_CORE 시스템 분석 보고서

> 분석일: 2025-11-29
> 프로젝트: Smart Farm AI Assistant System

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **프로젝트 유형** | 스마트팜 AI 어시스턴트 시스템 |
| **주요 언어** | Python |
| **핵심 프레임워크** | FastAPI, Streamlit, ChromaDB, PostgreSQL, Ollama |
| **목적** | 버섯/온실 재배 환경 모니터링 및 AI 기반 자동 제어 시스템 |

---

## 2. 현재 디렉토리 구조

```
h:\Workspace\agri_ai_core\
├── config.yaml                          # 서버 및 시스템 설정
├── constraints.txt                      # 재현성을 위한 고정 의존성
├── docker-compose.yml                   # ChromaDB, Ollama Docker 서비스
├── requirements.txt                     # 메인 의존성
├── run_to_fastapi.py                   # FastAPI 진입점
├── streamlit_chat.py                   # Streamlit UI 진입점
│
└── src/llm_framework/                  # 메인 애플리케이션 패키지
    ├── __init__.py
    ├── settings.py                      # 설정 관리 (Pydantic dataclasses)
    ├── config.py                        # 전역 설정 상수 및 헬퍼 함수 (973 lines)
    │
    ├── entrypoints/
    │   ├── __init__.py
    │   ├── api.py                       # FastAPI 서버 (1636 lines)
    │   ├── streamlit_app.py             # Streamlit UI (840 lines)
    │   ├── temp_files/                  # 임시 파일 저장소
    │   └── uploads/                     # 파일 업로드 저장소
    │
    └── modules/                         # 핵심 비즈니스 로직 (12,912 lines total)
        ├── __init__.py
        ├── log_handler.py               # 일별 로테이션 파일 로거 (92 lines)
        ├── postgre_handler.py           # PostgreSQL 연결 관리 (206 lines)
        ├── postgre_query.py             # SQL 쿼리 정의 (244 lines)
        ├── chroma_client.py             # ChromaDB 클라이언트 래퍼
        ├── chroma_rest_api.py           # ChromaDB REST API (815 lines)
        ├── chorma_handler.py            # ChromaDB 데이터 관리 (687 lines)
        ├── llm_core.py                  # Ollama LLM 인터페이스 (64 lines)
        ├── llm_processor.py             # 응답 처리 및 정리 (739 lines)
        ├── llm_query_handler.py         # 통합 쿼리 라우팅 (220 lines)
        ├── llm_query_analyzer.py        # 쿼리 분류 및 분석 (467 lines)
        ├── llm_query_generator.py       # 프롬프트 생성 (1177 lines)
        ├── data_retriever.py            # 컨텍스트 데이터 검색 (1128 lines)
        ├── llm_rag_analysis.py          # RAG 분석 파이프라인 (1486 lines)
        ├── llm_rag_training.py          # 모델 학습 오케스트레이션 (795 lines)
        ├── llm_rag_ref_web.py           # 웹 참조 검색 (292 lines)
        ├── llm_rag_relay_control.py     # 릴레이 제어 조정 (68 lines)
        ├── dat_pgdb_to_json.py          # PostgreSQL → JSON 변환 (196 lines)
        ├── dat_json_to_vcdb.py          # JSON → ChromaDB 로딩 (416 lines)
        ├── llm_document_process.py      # 파일 첨부 처리 (265 lines)
        ├── control_schema.py            # 제어 계획 Pydantic 모델 (183 lines)
        ├── control_router.py            # 제어 메시지 라우팅
        ├── control_prompts.py           # LLM 프롬프트 템플릿 (112 lines)
        ├── relay_status.py              # 릴레이 상태 및 응답 생성 (344 lines)
        ├── pattern_query.py             # 쿼리 패턴 정의 (112 lines)
        ├── pattern_other.py             # 추가 패턴
        ├── utils_date.py                # 날짜/시간 파싱 유틸 (166 lines)
        ├── utils_farm.py                # 농장 특화 유틸
        ├── utils_text.py                # 텍스트 처리 유틸
        ├── location_manager.py          # 지리 위치 및 날씨 (414 lines)
        ├── com_function.py              # 공통 유틸 함수
        ├── llm_session_manager.py       # 세션 상태 관리
        ├── scheduler.py                 # 백그라운드 태스크 스케줄러 (134 lines)
        │
        └── relay/                       # 릴레이 제어 서브패키지
            ├── __init__.py              # 패키지 exports (60 lines)
            ├── automatic.py             # 자동 릴레이 제어 (910 lines)
            ├── manual.py                # 겨울철 수동 제어 (387 lines)
            ├── data_access.py           # 센서/릴레이 DB 접근 (514 lines)
            └── common.py                # 공통 안전 규칙
```

---

## 3. 모듈별 상세 분석

### 3.1 설정 및 환경 관리

#### settings.py
**목적:** 중앙 집중식 설정 관리

**주요 Dataclass:**
- `DatabaseSettings`: PostgreSQL 연결 파라미터
- `VectorStoreSettings`: ChromaDB 설정
- `ModelSettings`: LLM 모델 파라미터
- `CollectionSettings`: ChromaDB 컬렉션명
- `LoggingSettings`: 로그 설정
- `AppSettings`: 통합 애플리케이션 설정

#### config.py (973 lines)
**내용:**
- **컬렉션 이름 (10개)**
  - farm_collection: 농장 메타데이터
  - source_collection: 원본 센서/릴레이 데이터
  - stats_collection: 계산된 통계
  - optimal_collection: 최적 환경 조건
  - learned_collection: LLM 학습 패턴
  - setting_collection: 시스템 설정
  - document_collection: 업로드된 문서
  - job_status_collection: 작업 상태
  - self_learning_collection: 자가학습 패턴
  - learning_pattern_collection: 패턴 분석 결과

- **센서 매핑 (8개 센서)**
  - indoor_temperature, indoor_humidity, outdoor_temperature
  - outdoor_humidity, co2, water_temperature, light_level, water_level

- **릴레이 매핑 (14개 릴레이)**
  - water_heater, fog_motor, drainage_motor, intake_fan, exhaust_fan
  - lighting, irrigation, indoor_heater, air_circulation_valve
  - air_intake_valve, air_exhaust_valve, water_heater_flag, radiator, heater_valve

- **데이터 제한 및 임계값**
  - QUERY_SOURCE_CNT=30
  - PROMPT_SOURCE_LIMIT=10
  - PROMPT_LEARNED_LIMIT=5
  - CONTROL_DEEP_LINE_THRESHOLD=2000
  - CONTROL_CO2_THRESHOLD=1300

- **헬퍼 함수들**
  - 날짜 포맷팅
  - JSON 파싱
  - 센서/릴레이 데이터 변환
  - 릴레이 설정 초기화

---

### 3.2 로깅 시스템

#### log_handler.py (92 lines)
**기능:**
- 날짜 기반 파일명 패턴의 일별 로테이션 핸들러
- 이중 출력: 파일 + 콘솔
- 모듈별 로거 인스턴스
- 설정 가능한 로그 레벨
- 캐시가 있는 싱글톤 패턴

**로그 형식:** `[timestamp] [level] [module_name] -> message`

**출력 경로:** `logs/llm_YYYY_MM_DD.log`

---

### 3.3 데이터베이스 레이어

#### PostgreSQL Handler (postgre_handler.py - 206 lines)
- **싱글톤 패턴** 연결 관리
- 메서드: `connect()`, `execute_query()`, `fetch_all()`, `fetch_one()`
- 컨텍스트 매니저: `db_session()` 자동 연결 처리
- `psycopg2` + `RealDictCursor` 딕셔너리 결과
- 재사용 시 연결 상태 확인

#### SQL 쿼리 (postgre_query.py - 244 lines)
- 20개 이상의 사전 정의된 SQL 쿼리
  - 농장/하우스 데이터 조회
  - 센서 값 쿼리
  - 릴레이 설정
  - 히스토리 데이터
  - 통계

---

### 3.4 벡터 데이터베이스 (ChromaDB)

#### REST API 래퍼 (chroma_rest_api.py - 815 lines)
- ChromaDB v2 API RESTful 인터페이스
- 엔드포인트:
  - `heartbeat()`: 헬스체크
  - `list_collections()`: 컬렉션 열거
  - `get_documents()`: 문서 쿼리
  - `upsert_collection_data()`: 문서 추가/업데이트
  - `delete_documents()`: ID로 삭제
  - `ensure_required_collections_exist()`: 자동 컬렉션 생성

#### 데이터 핸들러 (chorma_handler.py - 687 lines)
- 고수준 데이터 관리 작업
- 함수:
  - `get_unlearned_data()`: 학습 대상 데이터 조회
  - `update_learned_source_data()`: 학습 완료 표시
  - `update_learned_last_status()`: 학습 타임스탬프 업데이트
  - 컬렉션 생성 및 검증

---

### 3.5 LLM 핵심 시스템

#### LLM 인터페이스 (llm_core.py - 64 lines)
- **Ollama 인터페이스**: ollama.chat() 직접 호출
- 모델: 설정 가능 (기본: `mxbai-embed-large`)
- 파라미터: temperature=0.7, top_p=0.9, top_k=40
- 재시도 로직: 실패 시 2회 재시도
- 응답 검증: 다양한 응답 형식 처리

#### 쿼리 핸들러 (llm_query_handler.py - 220 lines)
- **통합 진입점**: `query_llm_unified()` async 함수
- 기능:
  - 쿼리 유형 분석 (날짜, 날씨, 문서학습 등)
  - 특수 명령 라우팅
  - 날씨 API 통합
  - 파일 첨부 처리
  - 컨텍스트 데이터 검색
  - 스트림 지원

#### 쿼리 분석기 (llm_query_analyzer.py - 467 lines)
- **쿼리 분류**:
  - 쿼리 유형: sensor_data, statistics, optimal_condition, learned_data 등
  - LLM 쿼리 유형: 날짜관련, 웹검색관련, 일반질문 등
  - 농장/하우스 ID 추출
  - 시간대 추출
  - 카테고리: agriculture, general, technical 등

#### 프롬프트 생성기 (llm_query_generator.py - 1177 lines)
- **시스템 프롬프트 구성** 기반:
  - 쿼리 유형 및 카테고리
  - 현재 농장/하우스 컨텍스트
  - 센서 데이터 및 최적 조건
  - 히스토리 패턴
  - 특수 지시사항

#### LLM 프로세서 (llm_processor.py - 739 lines)
- **응답 처리**:
  - 스트리밍 청크 정리
  - 모델 아티팩트 제거 (예: `<think>` 태그)
  - 마크다운 포맷팅
  - 구조화된 응답 추출
  - 에러 처리

---

### 3.6 RAG 파이프라인

#### 데이터 검색기 (data_retriever.py - 1128 lines)
- **컨텍스트 검색** 다중 소스:
  - 현재 센서 데이터 (PostgreSQL)
  - 히스토리 데이터 (ChromaDB source_collection)
  - 학습 패턴 (ChromaDB learned_collection)
  - 통계 (ChromaDB stats_collection)
  - 최적 조건 (ChromaDB optimal_collection)
  - 문서 참조 (ChromaDB document_collection)

- **필터링 로직**:
  - farm_id, house_id 기준
  - 날짜 범위 기준
  - 센서 유형 기준
  - 관련성 점수 기준

#### RAG 분석 (llm_rag_analysis.py - 1486 lines)
- **심층 분석 파이프라인**:
  - 패턴 감지 (계절별, 시간별, 이상치)
  - 추세 분석 (센서 리딩)
  - 상관관계 분석 (센서 관계)
  - 이상치 감지
  - 예측 (기본 추세 투영)
  - 리포트 생성

#### 학습 모듈 (llm_rag_training.py - 795 lines)
- **모델 학습 오케스트레이션**:
  - 시간별 예약 학습
  - PostgreSQL 데이터 추출
  - 청크 생성 (1000자 청크)
  - 임베딩 생성
  - ChromaDB 저장
  - 학습 상태 추적

#### 웹 참조 (llm_rag_ref_web.py - 292 lines)
- 날씨 API 통합
- 외부 참조 검색
- 웹 검색 조정

---

### 3.7 릴레이 제어 시스템

#### 자동 제어 (relay/automatic.py - 910 lines)
- **메인 오케스트레이터**: `control_all_relays()`
  - 센서에서 현재 환경 조회
  - ChromaDB에서 최적 조건 검색
  - `determine_relay_settings()`로 릴레이 설정 결정
  - 안전 규칙 검증
  - 제어 결정 로깅
  - 릴레이 설정 DB 저장

- **로직 엔진**: 규칙 기반 + LLM 지원
  - 온도 제어 (온수기, 실내 히터)
  - 습도 제어 (가습기, 제습)
  - CO2 제어 (공기순환)
  - 조명 제어
  - 수위 제어

#### 수동 제어 (relay/manual.py - 387 lines)
- **겨울철 예측**: `calculate_heater_operation_predictions()`
- 기능:
  - 온도 추세 분석
  - 히터 작동 예측
  - 비용 추정
  - 수동 오버라이드

#### 데이터 접근 레이어 (relay/data_access.py - 514 lines)
- **센서 데이터 접근**:
  - 현재 환경: `get_current_environment_data()`
  - 최적 조건: `get_optimal_conditions()`
  - 센서 히스토리: `fetch_recent_sensor_history()`
  - 릴레이 상태: `get_relay_settings()`

- **릴레이 관리**:
  - 릴레이 설정 저장: `save_relay_settings()`
  - 제어 액션 로깅
  - 릴레이 상태 변경 추적

#### 공통 안전 규칙 (relay/common.py)
- 규칙 강제:
  - RULE_1: 온수기와 실내히터 동시 ON 불가
  - RULE_2: 최소 하나의 공기 경로 유지
  - RULE_3: CO2 응답 요구사항
  - RULE_4: 안전 임계값
  - RULE_5: 릴레이 상호작용 제약

---

### 3.8 데이터 파이프라인

#### PostgreSQL → JSON (dat_pgdb_to_json.py - 196 lines)
- PostgreSQL에서 센서 데이터 추출
- JSON 형식으로 변환
- 로컬 파일시스템 캐시
- 예약 실행 (3분 간격)

#### JSON → ChromaDB (dat_json_to_vcdb.py - 416 lines)
- JSON 데이터 로드
- 임베딩 생성
- 데이터 청킹 (1000자 청크, 100자 오버랩)
- ChromaDB 컬렉션 저장

#### 문서 처리 (llm_document_process.py - 265 lines)
- 파일 첨부 처리 (PDF, CSV, Excel, 이미지, 텍스트)
- 텍스트 내용 추출
- 임베딩 생성
- document_collection 저장
- 쿼리 연결

---

### 3.9 제어 스키마 및 검증

#### control_schema.py (183 lines)
**Pydantic 모델:**
```python
Env: indoor_temp, humidity, CO2, water_temp, status_summary
Relays: water_heater, fog_motor, heater, intake_fan, exhaust_fan,
        intake_valve, exhaust_valve, lighting, irrigation (9개 릴레이)
ControlPlan:
  - house_id
  - timestamp
  - environment_assessment
  - air_circulation_mode
  - relay_settings
  - safety_rule_checks (리스트)
  - reason (최대 300자)
```

**검증기:**
- 타임스탬프 형식 검증
- 안전 규칙 검사 (1개 이상 항목)
- 릴레이 설정 제약 (상호 배제)
- RULE_1 & RULE_2 강제

---

### 3.10 패턴 매칭

#### pattern_query.py (112 lines)
- 문서 학습 패턴 (7개 패턴)
- 학습 정보 패턴 (7개 패턴)
- LLM 정체성 패턴 (12개 패턴)
- 작기 패턴 (12개 패턴)
- 작물 재배 패턴 (13개 패턴)
- 질병 패턴 (12개 패턴)
- 수확 패턴 (8개 패턴)
- 이익 패턴 (10개 패턴)

모든 패턴은 대소문자 무시 정규식 사용.

---

### 3.11 유틸리티

#### 날짜/시간 유틸 (utils_date.py - 166 lines)
- 날짜 범위 추출 (절대 & 상대)
- 주/월 범위 계산
- 쿼리에서 시간 추출
- ISO 8601 포맷팅

#### 위치 관리자 (location_manager.py - 414 lines)
- 한국 도시 → 영문 매핑 (200개 이상 도시)
- IP 기반 지리적 위치
- 날씨 API 통합
- 도시 거리 계산
- 브라우저 위치 지원

#### 텍스트 유틸 (utils_text.py)
- 텍스트 정규화
- 한글 문자 처리
- 특수 문자 정리

#### 농장 유틸 (utils_farm.py)
- 농장 특화 계산
- 작물 데이터 처리

---

### 3.12 스케줄링 및 백그라운드 태스크

#### scheduler.py (134 lines)

**예약된 작업:**
1. **데이터 전송** (매 3분)
   - PostgreSQL → JSON → ChromaDB
   - Job ID: `db_task`

2. **모델 학습** (매일 오전 4시 & 오후 4시)
   - Ollama 모델 미세조정
   - Job ID: `ollama_task`

3. **릴레이 제어** (매 5분, :00, :05, :10 등)
   - 자동 릴레이 결정
   - Job ID: `relay_control_task`

4. **농장 컬렉션 업데이트** (매일 오후 7시)
   - 농장 메타데이터 업데이트
   - Job ID: `farm_collection_task`

**기술 스택:** APScheduler
- 시간 기반 작업용 `CronTrigger`
- 주기적 작업용 `IntervalTrigger`
- 백그라운드 실행
- 중복 방지 (`max_instances=1`)

---

### 3.13 FastAPI 서버 (api.py - 1636 lines)

#### 아키텍처:
- **라이프사이클 관리**: 시작/종료 핸들러
- **서비스 상태 추적**: 스케줄러, Streamlit 프로세스 상태
- **스레드 안전 작업**: 상태 관리용 RLock
- **미들웨어**: 컬렉션 검증 및 에러 처리

#### 엔드포인트 (30개 이상):

**헬스 & 상태:**
- `GET /` - 서버 상태
- `GET /health` - 서비스 헬스체크
- `GET /status` - 상세 상태
- `GET /system_status` - 컴포넌트 상태

**데이터 관리:**
- `GET /get_environment/{farm_id}/{house_id}` - 현재 환경
- `GET /get_units_crops_data` - JSON 데이터 뷰어 (HTML)
- `GET /update_farm_collection` - 농장 데이터 강제 업데이트
- `GET /postgresql_to_chromadb` - 수동 데이터 마이그레이션
- `GET /pgdb_to_json` - PostgreSQL → JSON 내보내기
- `GET /json_to_vcdb` - JSON → ChromaDB 로드

**학습:**
- `POST /force_training` - 수동 모델 학습 (날짜 범위)
- `POST /simple_force_training` - 단순화된 학습

**릴레이 제어:**
- `GET /control_relays` - 즉시 릴레이 제어
- `POST /manual_control_relay/{farm_id}/{house_id}` - 수동 릴레이 설정
- `POST /manual_control_relay/winter/{farm_id}/{house_id}` - 겨울 모드

**스케줄링:**
- `GET /start_scheduler` - 백그라운드 스케줄러 시작
- `GET /stop_scheduler` - 백그라운드 스케줄러 중지

**챗 & 쿼리:**
- `POST /chat` - 표준 챗 (비스트리밍)
- `POST /chat_streaming` - SSE 스트리밍 응답
- `POST /chat_with_files` - 파일 첨부 챗
- `POST /chat_streaming_with_files` - 파일 첨부 스트리밍
- `POST /chat_with_history` - 대화 히스토리 포함 챗

**파일 작업:**
- `POST /rag/upload_and_vectorize` - 파일 업로드 & 벡터화

**데이터 검색:**
- `GET /get_default_farm_info` - 기본 농장/하우스 정보

---

### 3.14 Streamlit UI (streamlit_app.py - 840 lines)

#### 인터페이스 레이아웃:
```
┌─────────────────────────────────────────┐
│ 왼쪽 사이드바 (2/8 너비)  │ 메인 챗 (8/8)
├───────────────────────────────┤
│ 농장/하우스 선택             │ 챗 히스토리 표시
│ 날씨 위치 정보               │ 파일 첨부 영역
│ 날씨 업데이트 컨트롤         │ 챗 입력
└─────────────────────────────────────────┘
```

#### 기능:
1. **농장/하우스 선택**
   - DB 기반 드롭다운 선택기
   - URL 네비게이션용 쿼리 파라미터 지원
   - 기본 농장 조회

2. **날씨 통합**
   - IP 기반 위치 감지
   - 브라우저 위치 (JavaScript)
   - 수동 도시 오버라이드
   - 날씨 데이터 표시

3. **파일 관리**
   - 다중 파일 업로드
   - 파일 미리보기 (크기 표시)
   - 파일별 삭제
   - API 전송용 Base64 인코딩

4. **챗 인터페이스**
   - 역할별 메시지 히스토리 표시
   - 애니메이션 커서가 있는 스트리밍 응답
   - Async/sync 폴백 처리
   - Think 태그 필터링

5. **세션 상태 관리**
   - 농장/하우스 선택 유지
   - 메시지 히스토리 추적
   - 업로드 파일 추적
   - 날씨 도시 선택
   - 위치 감지 플래그

---

## 4. 모듈 의존성 그래프

```
api.py (FastAPI)
├── config.py
├── settings.py
├── log_handler.py
├── scheduler.py
│   ├── llm_rag_training.py
│   ├── llm_rag_relay_control.py
│   ├── relay/automatic.py
│   └── dat_json_to_vcdb.py
├── llm_query_handler.py
│   ├── llm_query_analyzer.py
│   ├── data_retriever.py
│   ├── llm_query_generator.py
│   ├── llm_processor.py
│   └── llm_rag_analysis.py
├── chroma_rest_api.py
├── postgre_handler.py
└── relay/
    ├── automatic.py
    ├── data_access.py
    └── manual.py

streamlit_app.py (Streamlit)
├── config.py
├── postgre_handler.py
├── location_manager.py
└── llm_query_handler.py

relay/automatic.py
├── relay/data_access.py
├── relay/common.py
├── postgre_handler.py
└── chroma_rest_api.py

data_retriever.py
├── postgre_handler.py
├── chroma_rest_api.py
└── utils_date.py

llm_rag_training.py
├── chroma_rest_api.py
├── postgre_handler.py
└── llm_core.py
```

---

## 5. 공유 함수 및 유틸리티

### config.py 함수:
```python
# 컬렉션 접근자
farm_collection(), source_collection(), stats_collection(),
optimal_collection(), learned_collection(), setting_collection(),
document_collection(), job_status_collection(), self_learning_collection(),
learning_pattern_collection()

# 데이터 변환
clean_sensor_value(value) → float
parse_boolean(value) → bool
safely_get_json(json_str) → dict
json_serialize(obj) → JSON 호환
convert_sensor_relay_data(data_item) → {sensor_data, relay_data}

# 포맷팅
format_datetime(datetime_str) → 한국어 형식
format_json_with_inline_objects(data) → 가독성 좋은 JSON
parse_datetime(dt_str) → datetime

# 센서/릴레이 정보
get_sensor_name(key) → 한글 이름
get_sensor_unit(key) → 측정 단위
get_relay_mapping(house_id) → 릴레이 필드 매핑
search_relay_function(search_item, search_type, search_value, return_type)

# 환경 분석
analyze_environment_condition(type, current, optimal, min, max)
  → "too_low" | "too_high" | "optimal" | "unknown"

# 시스템 작업
kill_existing_instance() → PID 8088 종료
check_system_status() → 서비스 상태 딕셔너리
initialize_relay_settings(house_id) → 릴레이 기본값
create_common_relay_settings() → 릴레이 템플릿
```

### 로거 사용:
```python
from modules.log_handler import setup_logger
logger = setup_logger(__name__)
logger.info/warning/error/debug(message)
```

### 데이터베이스 컨텍스트 매니저:
```python
from modules.postgre_handler import db_session
with db_session() as database:
    result = database.fetch_one(query, values)
    results = database.fetch_all(query, values, as_dict=True)
    success = database.execute_query(query, values)
```

---

## 6. 현재 아키텍처 문제점

### 6.1 코드 조직 문제
- **단일 config.py** (973 lines): 관련 없는 함수들이 혼합
  - 헬퍼 함수와 상수가 혼재
  - 분리 필요: constants, utilities, mapper

- **대형 단일 모듈**:
  - `api.py` (1636 lines): API 라우트 + 비즈니스 로직 + 파일 처리
  - `llm_rag_analysis.py` (1486 lines): 다중 책임
  - `llm_query_generator.py` (1177 lines): 복잡한 프롬프트 빌딩

- **일관성 없는 명명**:
  - `chorma_handler.py` (오타: "chorma" vs "chroma")
  - 일부 모듈에서 snake_case와 PascalCase 혼용

### 6.2 의존성 및 결합 문제
- **순환 의존성**: config.py가 modules에서 import, modules가 config import
- **긴밀한 결합**: API가 비즈니스 로직을 직접 import (서비스 레이어 필요)
- **전역 상태**: 설정 및 구성이 제대로 캡슐화되지 않음
- **스케줄러 의존성**: scheduler.py가 여러 관련 없는 모듈에서 import

### 6.3 데이터베이스 접근 문제
- **추상화 레이어 누락**: 원시 SQL 쿼리 분산
- **연결 풀링 없음**: 단순 싱글톤, 동시 요청에 비이상적
- **약한 쿼리 조직**: SQL 쿼리가 별도 파일이나 타입 부족
- **일관성 없는 에러 처리**: 일부는 empty/None 반환, 일부는 raise

### 6.4 LLM 통합 문제
- **하드코딩된 파라미터**: temperature, top_p 등이 코드에 있음
- **버저닝 없음**: 모델 버전 추적 안됨
- **약한 프롬프트 엔지니어링**: 프롬프트가 generator에 내장, 외부화 안됨
- **캐싱 없음**: 동일 쿼리 반복 계산
- **스트리밍 복잡성**: 스트림 필터링(think 태그)이 프로세서에 있어야 함

### 6.5 릴레이 제어 문제
- **복잡한 불린 로직**: 안전 규칙이 여러 곳에 분산
- **제한된 검증**: 릴레이 설정이 스키마 레벨에서만 검증
- **상태 추적 누락**: 전환 상태 로깅 없음
- **약한 진단**: 릴레이 결정의 제한된 로깅
- **하우스별 매핑**: 두 릴레이 매핑(E-version)이 복잡성 추가

### 6.6 데이터 파이프라인 문제
- **배치 처리**: 3분 간격으로 실시간 데이터 손실 가능
- **버저닝 없음**: 데이터 버전 추적 없음
- **약한 변환**: JSON 변환 중 최소 검증
- **롤백 없음**: 잘못된 데이터 마이그레이션 복원 방법 없음
- **일관성 없는 청킹**: 다른 모듈에서 다른 청크 크기

### 6.7 테스트 및 신뢰성 문제
- **단위 테스트 없음**: 리포지토리에 테스트 파일 없음
- **통합 테스트 없음**: 테스트 데이터 또는 픽스처 없음
- **약한 에러 처리**: 일반 Exception으로 많은 try/except
- **실패 로깅 없음**: 일부 백그라운드 태스크 조용한 실패
- **모니터링 없음**: 메트릭 또는 알림 인프라 없음

### 6.8 UI/UX 문제
- **Streamlit 제한**: 매 상호작용마다 리로딩
- **취약한 세션 상태**: streamlit_app.py에서 복잡한 상태 관리
- **부족한 에러 메시징**: 사용자에게 일반 에러 메시지
- **Async 복잡성**: 폴백이 있는 혼합 async/sync
- **파일 처리**: 파일 크기 제한 없음, 업로드 시 타입 검증 없음

### 6.9 설정 관리 문제
- **환경 파일 의존**: .env에 과도한 의존
- **설정 검증 없음**: 시작 시 필수 환경 변수 검증 없음
- **매직 넘버**: 코드 전체에 하드코딩된 임계값 분산
- **프로필 없음**: 개발/스테이징/프로덕션 설정 없음
- **약한 시크릿 관리**: .env가 git에 있을 수 있음 (.gitignore에서 가정)

### 6.10 문서화 문제
- **최소 문서**: modules/에 하나의 readme.md만
- **불명확한 목적**: 일부 함수의 의도 불분명
- **API 문서 없음**: FastAPI 엔드포인트 미문서화
- **아키텍처 문서 없음**: 시스템 아키텍처 문서화 없음
- **인라인 주석 부족**: 복잡한 로직 설명 주석 제한됨

---

## 7. 기술 스택 요약

| 컴포넌트 | 기술 | 목적 |
|----------|------|------|
| **서버** | FastAPI 0.115.9 | REST API 백엔드 |
| **웹 UI** | Streamlit | 챗 인터페이스 |
| **LLM** | Ollama | 로컬 LLM 추론 |
| **벡터 DB** | ChromaDB 1.3.5 | 벡터 임베딩 저장 |
| **SQL DB** | PostgreSQL | 트랜잭션 데이터 저장 |
| **태스크 스케줄링** | APScheduler | 백그라운드 작업 스케줄링 |
| **웹 서버** | Uvicorn | ASGI 애플리케이션 서버 |
| **검증** | Pydantic | 데이터 검증 및 파싱 |
| **HTTP 클라이언트** | Requests + httpx | 외부 API 호출 |
| **임베딩** | ONNX + tokenizers | 로컬 임베딩 생성 |
| **비동기** | asyncio | Async/await 지원 |
| **컨테이너화** | Docker + docker-compose | 서비스 오케스트레이션 |
| **프로세스 관리** | psutil | 프로세스 모니터링 |
| **설정** | python-dotenv + YAML | 환경 설정 |

---

## 8. 파일 통계

| 카테고리 | 파일 수 | 라인 수 | 예시 |
|----------|---------|---------|------|
| **설정/세팅** | 2 | 1,219 | settings.py, config.py |
| **데이터베이스** | 2 | 450 | postgre_handler.py, postgre_query.py |
| **벡터 DB** | 3 | 1,516 | chroma_rest_api.py, chorma_handler.py |
| **LLM 코어** | 4 | 2,187 | llm_core.py, llm_processor.py, llm_query_analyzer.py |
| **RAG** | 5 | 4,087 | data_retriever.py, llm_rag_analysis.py, llm_rag_training.py |
| **릴레이 제어** | 5 | 2,161 | relay/automatic.py, relay/data_access.py, relay/manual.py |
| **데이터 파이프라인** | 3 | 877 | dat_pgdb_to_json.py, dat_json_to_vcdb.py |
| **제어** | 3 | 463 | control_schema.py, control_prompts.py, relay_status.py |
| **패턴** | 2 | 212 | pattern_query.py, pattern_other.py |
| **유틸리티** | 5 | 1,184 | utils_date.py, location_manager.py, utils_text.py |
| **엔드포인트** | 2 | 2,476 | api.py (1636), streamlit_app.py (840) |
| **스케줄링** | 1 | 134 | scheduler.py |
| **로깅** | 1 | 92 | log_handler.py |
| **총계** | **47** | **17,458** | |

---

## 9. 결론

agri_ai_core는 다음을 갖춘 정교한 **스마트팜 AI 어시스턴트**입니다:
- PostgreSQL을 통한 **포괄적인 센서 모니터링**
- Ollama + RAG를 사용한 **고급 LLM 기반 분석**
- 안전 규칙이 있는 **자동 환경 제어**
- **이중 인터페이스** (REST API + Streamlit UI)
- 지속적 운영을 위한 **백그라운드 태스크 스케줄링**
- 패턴 학습 및 지식 저장을 위한 **벡터 데이터베이스**

그러나 코드베이스는 다음 개선이 필요합니다:
1. 결합도 감소 및 테스트 가능성 향상을 위한 **아키텍처 리팩토링**
2. API/UI와 비즈니스 로직 사이의 **서비스 레이어 추상화**
3. **포괄적인 테스트** 인프라
4. **더 나은 문서화** 및 인라인 주석
5. **설정 관리** 개선
6. 모듈 간 **에러 처리 표준화**

시스템은 기능하지만 엔터프라이즈 사용 프로덕션 준비 전에 이러한 개선이 필요합니다.
