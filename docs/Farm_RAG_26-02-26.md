# 스마트팜 RAG 시스템 분석 (2026-02-26)

## 1. 시스템 아키텍처 개요

```
┌──────────────────────────────────────────────────────────┐
│                   PostgreSQL (원본 데이터)                  │
│  SENSOR_L_RECORDING / RELAY_L_RECORDING / FARMHOUSE_L_CROPS │
└───────┬──────────────────────┬──────────────────┬────────┘
        │                      │                  │
        v                      v                  v
┌──────────────┐  ┌───────────────────┐  ┌──────────────────┐
│ 실시간 조회    │  │ 시간별 학습         │  │  생육 RAG          │
│ (LLM 도구)    │  │ (스케줄러 02:00)   │  │  (12:00 / 00:05)  │
│ tools_executor│  │ model_trainer     │  │ growth_rag_proc   │
└───────┬──────┘  └────────┬──────────┘  └────────┬─────────┘
        │                  │                       │
        │           ┌──────v──────────────────────v────────┐
        │           │        embed_text() (Ollama)          │
        │           │        임베딩 모델 → 1024차원 벡터       │
        │           └──────────────┬────────────────────────┘
        │                         │
        │           ┌─────────────v─────────────────────────┐
        │           │       ChromaDB (4개 컬렉션)              │
        │           │  farm_knowledge / document_collection   │
        │           │  conversation / web_knowledge           │
        │           └─────────────┬─────────────────────────┘
        │                         │
        v                         v
┌─────────────────────────────────────────────────────────┐
│  LLM (qwen3:32b) — 도구 결과 + RAG 검색 결과 종합 응답    │
└─────────────────────────────────────────────────────────┘
```

---

## 2. ChromaDB 컬렉션 구성

| 컬렉션 | 환경변수 | 용도 | 데이터 타입 |
|--------|---------|------|------------|
| **farm_knowledge** | `COLLECTION_FARM_KNOWLEDGE` | 센서/릴레이 학습 + 최적 조건 + 생육 RAG | `learned_data`, `growth_rag`, `structured_document` |
| **document_collection** | `COLLECTION_DOCUMENT` | 업로드 문서 청크 (PDF, TXT, MD, CSV, JSON) | `document_chunk` |
| **conversation** | `COLLECTION_CONVERSATION` | 대화 요약 RAG | conversation |
| **web_knowledge** | `COLLECTION_WEB_KNOWLEDGE` | 웹 검색 결과 캐시 | web |

- **임베딩 모델**: Ollama 기반 (`EMBEDDING_MODEL_NAME`)
- **임베딩 차원**: 1024 (`CHROMA_EMBEDDING_DIM`)
- **캐시**: SHA256 LRU 캐시 256개, 입력 최대 4000자
- **폴백**: Ollama 실패 시 MD5 기반 더미 임베딩 생성

---

## 3. 생육정보 RAG

### 3.1 트리거

| 시간 | 함수 | 동작 |
|------|------|------|
| 12:00 | `run_growth_rag(is_midnight=False)` | 새 생육 입력 기반 RAG 생성 |
| 00:05 | `run_growth_rag(is_midnight=True)` | 당일 미입력 시 일일 보장 RAG 생성 |

### 3.2 데이터 수집 (PostgreSQL)

**파일**: `agri_ai_core/src/ai/learning/growth_rag_processor.py`

| 함수 | DB 테이블 | 수집 내용 |
|------|----------|----------|
| `_get_active_farm_houses()` | `FARM_M_INFO` + `FARMHOUSE_M_INFO` | 활성 농장-재배사 목록 |
| `_get_new_crop_entries()` | `FARMHOUSE_L_CROPS` | 마지막 RAG 이후 생육 입력 |
| `_get_sensor_stats()` | `SENSOR_L_RECORDING` | 센서 통계 (평균/표준편차/최소/최대) |
| `_get_relay_stats()` | `RELAY_L_RECORDING` | 릴레이 가동 비율 (ON시간/전체시간) |
| `_get_day_night_stats()` | `SENSOR_L_RECORDING` | 주간(6-17시)/야간 분리 센서 통계 |
| `_get_moving_averages()` | `SENSOR_L_RECORDING` | 이동평균 트렌드 (72샘플 윈도우) |

### 3.3 센서 통계 쿼리 (GET_SENSOR_STATS_IN_RANGE)

