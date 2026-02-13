# ChromaDB 학습 데이터 분석 및 개선 방향

**작성일**: 2025-12-10
**목적**: 상황버섯 재배사 환경 최적화를 위한 학습 시스템 개선

---

## 1. 현황 분석

### 1.1 PostgreSQL 데이터 현황 (2025-02-05 ~ 2025-12-10)
```
✅ 센서 데이터: 15,240,228건
   - farm_id, hous_id, recd_dttm
   - 내부온도, 내부습도, 외부온도, 외부습도
   - CO2, 수온, 광량, 수위

✅ 릴레이 데이터: 충분한 데이터 존재
   - 16개 릴레이 상태 (boolean)
   - 물가열기, 분사펌프, 배수밸브, 흡기팬, 배기팬 등

⚠️ 생육/수확 데이터: 불완전
   - crop_strt_date, crop_end_date가 NULL
   - 총수확량, 등급별 수확량이 모두 0.000
   - rmks(비고)에만 수동 입력된 관찰 내용 존재
```

### 1.2 ChromaDB 현황
```
❌ 모든 컬렉션이 비어있음 (0건)
   - farm_collection: 0건
   - source_collection: 0건
   - stats_collection: 0건
   - optimal_collection: 0건
   - learned_collection: 0건
   - document_collection: 0건
```

---

## 2. 문제점 분석

### 2.1 심각한 문제
1. **ChromaDB 학습 데이터 전무**
   - 현재 설계된 모든 컬렉션이 비어있음
   - PostgreSQL → ChromaDB 이관 작업이 수행되지 않음
   - 학습 스케줄러가 작동하지 않음

2. **생육/수확 데이터 부재**
   - 실제 수확량 데이터가 0으로 기록됨
   - 재배 시작일/종료일이 NULL
   - **학습의 핵심인 "생육이 좋았을 때"를 판단할 수 없음**

3. **현재 학습 방법의 근본적 문제**
   - 문서(docs) 기반 학습을 시도하고 있으나 데이터가 없음
   - 센서/릴레이 → 수확량 상관관계 학습이 불가능
   - 최적 환경 조건 도출이 불가능

### 2.2 구조적 문제
1. **잘못된 학습 데이터 형식**
   - 현재: 센서/릴레이 데이터를 텍스트 문서로 변환 후 임베딩
   - 문제: 시계열 수치 데이터를 텍스트로 변환하면 패턴 손실
   - 결과: RAG 검색으로는 "센서 값 X일 때 수확량 Y" 같은 관계를 학습할 수 없음

2. **학습 목표와 방법의 불일치**
   - 목표: 버섯 재배 환경 최적화 (센서 → 릴레이 제어)
   - 현재 방법: 텍스트 문서 기반 RAG (질문-답변)
   - **RAG는 지식 검색용이지, 환경 제어 학습용이 아님**

---

## 3. 올바른 학습 방향

### 3.1 학습 데이터 구조 재설계

#### A. ChromaDB 사용 목적 재정의
**기존 (잘못됨)**:
- 센서/릴레이 데이터를 문서로 변환
- 임베딩 벡터로 검색
- 용도: 과거 데이터 질의응답

**개선 (올바름)**:
- **일반 농업 지식**: ChromaDB (문서 기반 RAG)
  - "상황버섯 최적 온도는?" → 문서 검색
  - "버섯 병해 예방법은?" → 문서 검색

- **환경 제어 학습**: PostgreSQL 집계 테이블 + 통계 분석
  - "수확량이 많았을 때의 온도/습도 패턴" → SQL 집계
  - "온도 27도일 때 켜야 할 릴레이" → 통계 기반 규칙

#### B. 데이터 구분

