# 농장 데이터 RAG 개선 — 생육 기반 인과 관계 RAG 전환

# =============
농장 데이터 RAG 방법을 개선하고자 한다.
- RAG주기: 일2회 (12:00, 00:00) 에 스케쥴에 따라 수행
- RAG방법:
-- 생육데이터가 입력된 시점에서 이전 생육데이터 생성 이후 시점 사이에 있는 센서값, 릴레이 셋팅 값의 단순평균, 이동평균 등 RAG 시점의 생육데이터가 되기 위한 모든 형태의 센서값, 릴레이값을 이용.
-- RAG 실행 시점에 생육데이터가 입력된 시점이 RAG 데이터가 생성되는것으로 RAG 일 2회 실행시 몇개의 RAG 가 생길 수도 없을 수도 있다.
-- 생육 RAG 데이터 저장은 센서데이터, 릴레이데이터, 데이터 생성 시점의 생육 데이터(rag시점의 계절시기, 오전/오후, 생육단계, 생육상태, 수기입력 생육데이터 등 등 최대한 세분화된 정보)로 저장
-- 00:00 분 RAG시 당일 생육 데이터가 한건도 입력이 안된경우는 00:00분기준 생육정보를 정상인 것으로 간주하여 RAG 수행, 즉 1일 최소 1회의 RAG 데이터 생성
- 기타 요구사항
-- 장기적으로 쌓인 과거 데이터를 이용해서 일정 시점 부터는 그 데이터를 활용해서 AI가 현재의 생육 환경을 위한 데이터 셋팅을 하고자 함이 목적
-- RAG 방법을 추가 제시하고
-- 가능하다면 RAG를 위한 생육 정보를 더 세분화 해서, 관련 테이블에 컬럼을 추가하고
-- 장기적 정보가 누적되었을때 AI가 가장 정확한 데이터로 활용하는 방안으로 RAG 방법과 데이터를 제안

추가로 전체파일을 현재 싯점으로 정확히 분석하고, 기존기능에서 제외할 부분, 혹은 기존 기능을 변경할 부분, 신규 작성할 부분 등을 자세히 작업게획서에 작성해야 한다. 반드시 현재 시점의 전체 코드를 분석하라.
# =============

---

## Context
현재 학습 파이프라인은 "시간대(hour) 기반"으로 센서/릴레이/생육 데이터를 1시간 단위로 집계하여 VectorDB에 저장한다.
그러나 사용자의 핵심 목적은 **"생육 데이터 입력 시점 기반으로, 해당 생육 결과를 만들어낸 센서/릴레이 환경 조건을 인과 관계로 묶어 RAG 데이터로 저장"**하는 것이다.
장기적으로 이 데이터가 누적되면, AI가 "이 생육단계에서 이런 환경을 유지하면 이런 생육 결과가 나왔다"를 학습하여 최적 환경 셋팅을 제안할 수 있게 된다.

---

## Phase 0: FARMHOUSE_L_CROPS 테이블 컬럼 추가 (생육 정보 세분화)

### 0-1. 신규 컬럼 추가 DDL (`queries.py`에 추가)

현재 `FARMHOUSE_L_CROPS` 테이블에는 생육단계(crop_lvel), 생육상태(crop_stat), 비고(rmks)만 있어 세부 관찰 데이터가 부족하다.

```sql
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS obsv_date DATE;
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS leaf_count INTEGER;
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS leaf_size VARCHAR(20);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS leaf_color VARCHAR(20);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS stem_height NUMERIC(6,1);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS stem_diameter NUMERIC(6,1);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS pest_type VARCHAR(50);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS pest_severity VARCHAR(10);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS fruit_count INTEGER;
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS fruit_size VARCHAR(20);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS watering_memo VARCHAR(200);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS growth_memo VARCHAR(500);
```

### 0-2. `queries.py`에 ALTER DDL 추가
- 상수명: `ALTER_CROPS_ADD_GROWTH_DETAIL_COLUMNS`
- `startup.py` Phase [3/4]에서 실행 (IF NOT EXISTS이므로 중복 실행 안전)

### 0-3. `GET_UNLEARNED_CROPS_DATA` 쿼리 확장
- 신규 컬럼들을 SELECT에 추가 (영문 alias)

---

## Phase 1: 신규 SQL 쿼리 추가 (`queries.py`)