```sql
SELECT COUNT(*)                                   AS sample_count
     , ROUND(AVG(indr_tprt_valu)::numeric, 2)    AS avg_indoor_temp
     , ROUND(STDDEV(indr_tprt_valu)::numeric, 2) AS std_indoor_temp
     , ROUND(MIN(indr_tprt_valu)::numeric, 2)    AS min_indoor_temp
     , ROUND(MAX(indr_tprt_valu)::numeric, 2)    AS max_indoor_temp
     , ROUND(AVG(indr_hmdt_valu)::numeric, 2)    AS avg_indoor_humidity
     , ROUND(AVG(co2_valu)::numeric, 2)          AS avg_co2
     , ROUND(AVG(watr_tprt_valu)::numeric, 2)    AS avg_water_temp
     , ROUND(AVG(ligt_lvel_valu)::numeric, 2)    AS avg_light_level
  FROM SENSOR_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
   AND recd_dttm > %s AND recd_dttm <= %s
```

### 3.4 릴레이 통계 쿼리 (GET_RELAY_STATS_IN_RANGE)

```sql
SELECT COUNT(*)                                                            AS sample_count
     , ROUND(AVG(CASE WHEN relay_1st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS heater_ratio
     , ROUND(AVG(CASE WHEN relay_2st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS misting_ratio
     , ROUND(AVG(CASE WHEN relay_6st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS exhaust_fan_ratio
     , ROUND(AVG(CASE WHEN relay_7st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS lighting_ratio
     , ROUND(AVG(CASE WHEN relay_8st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS irrigation_ratio
  FROM RELAY_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
   AND recd_dttm > %s AND recd_dttm <= %s
```

### 3.5 RAG 문서 생성 (_build_rag_document)

생성되는 텍스트 형식:

```
[생육 RAG] 2026-02-26 자연들에 농장 상황버섯1호재배사
계절: 겨울 | 생육단계: 생육 | 재배 45일차 | 오후 14시
생육상태: 양호 | 작물: 상황버섯 | 제어: 자동

[환경 통계 (2026-02-20 ~ 2026-02-26, 센서 1440건)]
- 실내온도: 평균 21.5°C (주간 23.2°C / 야간 18.9°C), 표준편차 2.1, 범위 16.5~28.3
- 실내습도: 평균 65.3% (주간 58.2% / 야간 72.1%), 표준편차 12.4
- CO2: 평균 520ppm, 표준편차 85.2, 범위 380~680
- 수온: 평균 18.5°C, 범위 16.2~20.1
- 광량: 평균 450 (주간 680 / 야간 50)

[릴레이 가동 비율]
- 물가열기: 12.5% | 분사펌프: 35.2% | 배기팬: 45.3% | 조명: 80.0% | 관수: 25.6%
- 열풍기: 8.5% | 순환댐퍼: 15.2% | 흡기댐퍼: 22.3% | 배기댐퍼: 38.4%

[이동평균 트렌드 (6시간 윈도우)]
- 온도: 상승 추세 (20.1→21.5°C)
- 습도: 안정 (64.2~65.8%)

[생육 결과]
- 총 수확량: 450kg | 1등급: 315kg(70.0%) | 2등급: 105kg | 3등급: 30kg
- 관찰: 잎 색상 진녹, 잎 22개, 줄기 높이 85cm, 열매 42개, 병해충 없음
- 비고: 정상 생육 중
```

### 3.6 메타데이터 구조 (_build_rag_metadata)

```json
{
  "farm_id": "1",
  "house_id": "1",
  "data_type": "growth_rag",
  "record_datetime": "2026-02-26 14:30:00",
  "season": "겨울",
  "month": 2,
  "crop_level": "생육",
  "days_since_start": 45,
  "crop_kind": "상황버섯",
  "growth_status": "양호",
  "pest_type": "없음",
  "anomaly_flag": "normal",
  "quality_label": "우수",
  "sensor_sample_count": 1440,
  "avg_indoor_temp": 21.5,
  "avg_indoor_humidity": 65.3,
  "avg_co2": 520.0,
  "grade_1_ratio": 0.700,
  "total_yield": 450.0,
  "is_daily_guarantee": false
}
```

### 3.7 저장 (_store_growth_rag)

```python
doc_id = f"grag_{hashlib.md5(id_source.encode()).hexdigest()[:16]}"
embedding = embed_text(document)  # Ollama 임베딩
upsert_documents_with_embedding(
    collection_name=farm_knowledge_collection(),
    docs=[{"doc_id": doc_id, "text": document, "metadata": metadata, "embedding": embedding}]
)
```

### 3.8 일일 보장 RAG (_ensure_daily_rag)

자정(00:05) 실행 시 당일 생육 입력이 없으면:
- 최근 24시간 센서/릴레이 통계 수집
- 가상 생육 엔트리 생성 (growth_status: "양호(추정)")
- `is_daily_guarantee: true` 플래그로 구분하여 저장
- 데이터 연속성 보장 목적