| 데이터 유형 | 저장소 | 용도 | 예시 |
|------------|--------|------|-----|
| 일반 농업 지식 | ChromaDB (document_collection) | RAG 검색 | "상황버섯 재배법", "병해 예방" |
| 센서 raw 데이터 | PostgreSQL (sensor_l_recording) | 실시간 조회 | "현재 1재배사 온도" |
| 릴레이 raw 데이터 | PostgreSQL (relay_l_recording) | 실시간 조회 | "현재 릴레이 상태" |
| 통계 데이터 | PostgreSQL (새 테이블) | 패턴 분석 | "시간대별 평균 온도" |
| **최적 환경 규칙** | PostgreSQL (새 테이블) | 제어 로직 | "온도 25-27도, 습도 85-90%" |
| 학습된 릴레이 규칙 | PostgreSQL (새 테이블) | 자동 제어 | "온도<25도 → 물가열기 ON" |

### 3.2 제안하는 새로운 테이블 구조

```sql
-- 1. 시간대별 통계 테이블 (10분 단위 집계)
CREATE TABLE sensor_statistics (
    farm_id BIGINT,
    hous_id BIGINT,
    stat_dttm TIMESTAMP,  -- 00:00, 00:10, 00:20 ...
    indr_tprt_avg DOUBLE PRECISION,
    indr_tprt_min DOUBLE PRECISION,
    indr_tprt_max DOUBLE PRECISION,
    indr_hmdt_avg DOUBLE PRECISION,
    indr_hmdt_min DOUBLE PRECISION,
    indr_hmdt_max DOUBLE PRECISION,
    co2_avg NUMERIC,
    co2_min NUMERIC,
    co2_max NUMERIC,
    PRIMARY KEY (farm_id, hous_id, stat_dttm)
);

-- 2. 릴레이 가동 통계 (10분 단위 집계)
CREATE TABLE relay_statistics (
    farm_id BIGINT,
    hous_id BIGINT,
    stat_dttm TIMESTAMP,
    relay_1st_on_minutes INT,  -- 10분 중 몇 분 켜졌는지
    relay_2st_on_minutes INT,
    relay_5st_on_minutes INT,
    relay_6st_on_minutes INT,
    -- ... 나머지 릴레이
    PRIMARY KEY (farm_id, hous_id, stat_dttm)
);

-- 3. 생육 주기 정보 (수동 입력 필요!)
CREATE TABLE crop_cycles (
    farm_id BIGINT,
    hous_id BIGINT,
    cycle_id SERIAL,
    start_date DATE NOT NULL,
    end_date DATE,
    total_harvest NUMERIC DEFAULT 0,
    grade_1_harvest NUMERIC DEFAULT 0,
    grade_2_harvest NUMERIC DEFAULT 0,
    grade_3_harvest NUMERIC DEFAULT 0,
    quality_score INT,  -- 1-5 점수
    notes TEXT,
    PRIMARY KEY (farm_id, hous_id, cycle_id)
);

-- 4. 최적 환경 조건 (학습 결과 저장)
CREATE TABLE optimal_conditions (
    farm_id BIGINT,
    hous_id BIGINT,
    crop_cycle_id INT,  -- 어느 재배 주기 기반인지
    growth_stage VARCHAR(50),  -- '초기', '생육기', '수확기'
    indr_tprt_min DOUBLE PRECISION,
    indr_tprt_optimal DOUBLE PRECISION,
    indr_tprt_max DOUBLE PRECISION,
    indr_hmdt_min DOUBLE PRECISION,
    indr_hmdt_optimal DOUBLE PRECISION,
    indr_hmdt_max DOUBLE PRECISION,
    co2_min NUMERIC,
    co2_optimal NUMERIC,
    co2_max NUMERIC,
    is_manual BOOLEAN DEFAULT FALSE,  -- 수동 설정 여부
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (farm_id, hous_id, growth_stage)
);

-- 5. 릴레이 제어 규칙 (학습 결과)
CREATE TABLE relay_control_rules (
    rule_id SERIAL PRIMARY KEY,
    farm_id BIGINT,
    hous_id BIGINT,
    condition_type VARCHAR(50),  -- '온도상승', '온도하강', '습도상승' 등
    sensor_condition TEXT,  -- 'indr_tprt < 25'
    relay_action JSONB,  -- {"relay_1st_flag": true, "relay_9st_flag": true}
    priority INT,  -- 규칙 우선순위
    success_rate DOUBLE PRECISION,  -- 이 규칙의 성공률
    is_manual BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 4. 구현 로드맵

### Phase 1: 데이터 기반 마련 (우선순위 높음)
1. **생육 주기 데이터 수동 입력**
   - farmhouse_l_crops 테이블에 실제 재배 시작일/종료일 입력
   - 수확량 데이터 입력
   - rmks의 관찰 내용을 구조화된 데이터로 변환

2. **통계 테이블 생성 및 집계**
   - `sensor_statistics` 테이블 생성
   - 기존 15,240,228건의 raw 데이터를 10분 단위로 집계
   - `relay_statistics` 테이블 생성 및 집계

3. **최적 조건 분석**
   - 수확량이 많았던 재배 주기 식별
   - 해당 기간의 센서 데이터 패턴 분석
   - `optimal_conditions` 테이블에 저장

### Phase 2: 제어 로직 구현
1. **릴레이 제어 규칙 생성**
   - 문서의 [학습방법] 섹션 기반 규칙 코드화
   - 우선순위: 온도 > 습도 > CO2
   - `relay_control_rules` 테이블에 저장

2. **자동 제어 시스템**
   - 현재 센서값 → 규칙 매칭 → 릴레이 제어
   - 수동/자동 모드 전환 기능

### Phase 3: LLM 통합
1. **ChromaDB document_collection에 지식 추가**
   - 상황버섯 재배 매뉴얼
   - 병해 대처 방법
   - 일반 농업 지식

2. **질의응답 개선**
   - "스마트팜이란?" → ChromaDB RAG
   - "1재배사 현재 상태" → PostgreSQL 실시간 데이터
   - "최적 온도는?" → optimal_conditions 테이블
   - "릴레이 왜 켜졌어?" → relay_control_rules + 현재 센서값

---

## 5. 즉시 수행해야 할 작업

### 5.1 데이터 정비 (긴급)
```sql
-- A. 생육 데이터 확인
SELECT * FROM farmhouse_l_crops WHERE crop_qtty > 0;

