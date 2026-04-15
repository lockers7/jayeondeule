# AgriAI Core RAG 파이프라인 상세 분석

> 갱신일: 2026-03-10
> 리팩토링: ChromaDB 컬렉션 10개 → 4개, PostgreSQL→ChromaDB 직접 복사 제거, 학습 상태 PostgreSQL 이관
> 추가: LLM Reranker, web_knowledge 캐싱, TTL 페널티, conversation VectorDB 저장, 3컬렉션 병렬 검색

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [센서/릴레이/생육 데이터 RAG (farm_knowledge)](#2-센서릴레이생육-데이터-rag-farm_knowledge)
3. [문서 RAG (document_collection)](#3-문서-rag-document_collection)
4. [대화 RAG (conversation_collection)](#4-대화-rag-conversation_collection)
5. [웹 검색 RAG (web_knowledge)](#5-웹-검색-rag-web_knowledge)
6. [임베딩 시스템](#6-임베딩-시스템)
7. [검색 통합 (LLM Tool Use)](#7-검색-통합-llm-tool-use)
8. [관련 파일 목록](#8-관련-파일-목록)

---

## 1. 시스템 개요

### 1.1 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           AgriAI Core RAG 시스템                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [데이터 소스]                    [처리/학습]                [저장소]            │
│                                                                              │
│  PostgreSQL ──────────────→ model_trainer.py ──────→ ChromaDB                │
│  (센서/릴레이/생육)          (분석+임베딩)              farm_knowledge         │
│                                                                              │
│  PostgreSQL ──────────────→ growth_rag_processor ──→ ChromaDB                │
│  (생육+센서통계+릴레이)      (스케줄러 자동학습)        farm_knowledge         │
│                                                                              │
│  문서 파일 (PDF/TXT) ─────→ document_processor.py ─→ ChromaDB                │
│                              + chunker.py              document_collection   │
│                              + document_enricher.py    + farm_knowledge      │
│                                                                              │
│  사용자-AI 대화 ──────────→ query_handler_simple.py ─→ PostgreSQL            │
│                              (비동기 VectorDB 저장)      ai_conversation     │
│                                                     → ChromaDB               │
│                                                       conversation_collection│
│                                                                              │
│  웹 검색 결과 ────────────→ tools_executor.py ─────→ ChromaDB                │
│  (SearXNG/Naver/Brave)      (백그라운드 캐싱)          web_knowledge         │
│                                                                              │
│  [학습 상태 관리]                                                              │
│  ai_learning_status ←─── loader.py (학습 시점 기록)                           │
│  ai_learning_pattern ←── data_analyzer.py (패턴 저장)                         │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 ChromaDB 컬렉션 구조 (4개)

| 컬렉션 | 환경변수 | 기본값 | 용도 |
|--------|---------|-------|------|
| `farm_knowledge` | `COLLECTION_FARM_KNOWLEDGE` | `farm_knowledge` | 센서/릴레이 학습 결과 + 생육 RAG + 문서 enrichment + 작물/병해충 청크 (벡터 유사 검색) |
| `document_collection` | `COLLECTION_DOCUMENT` | `document_collection` | 문서 RAG - 농작물, 병해충, 일반 문서 청크 (벡터 유사 검색) |
| `conversation_collection` | `COLLECTION_CONVERSATION` | `conversation_collection` | 대화 턴 저장 + 세션 요약 (관련 과거 대화 검색 + 오버플로우 요약) |
| `web_knowledge` | `COLLECTION_WEB_KNOWLEDGE` | `web_knowledge` | 웹 검색 결과 캐싱 (백그라운드 저장, search_farm_knowledge에서 검색) |

### 1.3 PostgreSQL 보조 테이블

| 테이블 | 용도 | 대체 대상 |
|--------|------|----------|
| `ai_conversation` (기존) | 원본 대화 이력 저장 | - |
| `ai_learning_status` (신규) | 학습 상태/job 실행 시간 기록 | ChromaDB `job_status_collection` |
| `ai_learning_pattern` (신규) | 자가학습 패턴 저장 | ChromaDB `self_learning` / `pattern_learned` |

### 1.4 임베딩 모델

| 항목 | 값 |
|------|---|
| 모델 | `bge-m3` (Ollama 기반) |
| 차원 | 1024 |
| 엔드포인트 | `http://127.0.0.1:11434/api/embed` |

---

## 2. 센서/릴레이/생육 데이터 RAG (farm_knowledge)

### 2.1 데이터 흐름 (model_trainer.py — 학습)

```
PostgreSQL (SENSOR_L_RECORDING + RELAY_L_RECORDING + FARMHOUSE_L_CROPS)
    │
    ▼
loader.py: get_unlearned_data()
    │  - ai_learning_status에서 마지막 학습 시점 조회
    │  - 그 이후 센서/릴레이/생육 데이터를 PostgreSQL에서 직접 조회
    │  - GET_UNLEARNED_UNITS_DATA, GET_UNLEARNED_CROPS_DATA 쿼리 사용
    ▼
model_trainer.py: update_ollama_model()
    │  - 농장-시간대별 데이터 분류 (farm_hour_data)
    │  - data_analyzer.py로 통계/최적 환경 분석
    │  - LLM(qwen3:32b)에 분석 결과 전달 → 학습 데이터 생성
    ▼
embedder.py: embed_text()
    │  - 학습 결과 텍스트 → bge-m3 임베딩 (1024차원)
    ▼
operations.py: upsert_collection_data()
    │  - farm_knowledge 컬렉션에 저장
    ▼
loader.py: update_learned_last_status()
    │  - PostgreSQL ai_learning_status에 학습 완료 시점 기록
    ▼
완료
```

### 2.2 데이터 흐름 (growth_rag_processor.py — 생육 RAG)

```
스케줄러 (12:00, 00:00 자동 실행)
    │
    ▼
growth_rag_processor.py: run_growth_rag()
    │  - _get_last_rag_datetime() → PostgreSQL ai_learning_status 조회 (기본: 7일 전)
    │  - _get_active_farm_houses() → 활성 농장-재배사 목록
    ▼
농장-재배사별 반복:
    ├─ _get_new_crop_entries() → 새 생육 입력 조회 (마지막 RAG 이후)
    │   └─ 생육 데이터 있음 → 생육 입력별 반복:
    │       ├─ _get_sensor_stats() → 센서 통계 (온도/습도/CO2/수온/광량)
    │       ├─ _get_relay_stats() → 릴레이 가동 비율 (8개 장치)
    │       ├─ _get_day_night_stats() → 주야간 분리 센서 통계
    │       ├─ _get_moving_averages() → 6시간 이동평균 (온도/습도 트렌드)
    │       │     └─ 트렌드 판정: 온도 ±1.0℃, 습도 ±3.0% 기준 → 상승/하강/안정
    │       ├─ _build_growth_context() → 생육 컨텍스트 (계절, 시간대, 재배일수, 생육단계, 병해충)
    │       ├─ _build_rag_document() → RAG 문서 텍스트 (환경+릴레이+트렌드+생육결과, ~1500-2000자)
    │       ├─ _build_rag_metadata() → 메타데이터 (anomaly_flag, quality_label, 등급1비율 등)
    │       └─ _store_growth_rag() → embed_text → ChromaDB(farm_knowledge)
    │             └─ doc_id: grag_{MD5해시[:16]}
    └─ 생육 데이터 없음 + 자정(00:00) 실행 → _ensure_daily_rag():
          ├─ 최근 24시간 센서/릴레이 통계 조회
          ├─ 가상 생육 entry 생성 (양호 추정)
          ├─ is_daily_guarantee: true 플래그
          └─ RAG 문서 + 메타데이터 → 임베딩 → farm_knowledge 저장
    ▼
_update_last_rag_datetime() → PostgreSQL ai_learning_status 갱신
```

### 2.3 데이터 수집 (PostgreSQL 직접 조회)

#### Units 데이터 (센서 + 릴레이)

**쿼리**: `GET_UNLEARNED_UNITS_DATA` (`queries.py`)

```sql
SELECT FMI.farm_id          AS farm_id,
       FMI.farm_name        AS farm_name,
       HMI.hous_id          AS house_id,
       HMI.hous_name        AS house_name,
       'units'              AS data_kind,
       TO_CHAR(SLR.recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS record_datetime,
       HMI.mnul_ctrl_flag   AS is_manual,
       -- 센서 8개
       indr_tprt_valu       AS indoor_temperature_value,
       indr_hmdt_valu       AS indoor_humidity_value,
       oudr_tprt_valu       AS outdoor_temperature_value,
       oudr_hmdt_valu       AS outdoor_humidity_value,
       co2_valu             AS co2_concentration_value,
       watr_tprt_valu       AS water_temperature_value,
       ligt_lvel_valu       AS light_level_value,
       watr_lvel_valu       AS water_level_value,
       -- 릴레이 12개
       relay_1st_flag,  relay_2st_flag,  relay_3st_flag,
       relay_5st_flag,  relay_6st_flag,  relay_7st_flag,
       relay_8st_flag,  relay_9st_flag,  relay_10st_flag,
       relay_11st_flag, relay_14st_flag, relay_15st_flag
  FROM FARM_M_INFO FMI
  JOIN FARMHOUSE_M_INFO HMI ...
  JOIN SENSOR_L_RECORDING SLR ...
  JOIN RELAY_L_RECORDING RLR ...
 WHERE FMI.farm_id != 0 AND HMI.hous_id != 99
   AND SLR.recd_dttm > %s   -- 마지막 학습 시점 이후
 ORDER BY SLR.recd_dttm ASC
 LIMIT %s;                   -- 기본 500건
```

**센서 필드 매핑** (`config.py` SENSOR_FIELD_MAPPING):

| 영문 키 | 한글명 | 단위 |
|---------|-------|------|
| `indoor_temperature_value` | 내부온도 | ℃ |
| `indoor_humidity_value` | 내부습도 | % |
| `outdoor_temperature_value` | 외부온도 | ℃ |
| `outdoor_humidity_value` | 외부습도 | % |
| `co2_concentration_value` | CO2 농도 | ppm |
| `water_temperature_value` | 수온 | ℃ |
| `light_level_value` | 광량 | - |
| `water_level_value` | 수위 | - |

**릴레이 필드 매핑** (`config.py` RELAY_FIELD_MAPPING):

| DB 컬럼 | 영문 키 | 한글명 | 기능 |
|---------|---------|-------|------|
| `relay_1st_flag` | `water_heater_flag` | 물가열기 | 수온 상승 |
| `relay_2st_flag` | `fog_occurs_flag` | 분사펌프 | 습도 상승 |
| `relay_3st_flag` | `drainage_motor_flag` | 배수밸브 | 수온 유지 |
| `relay_5st_flag` | `intake_fan_flag` | 흡기팬 | 외부 공기 흡입 |
| `relay_6st_flag` | `exhaust_fan_flag` | 배기팬 | 내부 공기 배출 |
| `relay_7st_flag` | `lighting_flag` | 조명토글 | 조명 ON/OFF |
| `relay_8st_flag` | `irrigation_flag` | 관수밸브 | 배지 관수 |
| `relay_9st_flag` | `indoor_heater_flag` | 열풍기 | 내부온도 상승 |
| `relay_10st_flag` | `air_circulation_valve_flag` | 순환댐퍼 | 내부공기 순환 |
| `relay_11st_flag` | `air_intake_valve_flag` | 흡기댐퍼 | 외부공기 흡입 밸브 |
| `relay_14st_flag` | `air_exhaust_valve_flag` | 배기댐퍼 | 내부공기 배출 밸브 |
| `relay_15st_flag` | `indoor_heater_valve_flag` | 열풍댐퍼 | 히터열기 배출 밸브 |

#### Crops 데이터 (생육 정보)

**쿼리**: `GET_UNLEARNED_CROPS_DATA` (`queries.py`)

| 영문 키 | 한글명 | 설명 |
|---------|-------|------|
| `growth_status` | 생육상태 | CODE_M_INFO 조인 결과 |
| `crop_kind` | 작물종류 | 예: 상황버섯 |
| `crop_lvel` | 생육단계 | 발아기/생육기/수확기/휴지기 |
| `total_yield` | 총수확량 | crop_qtty |
| `grade_1_yield` ~ `grade_5_yield` | 등급별 수량 | 1등급~5등급 |
| `grade_1_price` ~ `grade_5_price` | 등급별 가격 | 1등급~5등급 판매가 |
| `crop_strt_date` | 재배시작일 | - |
| `crop_end_date` | 재배종료일 | - |
| `alert` | 비고(rmks) | - |

### 2.4 학습 처리 과정 (model_trainer.py)

```
get_unlearned_data() 반환값 (dict 리스트)
    │
    ├─ data_kind == "units" 인 항목:
    │     └─ convert_sensor_relay_data(data) → sensor_data, relay_data 분리
    │        └─ unit_entry = {farm_id, house_id, record_datetime, hour_of_day,
    │                         sensor_value: {...}, relay_status: {...}}
    │
    ├─ data_kind == "crops" 인 항목:
    │     └─ crop_entry = {farm_id, house_id, record_datetime, hour_of_day,
    │                      crop_strt_date, crop_end_date, code_name,
    │                      crop_qtty, grade_1~5 수량/가격, grade_1_ratio}
    │
    ▼ farm_hour_data에 농장-시간대별 그룹핑
    │
    ├─ process_stats_and_optimal_data()  ← data_analyzer.py
    │    └─ 통계 집계 (10분 단위), 최적 환경 데이터 계산
    │    └─ ai_learning_status에 마지막 실행 시간 기록 (PostgreSQL)
    │
    ├─ process_farm_hour_data(farm_id, hour, data, hour_timestamp)
    │    └─ 농장-시간대별 학습 데이터 생성
    │    └─ LLM 분석: analyze_farm_optimal_conditions(), analyze_farm_time_patterns()
    │
    ▼ 학습 결과를 ChromaDB에 저장
```

### 2.5 ChromaDB 저장 구조 (farm_knowledge)

#### doc_id 생성 규칙

```python
# operations.py: generate_doc_id() — 학습 데이터
doc_id = f"{kind}:{farm_id}:{house_id}:{bucket_datetime}"
# 예시: "learned:1:0:2026-02-25 12:00:00"

# growth_rag_processor.py — 생육 RAG
doc_id = f"grag_{hashlib.md5(id_source.encode()).hexdigest()[:16]}"
# 예시: "grag_a1b2c3d4e5f67890"
```

**버킷팅 규칙** (학습 데이터 doc_id 시간 중복 방지):
- `units`/`crops`: 3분 단위 (`DATA_TRANSFER_MINUTES=3`)
- `stats`/`optimal`: 10분 단위 (`STATS_INTERVAL_MINUTES=10`)
- `learned`: 1시간 단위
- `grag_*`: 해시 기반 (충돌 가능성 최소)

#### metadata 필드 (학습 데이터)

```python
{
    "farm_id": "1",                           # 농장 ID
    "hour": 12,                               # 시간대
    "record_datetime": "2026-02-25 12:00:00", # 기록 시점
    "data_type": "learned_data",              # 데이터 유형
    "is_learned_flag": True                   # 학습 완료 플래그
}
```

#### metadata 필드 (생육 RAG)

```python
{
    "farm_id": "1",
    "house_id": "1",
    "record_datetime": "2026-03-10 12:00:00",
    "season": "봄",
    "crop_kind": "상황버섯",
    "growth_status": "생육기",
    "pest_type": "",
    "anomaly_flag": False,
    "quality_label": "우수",       # 우수/보통/개선필요
    "is_daily_guarantee": False,   # 일일 보장 RAG 여부
    "sensor_sample_count": 144,
    "avg_indoor_temp": 22.5,
    "avg_indoor_humidity": 75.0,
    "grade_1_ratio": 0.85,
}
```

### 2.6 학습 상태 관리 (PostgreSQL)

#### ai_learning_status 테이블

```sql
CREATE TABLE ai_learning_status (
    id           SERIAL PRIMARY KEY,
    status_key   VARCHAR(64) NOT NULL UNIQUE,
    status_value TEXT,
    updated_at   TIMESTAMP DEFAULT NOW()
);
```

**사용 패턴**:

| status_key | 기록 위치 | 용도 |
|-----------|----------|------|
| `last_learned_datetime` | `loader.py: update_learned_last_status()` | 마지막 학습 완료 시점 |
| `last_learned_datetime` | `data_analyzer.py: process_stats_and_optimal_data()` | 마지막 통계 실행 시점 |
| `last_growth_rag_datetime` | `growth_rag_processor.py: _update_last_rag_datetime()` | 마지막 생육 RAG 시점 |

```python
# 기록
UPSERT_AI_LEARNING_STATUS:
INSERT INTO ai_learning_status (status_key, status_value, updated_at)
VALUES (%s, %s, NOW())
ON CONFLICT (status_key) DO UPDATE SET status_value = EXCLUDED.status_value, updated_at = NOW()

# 조회
GET_AI_LEARNING_STATUS:
SELECT status_value, updated_at FROM ai_learning_status WHERE status_key = %s
```

---

## 3. 문서 RAG (document_collection)

### 3.1 데이터 흐름

```
문서 파일 (PDF/TXT) 또는 대화 메시지
    │
    ▼
document_processor.py: llm_document_process()
    │  - 문서 유형 감지 (detect_document_type)
    │  - 대화 메시지 → 텍스트 변환 (messages_to_text) [선택]
    ▼
chunker.py: store_document_with_chunks()
    │  - 문단 기반 → 문장 기반 → 크기 기반 3단계 청킹
    │  - 기존 동일 파일 청크 삭제 후 재저장 (중복 방지)
    │  - 각 청크별 embed_text() 호출
    ▼
operations.py: upsert_documents_with_embedding()
    │  - document_collection에 배치 저장
    ▼
+ 구조화 데이터 저장 (document_processor.py):
    │  - farm_knowledge_collection → structured_document (is_manual=True)
    │  - document_collection → 원문 일부(5000자) 저장
    ▼
+ 작물/병해충 문서 → farm_knowledge 이중 저장:
    │  - _store_crop_chunks_to_farm_knowledge(document_processor.py)
    │  - doc_id: fk_{doc_id_base}_{i}, data_kind: crop_document_chunk
    ▼
+ LLM enrichment (백그라운드 스레드):
    │  - _background_enrich(document_processor.py) → Thread
    │  - enrich_document(document_enricher.py):
    │      ├─ 요약 생성 (LLM 1회, timeout=180초, 300~500자)
    │      ├─ QA 쌍 생성 (LLM 1회, timeout=180초, 3~5쌍, 입력 최대 5000자)
    │      └─ 요약/QA 임베딩 → farm_knowledge 저장
    │            doc_id: summary_{file_name_base}, qa_{file_name_base}_{i}
    │            data_type: document_summary, document_qa
    │            is_llm_enriched: True
    ▼
완료
```

### 3.2 문서 유형 감지

```python
# document_processor.py: detect_document_type()
DOC_TYPE_LABELS = {
    "crop_info":    "작물 정보",    # 키워드: 상황버섯, 작약, 쇠무릎 등
    "disease_info": "병해충 정보",  # 키워드: 병해충, 병원균, 방제 등
    "general":      "일반 문서",    # 기타
}
```

### 3.3 청킹 방식 (chunker.py)

#### 3단계 청킹 알고리즘

**1단계: 문단 기반 분할**
- `\n\n` 구분자로 문단 분리
- 현재 청크 + 새 문단 ≤ `chunk_size`(1000자) → 합침
- 초과 시 현재 청크 확정 후 새 청크 시작

**2단계: 긴 문단 문장 분할**
- 문단이 `chunk_size` 초과 시 문장 단위 분할
- 한국어 문장 종결 정규식: `(?<=[다요죠까지음임함됨렵])[.]\s+|(?<=[?!])\s+|(?<=\.)\s+`
- 영문: 마침표/물음표/느낌표 기준

**3단계: 크기 기반 폴백**
- 청크가 3개 미만이면 고정 크기 분할
- `chunk_size=1000`, `chunk_overlap=200`
- 간격: `chunk_size - chunk_overlap = 800`

#### 설정값

| 항목 | 기본값 | 환경변수 |
|------|-------|---------|
| chunk_size | 1000 | - |
| chunk_overlap | 200 | - |

### 3.4 ChromaDB 저장 구조 (document_collection)

#### doc_id

```python
doc_id = f"{file_name.replace('.', '_')}_{chunk_index}"
# 예: "manual_pdf_0", "manual_pdf_1", "manual_pdf_2"
```

#### metadata 필드

```python
{
    "file_name": "manual.pdf",           # 원본 파일명
    "chunk_id": 0,                        # 청크 인덱스 (0부터)
    "total_chunks": 15,                   # 전체 청크 수
    "data_kind": "document_chunk",        # 데이터 종류
    "is_learned_flag": False,             # 학습 플래그
    "record_datetime": "2026-02-25 12:30:00"  # 저장 시점
}
```

#### 중복 방지 로직

```python
# 동일 파일명의 기존 청크를 모두 조회
existing = get_documents(
    collection_name=document_collection(),
    where={"file_name": {"$eq": file_name}}
)
# 기존 청크 ID 모두 삭제 후 새 청크 저장
```

### 3.5 검색 방식

`search_farm_knowledge()` (tools_executor.py)에서 3개 컬렉션 병렬 검색 (7.2절 참조):

```python
{
    "label": "document",
    "name": document_collection(),
    "where": None,                    # 전사 검색 (필터 없음)
    "max_distance": 22.0              # DOC_VECTOR_MAX_DISTANCE 환경변수
}
```

- file_name 파라미터 지정 시 → document_collection 단독 검색 (Reranker 바이패스)
- WHERE 조건 없이 전체 문서에서 유사도 검색
- distance > 22.0인 결과는 제외

---

## 4. 대화 RAG (conversation_collection)

### 4.1 대화 턴 실시간 저장 (구현 완료)

```
사용자 메시지 + AI 응답
    │
    ├─ [동기] PostgreSQL ai_conversation 저장
    │     └─ add_turn(conversation_store.py)
    │
    └─ [비동기] VectorDB conversation_collection 저장
          └─ _async_vectordb_save(query_handler_simple.py) → Thread:
                ├─ 인사/잡담 필터 (10자 미만+인사패턴 → 스킵)
                ├─ 결합 텍스트: "질문: {user_query}\n답변: {response[:500]}"
                ├─ embed_text() → bge-m3 임베딩
                ├─ upsert → conversation_collection
                │     doc_id: conv_turn_{MD5해시[:16]}
                │     metadata: {farm_id, session_id, data_kind: "conversation_turn",
                │                record_datetime, query_preview}
                └─ _prune_old_conversations: farm_id당 최대 30건 유지
```

### 4.2 대화 요약 저장 (오버플로우 처리)

```
대화 턴이 MAX_TURNS 초과 시:
    │
    ▼
conversation_store.py: _store_summary_to_vectordb()
    │  - LLM으로 3문장 이내 핵심 요약 생성
    │  - 요약 텍스트 임베딩
    ▼
conversation_collection (ChromaDB)
    doc_id: conv_summary_{MD5해시[:16]}
    metadata: {session_id, data_kind: "conversation_summary",
               record_datetime, summary_length}
```

### 4.3 관련 과거 대화 검색 (질의 시 참조)

```
사용자 새 질문
    │
    ▼
_search_related_conversations(query_handler_simple.py)
    │  - embed_text(user_query) → 임베딩 생성
    │  - query_documents(conversation_collection)
    │      where: {farm_id, data_kind: "conversation_turn"}
    │      n_results: 5 (HYBRID_RELATED_RESULTS)
    │  - 거리 임계값: 16.0 (CONV_VECTOR_MAX_DISTANCE) 초과 제외
    │  - 질문만 추출 (과거 답변 제외 → LLM 복사 방지)
    ▼
시스템 프롬프트에 "[관련 과거 대화 주제]" 삽입 (참고만, 도구 우선)
```

#### ai_conversation 테이블 구조

```sql
CREATE TABLE ai_conversation (
    id         SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,    -- 사용자 세션 ID
    role       VARCHAR(16) NOT NULL,    -- "user" 또는 "assistant"
    content    TEXT NOT NULL,           -- 메시지 내용
    farm_id    VARCHAR(32),            -- 농장 ID (선택)
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ai_conv_session ON ai_conversation(session_id);
CREATE INDEX idx_ai_conv_created ON ai_conversation(created_at);
```

#### 대화 조회

```python
store.get_history(session_id)
# → 최근 MAX_TURNS * 2개 메시지 반환 (기본 20개 = 10턴)
# → 시간순 정렬 (오래된 것부터)
```

| 설정 | 기본값 | 환경변수 |
|------|-------|---------|
| max_turns | 10 | `CONVERSATION_MAX_TURNS` |
| ttl_days | 7 | `CONVERSATION_TTL_DAYS` |
| 인메모리 TTL | 30분 | `MEMORY_TTL_SECONDS` |

### 4.4 대화 메시지 → 텍스트 변환 (document_processor.py)

```python
messages_to_text(messages, farm_name, house_name)
```

변환 결과:
```
[농장: 자연들에, 재배사: 1동]
[대화 시간: 2026-02-25 10:30:00]

[사용자] 지금 온도가 너무 높은데 어떻게 하면 좋을까요?
[AI] 현재 내부온도가 28℃로 높은 편입니다. 배기팬을 가동하여 환기를 권장합니다.

[사용자] 배기팬은 언제까지 켜두면 되나요?
[AI] 목표 온도 22-24℃에 도달할 때까지 약 30분간 가동하시면 됩니다.
```

---

## 5. 웹 검색 RAG (web_knowledge)

### 5.1 웹 검색 제공자

| 우선순위 | 제공자 | 환경변수 | 특징 |
|---------|-------|---------|------|
| 1 | SearXNG | `SEARXNG_URL` | 자체 호스팅, API 키 불필요, Google/Naver/Daum/DuckDuckGo/Bing 5개 엔진 통합 |
| 2 | Naver | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 한국어 검색 최적, 블로그+웹 |
| 3 | Brave | `BRAVE_SEARCH_API_KEY` | 글로벌 검색 |
| 4 | MCP | MCP web-search | 최종 fallback |

### 5.2 검색 결과 구조

```python
# tools_executor.py: search_web()
{
    "success": True,
    "query": "상황버섯 재배 온도",
    "results": [
        {
            "title": "상황버섯 재배 최적 온도",
            "url": "https://example.com/article",
            "description": "상황버섯 재배 시 적정 온도는 22-26℃...",
            "source": "naver_blog",
            "page_content": "본문 텍스트..."  # URL 자동 fetch 결과
        },
        ...
    ],
    "search_provider": "searxng",
    "auto_fetched_content": [...]  # URL 자동 fetch 결과 (최대 3개)
}
```

### 5.3 web_knowledge 캐싱 (구현 완료)

```
웹 검색 실행 완료
    │
    ▼
_cache_web_results_to_vectordb(tools_executor.py) → 백그라운드 Thread
    │  - 검색 결과 상위 5개 처리
    │  - URL 해시: hashlib.md5(url).hexdigest()[:12]
    │  - 임베딩 대상: "{title} {description} {page_content[:500]}"
    │  - doc_id: web_{url_hash} (중복 자동 방지)
    ▼
web_knowledge (ChromaDB)
    metadata: {
        url, title, description, query,
        data_kind: "web_knowledge",
        record_datetime
    }
    ▼
search_farm_knowledge에서 3번째 컬렉션으로 검색 (max_distance=20.0)
```

---

## 6. 임베딩 시스템

### 6.1 임베딩 생성 (embedder.py)

```python
embed_text(text, timeout=60, max_retries=5)
```

#### 처리 과정

1. **LRU 캐시 확인** (최대 256개 항목, OrderedDict 기반)
2. **Ollama 헬스 체크** (`/api/version`, `/api/tags`)
3. **임베딩 요청** (`POST /api/embed`)
   - 동적 타임아웃: `30 + (text_length // 100)초` (최대 180초)
4. **재시도**: 최대 5회, 지수 백오프 (5초 → 10초 → 20초 → 30초)
5. **폴백**: 더미 임베딩 (MD5 해시 시드 기반 정규 분포 벡터)

#### 더미 임베딩

```python
# 텍스트의 MD5 해시를 시드로 사용 → 동일 텍스트는 동일 더미 벡터 생성
seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % (2**31)
rng = np.random.RandomState(seed)
dummy = rng.randn(1024).tolist()
norm = sum(x**2 for x in dummy) ** 0.5
return [x / norm for x in dummy]  # L2 정규화
```

### 6.2 메타데이터 직렬화 (chroma/utils.py)

ChromaDB는 문자열/숫자/불린만 메타데이터로 허용. 복잡 타입 처리:

| 입력 타입 | 처리 방식 | 예시 |
|----------|----------|------|
| str, int, float, bool | 그대로 저장 | `"farm_id": "1"` |
| dict, list, set | JSON 직렬화 + `_is_json` 플래그 | `"relay_stats": "{...}", "relay_stats_is_json": true` |
| Decimal | int/float 변환 | `Decimal("22.5")` → `22.5` |
| datetime | 문자열 변환 | `"2026-02-25 12:30:00"` |
| None | 빈 문자열 | `""` |

---

## 7. 검색 통합 (LLM Tool Use)

### 7.1 search_farm_knowledge() (tools_executor.py)

LLM이 `search_farm_knowledge` 도구를 호출하면 실행되는 통합 검색 함수:

```python
search_farm_knowledge(
    query: str,          # 검색 쿼리
    n_results: int = 3,  # 반환 건수
    file_name: str = None, # 파일명 필터 (해당 파일 청크만)
    farm_id: str = None, # 농장 필터
    house_id: str = None # 재배사 필터
)
```

### 7.2 검색 전략

#### 3개 컬렉션 병렬 검색

```python
collection_plans = [
    {
        "label": "document",
        "name": document_collection(),     # 문서 RAG
        "where": None,                     # 필터 없음 (전사 검색)
        "max_distance": 22.0               # DOC_VECTOR_MAX_DISTANCE
    },
    {
        "label": "farm_knowledge",
        "name": farm_knowledge_collection(), # 센서/릴레이/생육 학습
        "where": {"farm_id": farm_id},       # 농장 필터
        "max_distance": 24.0                 # SOURCE_VECTOR_MAX_DISTANCE
    },
    {
        "label": "web_knowledge",
        "name": web_knowledge_collection(),  # 웹 검색 캐시
        "where": None,                      # 전역 검색
        "max_distance": 20.0                # WEB_VECTOR_MAX_DISTANCE
    }
]
```

#### WHERE 조건 유연 처리

farm_id/house_id가 주어지면 **문자열 + 숫자 양쪽 모두 시도**:

```python
source_where_candidates = [
    {"farm_id": "1", "house_id": "1"},   # 문자열 버전
    {"farm_id": 1,   "house_id": 1}      # 숫자 버전
]
```

- 각 후보 조건마다 별도 검색 플랜 생성
- ChromaDB의 `$eq` 연산자로 필터링

#### file_name 검색 (특수 경로)

- file_name 파라미터 지정 시 → document_collection만 검색
- Reranker 바이패스 (distance 기반 상위 결과 직접 반환)

#### 검색 건수

```python
per_collection_count = max(6, n_results * 3)
# n_results=3 → 각 컬렉션에서 9건 조회 → 필터링 후 최종 3건 반환
```

### 7.3 결과 처리

1. **거리 필터링**: `distance > max_distance`인 항목 제외
2. **TTL 페널티**: farm_knowledge의 90일 초과 데이터에 distance 가산
   - `penalty = ((age_days - 90) / 10) * 0.5`
   - 예: 100일=+0.5, 120일=+1.5
3. **거리 순 정렬**: distance 오름차순 (None은 마지막)
4. **중복 제거**: `(doc_id, record_datetime, content[:120])` 조합 기반
5. **LLM Reranker**: rerank_results(reranker.py)
   - 1-10점 관련성 채점 (LLM 호출, timeout=30초)
   - 4점 미만 제외 (RERANK_MIN_SCORE)
   - 최대 10건 후보 (RERANK_MAX_CANDIDATES)
   - 1회 재시도 (temperature 0→0.3 상향)
   - 실패 시 거리 기반 폴백
6. **최종 반환**: 상위 `n_results`개

#### 반환 구조

```python
{
    "success": True,
    "query": "상황버섯 적정 온도",
    "count": 3,
    "data_retrieved_at": "2026-03-10 14:30",
    "results": [
        {
            "content": "검색된 문서 텍스트 (최대 700자)",
            "metadata": {
                "farm_id": "1",
                "record_datetime": "2026-02-25 12:00:00",
                ...
            },
            "distance": 12.34,
            "collection": "document"  # 또는 "farm_knowledge", "web_knowledge"
        },
        ...
    ]
}
```

---

## 8. 관련 파일 목록

### 핵심 RAG 파일

| 파일 | 역할 |
|------|------|
| `agri_ai_core/src/ai/rag/embedder.py` | 텍스트 → 벡터 임베딩 생성 (bge-m3) |
| `agri_ai_core/src/ai/rag/chunker.py` | 문서 청킹 (3단계 알고리즘) |
| `agri_ai_core/src/ai/rag/document_processor.py` | 문서 처리 파이프라인 (유형 감지 → 청킹 → 저장 → enrichment) |
| `agri_ai_core/src/ai/rag/document_enricher.py` | 문서 요약/QA 생성 (LLM enrichment, 백그라운드) |
| `agri_ai_core/src/ai/rag/reranker.py` | LLM 기반 검색 결과 Reranker (1-10점 채점) |

### 학습 파일

| 파일 | 역할 |
|------|------|
| `agri_ai_core/src/ai/learning/model_trainer.py` | LLM 학습 메인 루프 (데이터 수집 → 분석 → 저장) |
| `agri_ai_core/src/ai/learning/data_analyzer.py` | 통계 집계, 최적 환경 분석, 시간 패턴 추출 |
| `agri_ai_core/src/ai/learning/growth_rag_processor.py` | 생육 RAG (스케줄러 자동학습, 일일 보장 RAG) |

### ChromaDB 파일

| 파일 | 역할 |
|------|------|
| `agri_ai_core/src/chroma/collections.py` | 4개 컬렉션명 관리 함수 |
| `agri_ai_core/src/chroma/loader.py` | 데이터 로더 (PostgreSQL → 학습 데이터 조회, 학습 상태 관리) |
| `agri_ai_core/src/chroma/operations.py` | ChromaDB CRUD (upsert, query, get, delete) |
| `agri_ai_core/src/chroma/client.py` | ChromaDB HTTP 클라이언트, 컬렉션 생성/관리 |
| `agri_ai_core/src/chroma/config.py` | ChromaDB 연결 설정, `_COLLECTION_ID_MAP` |
| `agri_ai_core/src/chroma/utils.py` | 메타데이터 직렬화, 임베딩 차원 관리 |

### LLM 처리 파일

| 파일 | 역할 |
|------|------|
| `agri_ai_core/src/ai/llm_client.py` | LLM 통신 핵심 (Tool Use 루프, 도구 결과 정제, 후처리, 가짜URL 제거) |
| `agri_ai_core/src/ai/tools_definition.py` | 도구 정의 5개 + 시스템 프롬프트 생성 |
| `agri_ai_core/src/ai/tools_executor.py` | 도구 실행 (검색, 웹검색, URL fetch, 릴레이 제어, web_knowledge 캐싱) |
| `agri_ai_core/src/ai/query_handler_simple.py` | 질의 핸들러 (복합질문 분리, 하이브리드 컨텍스트, 대화 저장) |
| `agri_ai_core/src/ai/conversation_store.py` | 대화 히스토리 관리 (PostgreSQL + VectorDB 요약) |

### 설정/쿼리 파일

| 파일 | 역할 |
|------|------|
| `agri_ai_core/config.py` | SENSOR_FIELD_MAPPING, RELAY_FIELD_MAPPING, 임베딩/청킹 설정 |
| `agri_ai_core/src/postgresql/queries.py` | SQL 쿼리 (GET_UNLEARNED_UNITS/CROPS_DATA, UPSERT_AI_LEARNING_STATUS) |
| `.env` | 환경변수 (컬렉션명, 모델명, API 키 등) |


## 함수명/파일명 매핑

### A. 문서 업로드 RAG
파일 업로드(WEB: FileUpload.jsx)
  → rag_perform(app.py)
    → process_attached_files(document_processor.py)
        └─ llm_document_process(document_processor.py):
            ├─ [1단계] 문서 읽기
            │     ├─ read_pdf_file(file_processor.py) → PyPDF2
            │     └─ open() (텍스트 파일)
            ├─ [2단계] detect_document_type(document_processor.py)
            ├─ [3단계] store_document_with_chunks(chunker.py):
            │     ├─ chunk_document(chunker.py) → 문단/크기 기반 분할
            │     ├─ get_documents(operations.py) → 기존 청크 조회 (중복 방지)
            │     ├─ delete_document(operations.py) → 기존 청크 삭제
            │     ├─ embed_text(embedder.py) → Ollama 임베딩 모델
            │     └─ upsert_documents_with_embedding(operations.py) → ChromaDB(document)
            ├─ [4단계] upsert_collection_data(operations.py) → ChromaDB(farm_knowledge + document)
            ├─ [5단계] _store_crop_chunks_to_farm_knowledge(document_processor.py):
            │     ├─ chunk_document(chunker.py)
            │     ├─ embed_text(embedder.py)
            │     └─ upsert_documents_with_embedding(operations.py) → ChromaDB(farm_knowledge)
            └─ [6단계] _background_enrich(document_processor.py) → 스레드:
                  └─ enrich_document(document_enricher.py):
                      ├─ _generate_summary(document_enricher.py) → _call_llm() → Ollama
                      ├─ _generate_qa_pairs(document_enricher.py) → _call_llm() → Ollama
                      │     └─ _parse_qa_response(document_enricher.py)
                      └─ _store_enriched_data(document_enricher.py):
                            ├─ embed_text(embedder.py)
                            └─ upsert_documents_with_embedding(operations.py) → ChromaDB(farm_knowledge)

### B. 대화 저장 RAG
대화 저장 버튼(WEB: ChatInput.jsx)
  → rag_save(app.py)
    → messages_to_text(document_processor.py) → 대화→텍스트 변환
    → llm_document_process(document_processor.py) → (위 A의 동일 파이프라인)
    → format_rag_save_result(document_processor.py) → 결과 포맷팅

### C. 생육 RAG
스케줄러(scheduler.py)
  → run_growth_rag(growth_rag_processor.py):
      ├─ _get_last_rag_datetime(growth_rag_processor.py) → db_session(connection.py) → PostgreSQL
      ├─ _get_active_farm_houses(growth_rag_processor.py) → db_session(connection.py) → PostgreSQL
      └─ 농장-재배사별:
          ├─ _get_new_crop_entries(growth_rag_processor.py) → PostgreSQL
          │   └─ 생육 입력별:
          │       ├─ _get_sensor_stats(growth_rag_processor.py) → PostgreSQL
          │       ├─ _get_relay_stats(growth_rag_processor.py) → PostgreSQL
          │       ├─ _get_day_night_stats(growth_rag_processor.py) → PostgreSQL
          │       ├─ _get_moving_averages(growth_rag_processor.py) → PostgreSQL
          │       ├─ _build_growth_context(growth_rag_processor.py)
          │       ├─ _build_rag_document(growth_rag_processor.py)
          │       ├─ _build_rag_metadata(growth_rag_processor.py)
          │       └─ _store_growth_rag(growth_rag_processor.py):
          │             ├─ embed_text(embedder.py) → Ollama 임베딩 모델
          │             └─ upsert_documents_with_embedding(operations.py) → ChromaDB(farm_knowledge)
          └─ _ensure_daily_rag(growth_rag_processor.py):
                ├─ _check_today_crops(growth_rag_processor.py) → PostgreSQL
                ├─ _get_sensor_stats / _get_relay_stats / _get_day_night_stats / _get_moving_averages → PostgreSQL
                ├─ _build_growth_context / _build_rag_document / _build_rag_metadata
                └─ _store_growth_rag → embed_text → ChromaDB(farm_knowledge)