| 상수명 | 용도 |
|--------|------|
| `GET_LAST_GROWTH_RAG_DATETIME` | 마지막 RAG 처리 시점 조회 |
| `GET_CROPS_IN_RANGE` | 특정 시간 구간 생육 데이터 조회 |
| `GET_SENSOR_STATS_IN_RANGE` | 센서 통계 (AVG, STDDEV, MIN, MAX) |
| `GET_RELAY_STATS_IN_RANGE` | 릴레이 가동 비율 |
| `GET_SENSOR_STATS_DAY_NIGHT` | 주야간 분리 센서 통계 |
| `GET_SENSOR_MOVING_AVG` | 이동평균 (6시간 윈도우) |
| `CHECK_TODAY_CROPS_EXISTS` | 당일 생육 입력 존재 확인 |
| `GET_ACTIVE_FARM_HOUSES_WITH_CROP` | 활성 농장-재배사 목록 |

---

## Phase 2: 핵심 — 생육 RAG 프로세서 신규 생성

### 파일: `agri_ai_core/src/ai/learning/growth_rag_processor.py` (신규)

```
run_growth_rag()              — 메인 진입점 (스케줄러에서 호출)
_get_last_rag_datetime()      — 마지막 RAG 처리 시점 조회
_update_last_rag_datetime()   — RAG 처리 시점 갱신
_get_new_crop_entries()       — 새로운 생육 입력 조회
_get_sensor_stats()           — 시간 구간 센서 통계 조회
_get_relay_stats()            — 시간 구간 릴레이 통계 조회
_get_day_night_stats()        — 주야간 분리 통계
_get_moving_averages()        — 이동평균 샘플 조회
_build_growth_context()       — 생육 컨텍스트 구성 (계절/시간대/재배일수 등)
_build_rag_document()         — RAG 문서 텍스트 생성
_build_rag_metadata()         — RAG 메타데이터 구성
_store_growth_rag()           — VectorDB 저장
_ensure_daily_rag()           — 00:00 실행 시 당일 RAG 보장
```

### 메인 흐름 (`run_growth_rag`)
1. `last_rag_dt` = 마지막 RAG 처리 시점 조회
2. 활성 농장-재배사 목록 조회
3. 각 (farm_id, house_id)별:
   - 새 생육 입력 조회 → 있으면 각각에 대해 센서/릴레이 통계 + 주야간 + 이동평균 조회 → RAG 문서+메타데이터 생성 → VectorDB 저장
   - 00:00 실행이고 당일 생육 없으면 → `_ensure_daily_rag()` (정상 간주 RAG)
4. 처리 시점 갱신

### RAG 문서 예시
```
[생육 RAG] 2026-02-25 농장1 재배사1
계절: 겨울 | 생육단계: 수확기 | 재배 45일차 | 오후 14시
생육상태: 양호 | 작물: 느타리버섯 | 제어: 자동

[환경 통계 (2026-02-23 ~ 2026-02-25, 센서 288건)]
- 실내온도: 평균 18.5°C (주간 20.1°C / 야간 16.9°C), 표준편차 1.8, 범위 14.2~23.1
- 실내습도: 평균 82.3% (주간 78.5% / 야간 86.1%), 표준편차 4.2, 범위 68.0~95.0
- CO2: 평균 680ppm, 표준편차 120, 범위 420~980
...

[릴레이 가동 비율]
- 히터: 32.5% | 미스팅: 15.8% | 배기팬: 48.2% | 조명: 41.0% | 관수: 22.5%

[이동평균 트렌드 (6시간 윈도우)]
- 온도: 상승 추세 (16.0→18.5°C)
- 습도: 안정 (81~84%)

[생육 결과]
- 총 수확량: 45kg | 1등급: 30kg(66.7%) | 2등급: 10kg | 3등급: 5kg
- 관찰: 잎 색상 녹색, 줄기 높이 15cm, 병해충 없음
```

---

## Phase 3: 스케줄러 변경

- `task_scheduler.py`의 `setup_default_jobs()`에 `growth_rag_func` 매개변수 추가
- 일 2회 실행: 12:00 (일반), 00:00 (is_midnight=True)
- `startup.py`에서 `growth_rag_func=run_growth_rag` 전달

---

## Phase 4: 기존 코드 변경/유지/제거 상세