### 3.9 처리 흐름도

```
스케줄러 (12:00 / 00:05)
  ↓
run_growth_rag()
  ├─ _get_last_rag_datetime() → ai_learning_status 테이블
  ├─ _get_active_farm_houses() → 활성 농장-재배사 목록
  │
  ├─ [각 농장-재배사 반복]
  │   ├─ _get_new_crop_entries() → 새 생육 입력
  │   │
  │   ├─ [입력 있음] → 각 생육 기록별
  │   │   ├─ _get_sensor_stats()     → 센서 통계
  │   │   ├─ _get_relay_stats()      → 릴레이 가동 비율
  │   │   ├─ _get_day_night_stats()  → 주야간 분리 통계
  │   │   ├─ _get_moving_averages()  → 이동평균 트렌드
  │   │   ├─ _build_growth_context() → 계절/재배일수/시간대
  │   │   ├─ _build_rag_document()   → RAG 텍스트 생성
  │   │   ├─ _build_rag_metadata()   → 메타데이터 생성
  │   │   └─ _store_growth_rag()     → ChromaDB farm_knowledge 저장
  │   │
  │   └─ [입력 없음 + 자정]
  │       └─ _ensure_daily_rag()     → 일일 보장 RAG 생성
  │
  └─ _update_last_rag_datetime()     → 처리 시점 갱신
```

---

## 4. 센서 데이터 RAG

### 4.1 실시간 조회 (LLM 도구)

**파일**: `agri_ai_core/src/ai/tools_executor.py`

**함수**: `get_farm_realtime_data(house_id, farm_id, data_type)`

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `house_id` | str (선택) | 재배사 ID, 미지정 시 자동 선택 |
| `farm_id` | str (선택) | 농장 ID |
| `data_type` | str | `"sensor"`, `"relay"`, `"all"` (기본) |

**센서 조회 쿼리** (GET_NOW_UNIT_INFO):

```sql
SELECT TO_CHAR(recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS record_datetime,
       indr_tprt_valu AS indoor_temperature,
       indr_hmdt_valu AS indoor_humidity,
       oudr_tprt_valu AS outdoor_temperature,
       oudr_hmdt_valu AS outdoor_humidity,
       co2_valu AS co2,
       watr_tprt_valu AS water_temperature,
       ligt_lvel_valu AS light_level,
       watr_lvel_valu AS water_level
  FROM SENSOR_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
 ORDER BY recd_dttm DESC LIMIT 1
```

**반환 형식**:

```json
{
  "success": true,
  "farm_id": "1",
  "house_id": "1",
  "timestamp": "2026-02-26T14:30:00",
  "data_retrieved_at": "2026-02-26 14:30",
  "auto_selected": false,
  "sensor": {
    "record_datetime": "2026-02-26 14:29:45",
    "indoor_temperature": 22.5,
    "indoor_humidity": 68.3,
    "outdoor_temperature": 5.2,
    "outdoor_humidity": 45.1,
    "co2": 520,
    "water_temperature": 18.5,
    "light_level": 450,
    "water_level": 75
  },
  "relay": { "relay_1": true, "relay_2": false, ... }
}
```

### 4.2 시간별 학습 (model_trainer)

**파일**: `agri_ai_core/src/ai/learning/model_trainer.py`

**스케줄**: 매일 02:00 (`update_ollama_model()`)

**프로세스**:

```
get_unlearned_data()
  ↓ 미학습 센서/릴레이/작물 데이터 조회
  ↓
process_farm_hour_data(farm_id, hour, data)
  ├─ analyze_farm_optimal_conditions(data) → 최적 환경 분석
  │   ├─ analyze_temperature_conditions()  → 주야간 온도
  │   ├─ analyze_humidity_conditions()     → 습도
  │   ├─ analyze_co2_conditions()          → CO2
  │   ├─ analyze_water_temperature_conditions() → 수온
  │   └─ analyze_light_level_conditions()  → 광량
  ├─ analyze_farm_time_patterns(data, hour) → 시간별 패턴
  │   └─ analyze_relay_data_for_time_patterns() → 릴레이 패턴
  ↓
upsert_collection_data(farm_knowledge_collection(), ...)
  → data_type: "learned_data"
```

### 4.3 최적 환경 분석 결과 (data_analyzer)

**파일**: `agri_ai_core/src/ai/learning/data_analyzer.py`

