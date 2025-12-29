# PostgreSQL → ChromaDB 데이터 파이프라인 문서

**작성일**: 2025-12-04
**버전**: 1.0
**작성자**: AgriAI Core 시스템 분석

---

## 목차

1. [개요](#1-개요)
2. [전체 처리 흐름](#2-전체-처리-흐름)
3. [단계별 상세 처리 절차](#3-단계별-상세-처리-절차)
4. [모듈 및 함수 매핑](#4-모듈-및-함수-매핑)
5. [데이터 변환 과정](#5-데이터-변환-과정)
6. [개선 필요 사항](#6-개선-필요-사항)
7. [실행 방법](#7-실행-방법)

---

## 1. 개요

### 1.1 목적
PostgreSQL에 저장된 스마트팜 센서 데이터와 작물 생육 데이터를 ChromaDB 벡터 데이터베이스로 변환하여 AI/ML 학습 및 검색에 활용할 수 있도록 한다.

### 1.2 주요 데이터 유형
- **Units 데이터**: 센서 데이터 (온도, 습도, CO2, 수온, 광량 등) 및 릴레이 상태 (히터, 환기팬, 조명 등)
- **Crops 데이터**: 작물 생육 데이터 (수확량, 등급별 수량/가격, 생육 상태 등)

### 1.3 처리 방식
1. PostgreSQL에서 데이터 읽기
2. JSON 파일로 중간 저장
3. JSON 데이터를 처리하여 ChromaDB에 저장

---

## 2. 전체 처리 흐름

```
┌─────────────────┐
│   PostgreSQL    │
│  (농장 DB)      │
└────────┬────────┘
         │ ① read_farm_house_list()
         │ ② read_units_data()
         │ ③ read_crops_data()
         ▼
┌─────────────────┐
│  JSON 파일       │
│ (중간 캐시)      │
└────────┬────────┘
         │ ④ fetch_data_from_json()
         │ ⑤ process_unit_data()
         │ ⑥ process_crop_data()
         ▼
┌─────────────────┐
│   ChromaDB      │
│ (벡터 DB)        │
└─────────────────┘
```

### 처리 흐름 설명

**Phase 1: PostgreSQL → JSON**
- 농장/재배사 목록 조회
- Units/Crops 데이터 조회
- JSON 파일로 저장

**Phase 2: JSON → ChromaDB**
- JSON 파일 로드
- 데이터 전처리 및 집계
- 벡터 임베딩 생성
- ChromaDB 저장

---

## 3. 단계별 상세 처리 절차

### Phase 1: PostgreSQL → JSON (데이터 추출)

#### Step 1-1: 농장/재배사 목록 조회
```python
# 함수: read_farm_house_list()
# 모듈: agri_ai_core/data_ingestion/postgres_reader.py

1. db_session() 컨텍스트 매니저로 DB 연결
2. GET_FARM_HOUSE_LIST 쿼리 실행
3. 모든 농장-재배사 조합 반환
```

**SQL 쿼리**: `GET_FARM_HOUSE_LIST`
```sql
SELECT DISTINCT
    FMI.farm_id, FMI.farm_name,
    HMI.hous_id, HMI.hous_name,
    HMI.mnul_ctrl_flag
FROM FARM_M_INFO FMI
JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
WHERE FMI.farm_id != 0 AND HMI.hous_id != 99
ORDER BY 1, 3
```

#### Step 1-2: Units 데이터 조회
```python
# 함수: read_units_data(farm_id, house_id)
# 모듈: agri_ai_core/data_ingestion/postgres_reader.py

각 농장/재배사에 대해:
1. GET_UNITS_VALUE 쿼리 실행
2. 센서 데이터 + 릴레이 데이터 조인
3. last_get_dttm 이후 데이터만 조회
4. 딕셔너리 리스트로 반환
```

**SQL 쿼리**: `GET_UNITS_VALUE`
```sql
SELECT
    FMI.farm_id, FMI.farm_name,
    HMI.hous_id, HMI.hous_name,
    TO_CHAR(SLR.recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS 기록일시,
    HMI.mnul_ctrl_flag AS 동작모드,
    indr_tprt_valu AS 내부온도,
    indr_hmdt_valu AS 내부습도,
    oudr_tprt_valu AS 외부온도,
    oudr_hmdt_valu AS 외부습도,
    co2_valu AS co2,
    watr_tprt_valu AS 수온,
    ligt_lvel_valu AS 광량,
    watr_lvel_valu AS 수위,
    relay_1st_flag AS 수온히터,
    relay_2st_flag AS 습도모터,
    -- ... (16개 릴레이)
FROM FARM_M_INFO FMI
JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
JOIN SENSOR_L_RECORDING SLR ON SLR.farm_id = HMI.farm_id AND SLR.hous_id = HMI.hous_id
JOIN RELAY_L_RECORDING RLR ON RLR.farm_id = SLR.farm_id AND RLR.hous_id = SLR.hous_id
    AND RLR.recd_dttm = SLR.recd_dttm
WHERE FMI.farm_id = %s AND HMI.hous_id = %s
    AND SLR.recd_dttm >= HMI.last_get_dttm
ORDER BY SLR.recd_dttm ASC
```

#### Step 1-3: Crops 데이터 조회
```python
# 함수: read_crops_data(farm_id, house_id)
# 모듈: agri_ai_core/data_ingestion/postgres_reader.py

각 농장/재배사에 대해:
1. GET_CROPS_VALUE 쿼리 실행
2. 작물 생육 데이터 조회
3. last_get_dttm 이후 데이터만 조회
4. 딕셔너리 리스트로 반환
```

**SQL 쿼리**: `GET_CROPS_VALUE`
```sql
SELECT
    FMI.farm_id, FMI.farm_name,
    HMI.hous_id, HMI.hous_name,
    TO_CHAR(recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS 기록일시,
    crop_strt_date AS 재배시작일,
    crop_end_date AS 재배종료일,
    code_name AS 생육상태,
    crop_qtty AS 총수확량,
    crop_grde_qtty_1 AS 등급1,
    crop_grde_qtty_2 AS 등급2,
    crop_grde_qtty_3 AS 등급3,
    crop_grde_qtty_4 AS 등급4,
    crop_grde_qtty_5 AS 등급5,
    crop_grde_amut_1 AS 등급1판매가격,
    -- ... (등급별 가격)
FROM FARM_M_INFO FMI
JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
JOIN FARMHOUSE_L_CROPS HLC ON HLC.farm_id = HMI.farm_id AND HLC.hous_id = HMI.hous_id
JOIN CODE_M_INFO CMI ON CMI.code_id = 'crop_stat' AND CMI.code_item = HLC.crop_stat
WHERE FMI.farm_id = %s AND HMI.hous_id = %s
    AND HLC.recd_dttm >= HMI.last_get_dttm
ORDER BY HLC.recd_dttm ASC
```

#### Step 1-4: JSON 파일 저장
```python
# 함수: run_data_export()
# 모듈: agri_ai_core/data_ingestion/json_exporter.py

1. 모든 농장/재배사 목록 순회
2. 각 농장에 대해 Units + Crops 데이터 수집
3. JSON 구조로 포맷팅:
   {
     "farm_id": "1",
     "farm_name": "자연들에 농장",
     "house_id": "1",
     "house_name": "상황버섯1호재배사",
     "units": [...],
     "crops": [...],
     "create_datetime": "2025-12-04 23:00:00"
   }
4. JSON 파일 저장 (settings.house_source_json 경로)
5. 각 재배사의 last_get_dttm 업데이트
```

**저장 경로**: `settings.vector.vector_cache` + `settings.house_source_json`
**기본값**: `./FarmUnits/v3/farm_unit_info.json`

---

### Phase 2: JSON → ChromaDB (데이터 변환 및 저장)

#### Step 2-1: JSON 파일 로드
```python
# 함수: fetch_data_from_json(limit=100000)
# 모듈: agri_ai_core/data_pipeline/json_loader.py

1. JSON 파일 경로 확인
2. UTF-8 인코딩으로 파일 읽기 (실패 시 CP949 시도)
3. JSON 파싱
4. limit 적용 (필요시)
5. 데이터 목록 반환
```

#### Step 2-2: Units 데이터 처리 및 집계
```python
# 함수: process_unit_data(item)
# 모듈: agri_ai_core/data_pipeline/data_processor.py

1. Units 데이터를 pandas DataFrame으로 변환
2. 기록일시를 datetime으로 파싱
3. 3분 단위로 시간 정렬 (align_to_3min)
   - 예: 10:01 → 10:03, 10:04 → 10:06
4. 3분 그룹별로 집계:
   a. 센서 데이터 평균 계산
   b. 릴레이 상태 다수결 투표
5. 메타데이터 생성
6. 문서 텍스트 생성
7. doc_id 생성: "units_{farm_id}_{house_id}_{timestamp}"
8. ChromaDB 저장 (upsert_collection_data)
```

**센서 데이터 집계 로직**:
```python
# 3분 시간 버킷 정렬
def align_to_3min(dt):
    m = dt.minute
    slot = ((m - 1) // 3 + 1) * 3 if m != 0 else 0
    if slot > 57:
        dt += timedelta(hours=1)
        slot = 0
    return dt.replace(minute=slot, second=0, microsecond=0)

# 센서 평균 계산
sensor_averages = {
    k: round(sensor_sums[k] / sensor_counts[k], 2)
    if sensor_counts[k] > 0 else 0.0
    for k in SENSOR_MAPPING.values()
}

# 릴레이 다수결
relay_majority = {}
for kr_key, en_key in RELAY_MAPPING.items():
    flags = group[kr_key].map(parse_boolean)
    flag_counts = Counter(flags)
    relay_majority[en_key] = flag_counts.most_common(1)[0][0]
```

**저장되는 메타데이터 구조**:
```json
{
  "farm_id": "1",
  "farm_name": "자연들에 농장",
  "house_id": "1",
  "house_name": "상황버섯1호재배사",
  "data_kind": "units",
  "record_datetime": "2025-12-04 10:03:00",
  "indoor_temperature_value": 18.5,
  "indoor_humidity_value": 75.2,
  "outdoor_temperature_value": 12.3,
  "outdoor_humidity_value": 65.8,
  "co2_concentration_value": 450.0,
  "water_temperature_value": 20.1,
  "light_level_value": 1200.0,
  "water_level_value": 80.0,
  "water_heater_flag": true,
  "humidity_motor_flag": false,
  "drainage_valve_flag": false,
  "suction_motor_flag": true,
  "exhaust_motor_flag": false,
  "lighting_flag": true,
  "irrigation_flag": false,
  "indoor_heater_flag": false,
  "circulation_valve_flag": true,
  "suction_valve_flag": false,
  "exhaust_valve_flag": false,
  "heater_valve_flag": true,
  "is_learned_flag": false
}
```

**저장되는 문서 텍스트**:
```
농장코드: 1, 농장명: 자연들에 농장, 재배사코드: 1, 재배사명: 상황버섯1호재배사,
장치데이터: units, 기록일시: 2025-12-04 10:03:00,
indoor_temperature_value: 18.5, indoor_humidity_value: 75.2,
outdoor_temperature_value: 12.3, outdoor_humidity_value: 65.8,
co2_concentration_value: 450.0, water_temperature_value: 20.1,
light_level_value: 1200.0, water_level_value: 80.0,
수온히터: 작동중(True), 습도모터: 미작동(False), 배수밸브: 미작동(False),
흡입모터: 작동중(True), 배출모터: 미작동(False), 조명토글: 작동중(True),
관수토글: 미작동(False), 내부히터: 미작동(False), 순환밸브: 작동중(True),
흡입밸브: 미작동(False), 배출밸브: 미작동(False), 히터밸브: 작동중(True),
학습여부: False
```

#### Step 2-3: Crops 데이터 처리
```python
# 함수: process_crop_data(item)
# 모듈: agri_ai_core/data_pipeline/data_processor.py

1. Crops 데이터 순회
2. 각 작물 데이터에 대해:
   a. 메타데이터 생성
   b. 등급별 수익 계산 (수량 × 가격)
   c. 총 수익 계산
   d. 1등급 비율 계산
3. 문서 텍스트 생성
4. doc_id 생성: "crops_{farm_id}_{house_id}_{timestamp}"
5. ChromaDB 저장 (upsert_collection_data)
```

**저장되는 메타데이터 구조**:
```json
{
  "farm_id": "1",
  "farm_name": "자연들에 농장",
  "house_id": "1",
  "house_name": "상황버섯1호재배사",
  "data_kind": "crops",
  "record_datetime": "2025-12-04 10:00:00",
  "crop_strt_date": "2025-10-01",
  "crop_end_date": "2025-12-04",
  "growth_status": "수확기",
  "total_yield": 250.5,
  "grade_1_yield": 150.0,
  "grade_2_yield": 70.0,
  "grade_3_yield": 20.0,
  "grade_4_yield": 8.0,
  "grade_5_yield": 2.5,
  "grade_1_price": 15000,
  "grade_2_price": 12000,
  "grade_3_price": 9000,
  "grade_4_price": 6000,
  "grade_5_price": 3000,
  "grade_1_revenue": 2250000,
  "grade_2_revenue": 840000,
  "grade_3_revenue": 180000,
  "grade_4_revenue": 48000,
  "grade_5_revenue": 7500,
  "total_revenue": 3325500,
  "grade_1_ratio": 0.5988,
  "alert": "",
  "is_learned_flag": false
}
```

#### Step 2-4: ChromaDB 저장
```python
# 함수: upsert_collection_data(calledby, collection, doc_id, document, metadata)
# 모듈: agri_ai_core/database/chromadb/operations.py

1. 컬렉션 ID 조회
2. 기존 문서 존재 여부 확인 (doc_id로)
3. 기존 문서가 있으면 삭제
4. 새 문서 추가:
   a. 메타데이터를 ChromaDB 호환 형식으로 변환
   b. 임베딩 생성 (또는 제로 벡터 사용)
   c. REST API로 ChromaDB에 저장
5. 결과 반환 ("added", "updated", "failed")
```

**ChromaDB REST API 호출**:
```http
POST {CHROMA_API_BASE}/collections/{collection_id}/add
Content-Type: application/json

{
  "ids": ["units_1_1_2025-12-04 10:03:00"],
  "documents": ["농장코드: 1, 농장명: ..."],
  "metadatas": [{...}],
  "embeddings": [[0.0, 0.0, ..., 0.0]]
}
```

---

## 4. 모듈 및 함수 매핑

### 4.1 데이터 읽기 모듈

#### `agri_ai_core/data_ingestion/postgres_reader.py`

| 함수명 | 용도 | 호출되는 SQL 쿼리 | 반환값 |
|--------|------|-------------------|--------|
| `read_farm_house_list()` | 모든 농장-재배사 목록 조회 | GET_FARM_HOUSE_LIST | list[dict] |
| `read_units_data(farm_id, house_id)` | Units 데이터 조회 | GET_UNITS_VALUE | list[dict] |
| `read_crops_data(farm_id, house_id)` | Crops 데이터 조회 | GET_CROPS_VALUE | list[dict] |
| `read_farm_info()` | 농장 상세 정보 조회 | GET_FARM_INFO_LIST | list[dict] |
| `read_optimal_condition(farm_id, house_id)` | 최적 조건 조회 | GET_OPTIMAL_CONDITION | dict |
| `read_current_sensor_info(farm_id, house_id)` | 현재 센서 정보 조회 | GET_NOW_UNIT_INFO | dict |
| `read_latest_relay_info(farm_id, house_id)` | 최신 릴레이 정보 조회 | GET_LATEST_RELAY_INFO | dict |
| `read_sensor_history(farm_id, house_id, days, limit)` | 센서 히스토리 조회 | GET_SENSOR_HISTORY | list[dict] |
| `read_light_irrigation_settings(farm_id, house_id, unit_type)` | 조명/관수 설정 조회 | GET_LIGHT_IRRIGATION | list[dict] |
| `update_last_get_time(farm_id, house_id, get_time)` | 조회 시간 업데이트 | SET_FARMHOUSE_INFO | bool |

#### `agri_ai_core/database/postgres/connection.py`

| 클래스/함수 | 용도 |
|------------|------|
| `DatabaseHandler` | PostgreSQL 연결 관리 (싱글톤) |
| `db_session()` | 컨텍스트 매니저 (connection 제공) |
| `db.connect()` | DB 연결 생성 |
| `db.fetch_all(query, vals)` | 복수 레코드 조회 |
| `db.fetch_one(query, vals)` | 단일 레코드 조회 |
| `db.execute_query(query, vals)` | CUD 쿼리 실행 |

#### `agri_ai_core/database/postgres/queries.py`

SQL 쿼리 문자열 상수 정의

### 4.2 JSON 처리 모듈

#### `agri_ai_core/data_ingestion/json_exporter.py`

| 함수명 | 용도 | 호출 함수 |
|--------|------|-----------|
| `run_data_export()` | PostgreSQL → JSON 전체 프로세스 | `read_farm_house_list()`, `read_units_data()`, `read_crops_data()`, `update_last_get_time()` |
| `export_units_to_json(farm_id, house_id, output_path)` | Units 데이터 JSON 내보내기 | `read_units_data()` |
| `export_crops_to_json(farm_id, house_id, output_path)` | Crops 데이터 JSON 내보내기 | `read_crops_data()` |
| `get_training_json_path()` | 학습용 JSON 경로 반환 | - |
| `get_units_json_path()` | Units JSON 경로 반환 | - |
| `get_crops_json_path()` | Crops JSON 경로 반환 | - |
| `get_json_cache_dir()` | JSON 캐시 디렉토리 경로 반환 | - |

#### `agri_ai_core/data_pipeline/json_loader.py`

| 함수명 | 용도 | 호출 함수 |
|--------|------|-----------|
| `json_to_vcdb(data_limit)` | JSON → ChromaDB 전체 프로세스 | `fetch_data_from_json()`, `process_unit_data()`, `process_crop_data()` |
| `fetch_data_from_json(limit)` | JSON 파일 읽기 | - |
| `get_training_json_path()` | 학습용 JSON 경로 반환 | - |
| `get_units_json_path()` | Units JSON 경로 반환 | - |
| `get_crops_json_path()` | Crops JSON 경로 반환 | - |
| `safe_float(value)` | 안전한 float 변환 | - |

### 4.3 데이터 처리 모듈

#### `agri_ai_core/data_pipeline/data_processor.py`

| 함수명 | 용도 | 호출 함수 |
|--------|------|-----------|
| `process_unit_data(item)` | Units 데이터 집계 및 저장 | `generate_doc_id()`, `upsert_collection_data()` |
| `process_crop_data(item)` | Crops 데이터 처리 및 저장 | `generate_doc_id()`, `upsert_collection_data()` |
| `safe_float(value)` | 안전한 float 변환 | - |

### 4.4 ChromaDB 작업 모듈

#### `agri_ai_core/database/chromadb/operations.py`

| 함수명 | 용도 | 호출 API |
|--------|------|----------|
| `generate_doc_id(kind, farm_id, house_id, timestamp)` | 문서 ID 생성 | - |
| `add_document(collection_name, doc_id, text, metadata, embedding)` | 단일 문서 추가 | POST /collections/{id}/add |
| `get_documents(collection_name, ids, where, limit, ...)` | 문서 조회 | POST /collections/{id}/get |
| `delete_document(collection_name, ids)` | 문서 삭제 | POST /collections/{id}/delete |
| `upsert_collection_data(calledby, collection, doc_id, document, metadata)` | 문서 업서트 | `add_document()`, `delete_document()` |
| `upsert_documents_with_embedding(collection_name, docs)` | 복수 문서 업서트 | POST /collections/{id}/upsert |
| `query_documents(collection_name, query_embeddings, n_results, where, ...)` | 벡터 검색 | POST /collections/{id}/query |
| `prepare_metadata_for_chroma(metadata)` | 메타데이터 포맷 변환 | - |
| `restore_metadata_from_chroma(metadata)` | 메타데이터 복원 | - |
| `_sanitize_for_json(value)` | JSON 직렬화 가능 형태로 변환 | - |

#### `agri_ai_core/database/chromadb/client.py`

| 함수명 | 용도 |
|--------|------|
| `heartbeat()` | ChromaDB 연결 확인 |
| `get_collection(name)` | 컬렉션 정보 조회 |
| `get_collection_id_from_name(name)` | 컬렉션 ID 조회 |
| `ensure_collections()` | 필수 컬렉션 생성 확인 |

### 4.5 ChromaDB 데이터 로더 모듈

#### `agri_ai_core/data_pipeline/chroma_loader.py`

| 함수명 | 용도 | 호출 함수 |
|--------|------|-----------|
| `get_unlearned_data(after_date, top_cnt)` | 학습되지 않은 신규 데이터 조회 | `get_documents()` |
| `get_learned_data(after_date, hour)` | 기존 학습된 데이터 조회 | `get_documents()` |
| `search_similar_data(query_text, farm_id, hour, top_count, date_range)` | 유사 데이터 검색 | `query_documents()`, `embed_text()` |
| `update_learned_source_data(datas)` | 학습 플래그 업데이트 | `generate_doc_id()`, `upsert_collection_data()` |
| `update_learned_last_status()` | 학습 완료 시간 저장 | `upsert_collection_data()` |
| `generate_document_text(meta)` | 문서 텍스트 생성 | - |
| `clean_metadata(metadata)` | 메타데이터 정리 | - |

### 4.6 공통 유틸리티 모듈

#### `agri_ai_core/shared_modules/common/mappers.py`

| 상수명 | 용도 |
|--------|------|
| `SENSOR_MAPPING` | 한글 센서명 → 영문 필드명 매핑 |
| `RELAY_MAPPING` | 한글 릴레이명 → 영문 필드명 매핑 |
| `RELAY_FIELD_MAPPING` | 릴레이 필드명 → [한글명, 설명] 매핑 |

#### `agri_ai_core/shared_modules/common/validators.py`

| 함수명 | 용도 |
|--------|------|
| `clean_sensor_value(value)` | 센서 값 정제 (None, NaN, 문자열 처리) |
| `parse_boolean(value)` | 불린 값 파싱 (1/0, true/false, T/F 등) |

#### `agri_ai_core/shared_modules/common/constants.py`

| 함수명 | 용도 |
|--------|------|
| `source_collection()` | 소스 컬렉션명 반환 |
| `learned_collection()` | 학습 컬렉션명 반환 |
| `job_status_collection()` | 작업 상태 컬렉션명 반환 |

---

## 5. 데이터 변환 과정

### 5.1 센서 데이터 매핑

**PostgreSQL 컬럼 → ChromaDB 메타데이터**

| PostgreSQL 컬럼 | 한글명 | ChromaDB 필드 | 설명 |
|----------------|--------|---------------|------|
| `indr_tprt_valu` | 내부온도 | `indoor_temperature_value` | 섭씨 온도 (°C) |
| `indr_hmdt_valu` | 내부습도 | `indoor_humidity_value` | 상대습도 (%) |
| `oudr_tprt_valu` | 외부온도 | `outdoor_temperature_value` | 섭씨 온도 (°C) |
| `oudr_hmdt_valu` | 외부습도 | `outdoor_humidity_value` | 상대습도 (%) |
| `co2_valu` | CO2 | `co2_concentration_value` | CO2 농도 (ppm) |
| `watr_tprt_valu` | 수온 | `water_temperature_value` | 섭씨 온도 (°C) |
| `ligt_lvel_valu` | 광량 | `light_level_value` | 광도 (lux) |
| `watr_lvel_valu` | 수위 | `water_level_value` | 수위 (%) |

### 5.2 릴레이 데이터 매핑

**PostgreSQL 컬럼 → ChromaDB 메타데이터**

| PostgreSQL 컬럼 | 한글명 | ChromaDB 필드 | 제어 장치 |
|----------------|--------|---------------|----------|
| `relay_1st_flag` | 수온히터 | `water_heater_flag` | 수온 히터 |
| `relay_2st_flag` | 습도모터 | `humidity_motor_flag` | 습도 제어 모터 |
| `relay_3st_flag` | 배수밸브 | `drainage_valve_flag` | 배수 밸브 |
| `relay_5st_flag` | 흡입모터 | `suction_motor_flag` | 흡입 팬 모터 |
| `relay_6st_flag` | 배출모터 | `exhaust_motor_flag` | 배출 팬 모터 |
| `relay_7st_flag` | 조명토글 | `lighting_flag` | 조명 ON/OFF |
| `relay_8st_flag` | 관수토글 | `irrigation_flag` | 관수 ON/OFF |
| `relay_9st_flag` | 내부히터 | `indoor_heater_flag` | 내부 난방 히터 |
| `relay_10st_flag` | 순환밸브 | `circulation_valve_flag` | 순환 밸브 |
| `relay_11st_flag` | 흡입밸브 | `suction_valve_flag` | 흡입 밸브 |
| `relay_14st_flag` | 배출밸브 | `exhaust_valve_flag` | 배출 밸브 |
| `relay_15st_flag` | 히터밸브 | `heater_valve_flag` | 히터 밸브 |

### 5.3 작물 데이터 매핑

**PostgreSQL 컬럼 → ChromaDB 메타데이터**

| PostgreSQL 컬럼 | 한글명 | ChromaDB 필드 | 설명 |
|----------------|--------|---------------|------|
| `crop_strt_date` | 재배시작일 | `crop_strt_date` | YYYY-MM-DD |
| `crop_end_date` | 재배종료일 | `crop_end_date` | YYYY-MM-DD |
| `code_name` | 생육상태 | `growth_status` | 예: "수확기", "생육기" |
| `crop_qtty` | 총수확량 | `total_yield` | kg |
| `crop_grde_qtty_1` | 등급1 | `grade_1_yield` | kg |
| `crop_grde_qtty_2` | 등급2 | `grade_2_yield` | kg |
| `crop_grde_qtty_3` | 등급3 | `grade_3_yield` | kg |
| `crop_grde_qtty_4` | 등급4 | `grade_4_yield` | kg |
| `crop_grde_qtty_5` | 등급5 | `grade_5_yield` | kg |
| `crop_grde_amut_1` | 등급1판매가격 | `grade_1_price` | 원/kg |
| `crop_grde_amut_2` | 등급2판매가격 | `grade_2_price` | 원/kg |
| `crop_grde_amut_3` | 등급3판매가격 | `grade_3_price` | 원/kg |
| `crop_grde_amut_4` | 등급4판매가격 | `grade_4_price` | 원/kg |
| `crop_grde_amut_5` | 등급5판매가격 | `grade_5_price` | 원/kg |

**계산 필드**:
- `grade_{1-5}_revenue` = `grade_{1-5}_yield` × `grade_{1-5}_price`
- `total_revenue` = Σ `grade_{1-5}_revenue`
- `grade_1_ratio` = `grade_1_yield` / `total_yield`

### 5.4 문서 ID 생성 규칙

```python
def generate_doc_id(kind, farm_id, house_id, timestamp):
    if kind == "units":
        # 3분 단위 버킷팅
        bucket_min = ((minute - 1) // 3 + 1) * 3
        return f"units_{farm_id}_{house_id}_{timestamp:%Y-%m-%d %H:%M:00}"

    elif kind == "crops":
        # 초 단위까지 포함
        return f"crops_{farm_id}_{house_id}_{timestamp:%Y-%m-%d %H:%M:%S}"
```

**예시**:
- Units: `units_1_1_2025-12-04 10:03:00`
- Crops: `crops_1_1_2025-12-04 10:15:30`

---

## 6. 개선 필요 사항

### 6.1 성능 개선

#### ⚠️ 문제점 1: 중간 JSON 파일 사용
**현재**: PostgreSQL → JSON 파일 → ChromaDB
**문제**: 불필요한 I/O 오버헤드, 디스크 공간 낭비
**개선 방안**:
- 직접 PostgreSQL → ChromaDB 변환
- 스트리밍 처리로 메모리 효율 개선
```python
# 현재
def run_data_export():  # PostgreSQL → JSON
    ...
def json_to_vcdb():     # JSON → ChromaDB
    ...

# 개선안
def direct_pg_to_chromadb():
    """PostgreSQL에서 직접 ChromaDB로 변환"""
    for farmhouse in read_farm_house_list():
        for unit_batch in read_units_data_streaming(farm_id, house_id):
            process_and_store_units(unit_batch)
```

#### ⚠️ 문제점 2: 중복 데이터 조회
**현재**: `json_to_vcdb()`에서 JSON 로드 후 다시 Units/Crops 데이터를 개별 조회
**문제**: 데이터 중복 처리
**개선 방안**:
- JSON에서 로드한 데이터를 직접 처리
- 불필요한 재조회 제거

#### ⚠️ 문제점 3: 임베딩 생성하지 않음
**현재**: 제로 벡터 `[0.0, 0.0, ..., 0.0]` 저장
**문제**: 벡터 검색 기능 미작동
**개선 방안**:
- 문서 텍스트에서 실제 임베딩 생성
- Sentence Transformers 또는 OpenAI 임베딩 사용
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

def generate_embedding(text):
    return model.encode(text).tolist()
```

### 6.2 데이터 품질 개선

#### ⚠️ 문제점 4: 센서 이상값 처리 부족
**현재**: `clean_sensor_value()`에서 None, NaN만 처리
**문제**: 물리적으로 불가능한 값 (예: 온도 -999°C) 저장됨
**개선 방안**:
- 센서별 정상 범위 검증
- 이상치 필터링 또는 보간
```python
SENSOR_RANGES = {
    "indoor_temperature_value": (-20, 60),  # °C
    "indoor_humidity_value": (0, 100),      # %
    "co2_concentration_value": (0, 5000),   # ppm
}

def validate_sensor_value(sensor_name, value):
    if sensor_name in SENSOR_RANGES:
        min_val, max_val = SENSOR_RANGES[sensor_name]
        if not (min_val <= value <= max_val):
            logger.warning(f"이상값 감지: {sensor_name}={value}")
            return None
    return value
```

#### ⚠️ 문제점 5: 시간 동기화 문제
**현재**: 센서와 릴레이 데이터를 `recd_dttm`으로 조인
**문제**: 정확히 일치하는 타임스탬프만 조인됨 (데이터 누락 가능)
**개선 방안**:
- 시간 윈도우 기반 조인 (예: ±30초)
- 센서 데이터 우선 조회 후 가장 근접한 릴레이 상태 매칭

### 6.3 확장성 개선

#### ⚠️ 문제점 6: 하드코딩된 시간 버킷
**현재**: 3분 고정 집계
**문제**: 다른 시간 단위 집계 불가능
**개선 방안**:
- 설정 파일에서 집계 단위 지정
- 다중 시간 해상도 지원 (1분, 5분, 10분, 1시간)

#### ⚠️ 문제점 7: 단일 컬렉션 사용
**현재**: 모든 데이터를 `source_collection`에 저장
**문제**: Units와 Crops 데이터가 혼재, 검색 효율 저하
**개선 방안**:
- Units 전용 컬렉션: `units_source_collection`
- Crops 전용 컬렉션: `crops_source_collection`
- 학습 후: `learned_units_collection`, `learned_crops_collection`

### 6.4 에러 처리 개선

#### ⚠️ 문제점 8: 부분 실패 시 롤백 없음
**현재**: 일부 데이터 저장 실패 시 계속 진행
**문제**: 데이터 일관성 문제
**개선 방안**:
- 트랜잭션 단위 처리 (농장/재배사별)
- 실패 시 재시도 로직
- 실패한 데이터 별도 로그 기록

#### ⚠️ 문제점 9: 로깅 상세도 부족
**현재**: 성공/실패 카운트만 로깅
**문제**: 문제 원인 파악 어려움
**개선 방안**:
- 실패한 데이터의 farm_id, house_id, timestamp 기록
- 에러 메시지 상세화
- 처리 시간 측정 및 로깅

### 6.5 유지보수성 개선

#### ⚠️ 문제점 10: 긴 함수 (process_unit_data 170줄)
**문제**: 가독성 저하, 테스트 어려움
**개선 방안**:
- 함수 분리:
  - `aggregate_sensor_data(group)`
  - `calculate_relay_majority(group)`
  - `generate_unit_metadata(aggregated_data)`
  - `generate_unit_document(metadata)`
  - `save_to_chromadb(doc_id, document, metadata)`

#### ⚠️ 문제점 11: 매직 넘버
**현재**: 3분 집계 시 `((m - 1) // 3 + 1) * 3`
**문제**: 의도 파악 어려움
**개선 방안**:
```python
UNIT_AGGREGATION_MINUTES = 3

def align_to_bucket(dt, bucket_minutes=UNIT_AGGREGATION_MINUTES):
    """타임스탬프를 버킷 단위로 정렬"""
    minute = dt.minute
    bucket = ((minute - 1) // bucket_minutes + 1) * bucket_minutes
    ...
```

### 6.6 보안 개선

#### ⚠️ 문제점 12: SQL 인젝션 가능성
**현재**: `execute_query(query, vals)` 사용 중
**상태**: 현재는 안전하게 파라미터 바인딩 사용 중
**권장사항**: ORM 사용 검토 (SQLAlchemy)

---

## 7. 실행 방법

### 7.1 Phase 1: PostgreSQL → JSON

```python
from agri_ai_core.data_ingestion.json_exporter import run_data_export

# 전체 데이터 내보내기
success = run_data_export()

if success:
    print("JSON 파일 생성 완료")
else:
    print("JSON 파일 생성 실패")
```

**출력 파일**: `./FarmUnits/v3/farm_unit_info.json`

### 7.2 Phase 2: JSON → ChromaDB

```python
from agri_ai_core.data_pipeline.json_loader import json_to_vcdb

# JSON을 ChromaDB로 변환
success = json_to_vcdb(data_limit=100000)

if success:
    print("ChromaDB 저장 완료")
else:
    print("ChromaDB 저장 실패")
```

### 7.3 전체 파이프라인 실행

```python
from agri_ai_core.data_ingestion.json_exporter import run_data_export
from agri_ai_core.data_pipeline.json_loader import json_to_vcdb

# Phase 1: PostgreSQL → JSON
if run_data_export():
    print("✓ Phase 1 완료: JSON 파일 생성")

    # Phase 2: JSON → ChromaDB
    if json_to_vcdb():
        print("✓ Phase 2 완료: ChromaDB 저장")
        print("✓ 전체 파이프라인 성공")
    else:
        print("✗ Phase 2 실패")
else:
    print("✗ Phase 1 실패")
```

### 7.4 스케줄링 (주기적 실행)

```python
from agri_ai_core.control.scheduler.task_scheduler import scheduler

# 매시간 정각에 실행
scheduler.add_job(
    func=run_data_export,
    trigger='cron',
    hour='*',
    minute='0',
    id='data_export_job'
)

# 매시간 5분에 실행
scheduler.add_job(
    func=json_to_vcdb,
    trigger='cron',
    hour='*',
    minute='5',
    id='chromadb_sync_job'
)
```

### 7.5 CLI 실행 (향후 추가 권장)

```bash
# PostgreSQL → JSON
python -m agri_ai_core.data_ingestion.cli export --output ./data/export.json

# JSON → ChromaDB
python -m agri_ai_core.data_pipeline.cli sync --input ./data/export.json

# 전체 파이프라인
python -m agri_ai_core.data_pipeline.cli pipeline --mode full
```

---

## 8. 참고 자료

### 8.1 관련 파일
- PostgreSQL 쿼리: `agri_ai_core/database/postgres/queries.py`
- 데이터베이스 연결: `agri_ai_core/database/postgres/connection.py`
- ChromaDB 클라이언트: `agri_ai_core/database/chromadb/client.py`
- 설정 파일: `config.yaml`, `.env`

### 8.2 설정 파라미터

```yaml
# config.yaml
vector:
  vector_cache: "./FarmUnits/v3/llm_vector.db"

database:
  host: "localhost"
  port: 5432
  database: "smartfarm"
  user: "postgres"
  password: "password"

embedding_dim: 384  # 임베딩 차원
```

### 8.3 ChromaDB 컬렉션

| 컬렉션명 | 용도 |
|---------|------|
| `farm_data_source` | 원본 데이터 (Units + Crops) |
| `farm_data_learned` | 학습 완료 데이터 |
| `job_status` | 작업 상태 추적 |

---

**문서 끝**