### `model_trainer.py` — 유지 (더미 데이터 생성→스킵으로 변경)
| 함수 | 판정 | 이유 |
|------|------|------|
| `verify_chroma_connection()` | 유지 | 공용 헬스체크 |
| `create_default_crop_entry()` | 변경 | 호출부에서 스킵 로직으로 전환 |
| `create_default_units_entry()` | 변경 | 동일 |
| `process_farm_hour_data()` | 유지 | 기존 시간대 기반 학습 유지 |
| `update_ollama_model()` | 유지 | 기존 학습 파이프라인 유지 |

### `data_analyzer.py` — 전체 유지
- `get_growth_status_rank()`, `is_positive_remark()` → growth_rag에서 재활용

### `loader.py` — 전체 유지

### `queries.py` — 신규 8개 쿼리 추가 + GET_UNLEARNED_CROPS_DATA 확장

### `tools_executor.py` — 변경
- `search_farm_knowledge()`에서 season/crop_level 메타데이터 필터 추가

### `config.py` — 상수 3개 추가
- `GROWTH_RAG_HOURS`, `GROWTH_RAG_TTL_DAYS`, `GROWTH_RAG_MOVING_AVG_WINDOW`

### `task_scheduler.py` — growth_rag_job 등록

### `startup.py` — ALTER DDL 실행 + growth_rag_func 연동

### 변경하지 않는 파일
reranker.py, chunker.py, embedder.py, conversation_store.py, operations.py, collections.py, client.py, config.py(chroma), conversion.py, validators.py, date_utils.py, tools_definition.py, loader.py, reader.py

---

## Phase 5: 추가 RAG 방법 제안

### 5-1. 계절-생육단계 패턴 벡터 (장기 누적 활용)
- 동일 계절 + 동일 생육단계의 과거 RAG 데이터를 집계하여 "패턴 벡터" 생성
- ChromaDB where 필터로 `season + crop_level` 활용

### 5-2. 생육 결과 피드백 루프
- 수확 완료 시점(crop_end_date) 감지 → 재배 기간 전체 RAG에 성공/실패 라벨링
- grade_1_ratio > 60% → "우수", 30~60% → "보통", < 30% → "개선 필요"

### 5-3. 이상 상태 자동 감지 RAG
- 표준편차 2배 이상 → "환경 불안정" 태그
- 병해충 감지 → "병해충 발생 환경" 태그

---

## Phase 6: 장기 데이터 활용 전략 — AI 최적 환경 셋팅

### 6-1. 검색 시 컨텍스트 매칭 강화
- season + crop_level 메타데이터 필터 자동 적용
- 사용자 질문에서 계절/생육단계 키워드 감지 → where 절 구성

### 6-2. 데이터 축적 후 자동 최적 조건 도출 (향후)
- 동일 조건 RAG 10건 이상 축적 시
- 성공 사례(grade_1_ratio > 60%) 센서 통계 평균 → "권장 환경"
- 현재 센서값과 비교 → 조정 방향 제안

---

## 수정 파일 전체 목록

| 순서 | 파일 | 작업 |
|------|------|------|
| 1 | `agri_ai_core/src/postgresql/queries.py` | ALTER DDL + 8개 신규 쿼리 + 확장 |
| 2 | `agri_ai_core/startup.py` | ALTER DDL 실행 + growth_rag 연동 |
| 3 | `agri_ai_core/config.py` | GROWTH_RAG 상수 3개 추가 |
| 4 | `agri_ai_core/src/ai/learning/growth_rag_processor.py` | **신규** |
| 5 | `agri_ai_core/src/control/task_scheduler.py` | growth_rag_job 등록 |
| 6 | `agri_ai_core/src/ai/learning/model_trainer.py` | 더미→스킵 |
| 7 | `agri_ai_core/src/ai/tools_executor.py` | 메타데이터 필터 |

---

## 검증 방법

```bash
# 1. 구문 오류 검증
python -c "from agri_ai_core.src.ai.learning.growth_rag_processor import run_growth_rag; print('OK')"

# 2. 수동 RAG 실행
python -c "from agri_ai_core.src.ai.learning.growth_rag_processor import run_growth_rag; print(run_growth_rag())"

# 3. 서비스 기동 테스트
sudo ./agriAiCore restart && sudo ./agriAiCore status
```