```json
{
  "temperature": {
    "day":   {"min": 18.5, "max": 25.3, "optimal": 21.5},
    "night": {"min": 15.2, "max": 18.8, "optimal": 17.2}
  },
  "humidity": {
    "day":   {"min": 55.0, "max": 70.5, "optimal": 62.3},
    "night": {"min": 70.0, "max": 85.2, "optimal": 77.5}
  },
  "co2":               {"min": 400, "max": 600, "optimal": 520},
  "water_temperature":  {"min": 16.5, "max": 20.2, "optimal": 18.5},
  "light_level":        {"min": 300, "max": 800, "optimal": 600}
}
```

---

## 5. 릴레이 셋팅 RAG

### 5.1 실시간 릴레이 조회

**쿼리** (GET_LATEST_RELAY_INFO):

```sql
SELECT relay_1st_flag, relay_2st_flag, ..., relay_16st_flag
  FROM RELAY_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
 ORDER BY recd_dttm DESC LIMIT 1
```

16개 릴레이 상태 (ON/OFF):

| 릴레이 | 장비 |
|--------|------|
| relay_1 | 물가열기 (히터) |
| relay_2 | 분사펌프 (미스팅) |
| relay_6 | 배기팬 |
| relay_7 | 조명 |
| relay_8 | 관수 |
| 기타 | 열풍기, 순환댐퍼, 흡기댐퍼, 배기댐퍼 등 |

### 5.2 릴레이 가동 비율 분석

**파일**: `agri_ai_core/src/ai/learning/data_analyzer.py` (라인 456-474)

```python
def analyze_relay_data_for_time_patterns(time_patterns, hour_units, current_hour):
    """시간대별 릴레이 가동 비율 계산"""
    # ON 시간 / 전체 시간 = 가동 비율 (0.0 ~ 1.0)
```

### 5.3 생육 RAG 문서 내 릴레이 표현

```
[릴레이 가동 비율]
- 물가열기: 35.2% | 분사펌프: 18.5% | 배기팬: 42.1% | 조명: 0% | 관수: 12.3%
- 열풍기: 8.2% | 순환댐퍼: 15.1% | 흡기댐퍼: 22.3% | 배기댐퍼: 28.5%
```

---

## 6. RAG 검색 (search_farm_knowledge)

**파일**: `agri_ai_core/src/ai/tools_executor.py` (라인 346-661)

### 6.1 3단계 하이브리드 검색

```
[1단계] 벡터 유사도 검색 (3개 컬렉션 동시)
  ├─ document_collection  (max_distance: 22.0)
  ├─ farm_knowledge       (max_distance: 24.0, farm_id/house_id 필터)
  └─ web_knowledge        (max_distance: 20.0)
     ↓
[2단계] FTS 키워드 보완 검색
  ├─ 한국어 명사 2글자 이상 추출
  ├─ where_document: {"$contains": keyword}
  └─ RRF(Reciprocal Rank Fusion)로 병합
     ↓
[3단계] LLM Reranking
  └─ 상위 후보 → LLM 관련성 점수(1-10) → 재정렬
```

### 6.2 거리 필터링 및 TTL 페널티

```python
# 거리 기반 필터
if dist > plan["max_distance"]:
    continue  # 관련 없는 결과 제외

# TTL 페널티: 90일 이상 오래된 farm_knowledge 데이터
if age_days > 90:
    penalty = ((age_days - 90) / 10) * 0.5
    dist += penalty  # 오래된 데이터 순위 하락
```

### 6.3 반환 형식

```json
{
  "success": true,
  "query": "상황버섯 최적 온도는?",
  "count": 3,
  "data_retrieved_at": "2026-02-26 14:30",
  "results": [
    {
      "content": "[생육 RAG] 2026-02-20 ...",
      "metadata": {"farm_id": "1", "season": "겨울", "avg_indoor_temp": 21.5, ...},
      "distance": 0.123,
      "collection": "farm_knowledge"
    }
  ]
}
```

---

## 7. 문서 업로드 RAG

### 7.1 지원 파일 형식

| 확장자 | 처리 함수 | 저장 컬렉션 |
|--------|----------|------------|
| .txt, .md | `read_text_file()` | document_collection |
| .csv | `read_csv_file()` | document_collection |
| .json | 텍스트 읽기 | document_collection |
| .pdf | `read_pdf_file()` (PyPDF2) | document_collection |
| .xlsx | `read_excel_file()` | document_collection |

### 7.2 청킹 전략 (chunker.py)

```
문서 → 문단 분할 (우선)
     → 큰 문단은 문장 분할 (한국어 종결어미 + 마침표 기준)
     → 3개 미만이면 크기 기반 폴백 (1000자, 200자 오버랩)
```