-- B. 센서 설정 확인
SELECT * FROM sensor_m_setting;

-- C. 재배사 정보 확인
SELECT farm_id, hous_id, hous_name, crop_kind
FROM farmhouse_m_info;
```

### 5.2 스케줄러 점검
```bash
# 데이터 이관 스케줄러가 작동하지 않음
# agri_ai_core/data_pipeline/scheduler/ 확인 필요
```

### 5.3 학습 로직 재설계
현재 `learned_collection`에 데이터를 넣으려는 로직이 있지만:
- ❌ 텍스트 문서로 변환하는 방식은 비효율적
- ✅ SQL 집계 + 통계 분석이 올바른 방향

---

## 6. 결론

### 핵심 문제
1. **ChromaDB가 비어있음** - 학습 데이터 이관 실패
2. **생육 데이터가 없음** - 학습 목표(좋은 수확) 판단 불가
3. **잘못된 학습 방법** - 수치 데이터를 텍스트 RAG로 처리 시도

### 해결 방안
1. **ChromaDB**: 일반 농업 지식만 저장 (문서 기반)
2. **PostgreSQL**: 센서/릴레이 통계 + 최적 조건 + 제어 규칙
3. **생육 데이터**: 수동 입력 또는 농장주와 협력하여 수집

### 우선순위
```
[긴급] 생육 데이터 수집 및 입력
[긴급] 통계 테이블 생성 및 집계
[높음] 최적 조건 분석 로직 구현
[중간] ChromaDB에 농업 지식 문서 추가
[낮음] 자동 제어 시스템 고도화
```

---

**다음 단계**: 이 분석을 바탕으로 코드 수정 계획 수립