### 7.3 저장 프로세스

```
llm_document_process()
  ├─ 문서 읽기 (PDF → read_pdf_file(), 기타 → UTF-8 텍스트)
  ├─ 문서 유형 감지 (crop_info / disease_info / general)
  ├─ store_document_with_chunks() → document_collection
  │   ├─ chunk_document() → 청크 분할
  │   ├─ 각 청크별 embed_text() → 임베딩 생성
  │   └─ upsert_documents_with_embedding() → ChromaDB 저장
  └─ upsert_collection_data() → farm_knowledge (구조화 메타데이터)
```

---

## 8. LLM 도구 사용 규칙

**파일**: `agri_ai_core/src/ai/tools_definition.py`

### 도구 목록 (4개)

| 도구 | 용도 |
|------|------|
| `get_farm_realtime_data` | 실시간 센서/릴레이 데이터 조회 (PostgreSQL) |
| `search_farm_knowledge` | VectorDB 지식 검색 (ChromaDB 하이브리드 검색) |
| `search_web` | 외부 웹 검색 (SearXNG) |
| `fetch_url_content` | URL 본문 읽기 |

### 사용 규칙

1. 농장/센서/릴레이 질문 → `get_farm_realtime_data` + `search_farm_knowledge` **모두** 사용
2. 사실 정보 (좌표, 가격 등) → `search_farm_knowledge` 필수, 추측 금지
3. 일반 정보 → `search_web` 사용
4. 인사/감정 → 도구 없이 응답 가능
5. **센서 수치, 릴레이 상태를 도구 없이 추측하여 답변 절대 금지**

---

## 9. 스케줄러 작업 요약

| 작업 | 시간 | 함수 | 데이터 흐름 |
|------|------|------|------------|
| 학습 | 매일 02:00 | `update_ollama_model()` | PostgreSQL → 분석 → farm_knowledge |
| 생육 RAG (정오) | 매일 12:00 | `run_growth_rag()` | 생육+센서+릴레이 → farm_knowledge |
| 생육 RAG (자정) | 매일 00:05 | `run_growth_rag(is_midnight=True)` | 일일 보장 RAG → farm_knowledge |
| 릴레이 제어 | 1분마다 | 릴레이 제어 함수 | 센서 → 판단 → 릴레이 명령 |
| 통계 처리 | 10분마다 | stats 함수 | 센서 통계 집계 |
| 청크 정리 | 매일 03:00 | 정리 함수 | 180일 이상 청크 삭제 |
| 로그 정리 | 매일 00:00 | 정리 함수 | 100일 이전 로그 삭제 |

---

## 10. 주요 파일 경로

| 카테고리 | 파일 | 핵심 함수 |
|---------|------|----------|
| **생육 RAG** | `src/ai/learning/growth_rag_processor.py` | `run_growth_rag()`, `_build_rag_document()` |
| **센서 분석** | `src/ai/learning/data_analyzer.py` | `analyze_farm_optimal_conditions()` |
| **학습 파이프라인** | `src/ai/learning/model_trainer.py` | `update_ollama_model()`, `process_farm_hour_data()` |
| **LLM 도구 실행** | `src/ai/tools_executor.py` | `get_farm_realtime_data()`, `search_farm_knowledge()` |
| **LLM 도구 정의** | `src/ai/tools_definition.py` | `get_available_tools()`, `get_system_prompt_with_tools()` |
| **임베딩** | `src/ai/rag/embedder.py` | `embed_text()` |
| **청킹** | `src/ai/rag/chunker.py` | `chunk_document()`, `store_document_with_chunks()` |
| **문서 처리** | `src/ai/rag/document_processor.py` | `llm_document_process()`, `process_attached_files()` |
| **Reranking** | `src/ai/rag/reranker.py` | `rerank_results()` |
| **ChromaDB 연결** | `src/chroma/client.py` | `get_collection()`, `heartbeat()` |
| **ChromaDB 컬렉션** | `src/chroma/collections.py` | `farm_knowledge_collection()` 등 |
| **ChromaDB 작업** | `src/chroma/operations.py` | `upsert_documents_with_embedding()`, `query_documents()` |
| **데이터 적재** | `src/chroma/loader.py` | `get_unlearned_data()`, `search_similar_data()` |
| **DB 쿼리** | `src/postgresql/queries.py` | SQL 쿼리 상수 정의 |
| **스케줄러** | `src/control/task_scheduler.py` | `setup_default_jobs()` |
| **초기화** | `startup.py` | `init_app()` |

> 모든 파일 경로는 `agri_ai_core/` 기준 상대 경로입니다.
