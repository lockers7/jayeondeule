# agri_ai_core 코드 최적화 작업 계획서

> 작성일: 2026-02-27
> 대상: `agri_ai_core/` 디렉토리 전체 (56개 .py 파일)
> 원칙: **기존 기능 100% 보존**, 순수 코드 품질 개선만 수행

---

## 1. 분석 요약

| 분류 | 파일 수 | 최적화 대상 | 최적화 불필요 |
|------|---------|------------|-------------|
| ai 모듈 | 8 | 6 | 2 |
| rag 모듈 | 5 | 4 | 1 |
| learning 모듈 | 3 | 3 | 0 |
| chroma 모듈 | 6 | 3 | 3 |
| control 모듈 | 4 | 4 | 0 |
| postgresql 모듈 | 4 | 3 | 1 |
| config 모듈 | 4 | 2 | 2 |
| api 모듈 | 5 | 3 | 2 |
| utils 모듈 | 3 | 1 | 2 |
| voice 모듈 | 3 | 0 | 3 |
| 루트 파일 | 3 | 3 | 0 |
| **합계** | **56** | **32** | **24** |

---

## 2. 우선순위별 최적화 항목

### 2.1 높음 (중복 코드 대량 제거, 성능 영향)

#### OPT-01: schedule_control.py + manual_control.py 공통 함수 추출
- **파일**: `src/control/schedule_control.py`, `src/control/manual_control.py`
- **문제**: `_to_sortable_int()`, `_sort_houses()` 두 함수가 양쪽 파일에 **완전 동일하게 중복**
- **개선**: `src/utils/sorting.py` 신규 모듈로 추출, 양쪽에서 import
- **절감**: 약 30줄

#### OPT-02: schedule_control.py 조명/관수 제어 로직 통합
- **파일**: `src/control/schedule_control.py`
- **줄**: 179-225 (조명), 296-342 (관수)
- **문제**: 조명 제어와 관수 제어 코드가 **90% 동일** (변수명/릴레이 번호만 다름)
- **개선**: `_handle_schedule_control(schedule_type, relay_flag, settings)` 공통 함수 추출
- **절감**: 약 80줄
- **추가**: weekday_names 딕셔너리도 줄 221, 338에 중복 → 모듈 상수로 이동

#### OPT-03: logs.py 로거 초기화 로직 통합
- **파일**: `logs.py`
- **줄**: 93-144 (`setup_logger`), 159-211 (`setup_web_logger`)
- **문제**: 두 함수가 **60줄 이상 동일** (핸들러 설정, 포매터 적용, 캐시 관리)
- **개선**: `_setup_logger_impl(name, log_dir, ...)` 공통 헬퍼 추출
- **절감**: 약 60줄
- **추가**: 줄 295-305, 335-341 tempfile 처리도 `_write_temp_and_replace()` 로 추출

#### OPT-04: connection.py DB 실행 함수 공통 래퍼
- **파일**: `src/postgresql/connection.py`
- **줄**: 197-234 (`execute_query`), 236-275 (`fetch_all`), 277-314 (`fetch_one`)
- **문제**: 3개 함수 모두 **동일한 로깅 + MCP 폴백 + 재시도 패턴** 반복
- **개선**: `_execute_with_fallback(operation, query, params)` 래퍼 함수 추출
- **절감**: 약 60줄

#### OPT-05: startup.py DB 연결 중복 제거
- **파일**: `startup.py`
- **줄**: 127-161
- **문제**: 동일한 PostgreSQL 연결 파라미터로 **2번 연결 생성**, cursor 생성/닫기 반복
- **개선**: 단일 연결 + 단일 cursor로 통합, `_get_db_connection()` 헬퍼
- **추가**: 줄 37-42의 `for n in range(50): logger.info("-")` → `logger.info("-" * 50)` 단일 호출

#### OPT-06: data_analyzer.py 센서 통계 계산 제네릭화
- **파일**: `src/ai/learning/data_analyzer.py`
- **줄**: 248-296
- **문제**: 온도, 습도, CO2, 수온 등 **각 센서마다 동일한 np.percentile(), np.mean() 로직 반복**
- **개선**: `_analyze_sensor_condition(data, field_key, target_dict)` 제네릭 함수 추출
- **절감**: 약 40줄

---

### 2.2 중간 (코드 중복 · 메모리 · 가독성)

#### OPT-07: llm_client.py 트리플 폴백 루프화
- **파일**: `src/ai/llm_client.py`
- **줄**: 377-441
- **문제**: package → MCP → direct 3단계 동일한 함수 호출 패턴 반복
- **개선**: 폴백 전략을 리스트로 관리, 루프로 처리
```python
strategies = [("package", _call_package), ("mcp", _call_mcp), ("direct", _call_direct)]
for name, func in strategies:
    try: return func(...); break
    except: continue
```
- **추가**: 줄 316-354의 유사한 로깅 함수 `_log_llm_request_json()` / `_log_llm_response_json()` → 공통 헬퍼

#### OPT-08: file_processor.py CSV/Excel 공통 로직 추출
- **파일**: `src/ai/file_processor.py`
- **줄**: 32-49 (`read_csv_file`), 68-93 (`read_excel_file`)
- **문제**: 행 수 체크, 요약 생성, 컬럼 정보 추출 로직이 **거의 동일**
- **개선**: `_format_dataframe_output(df, max_rows, source_label)` 헬퍼 함수 추출
- **추가**: 줄 112-138 `read_text_file` 내 UTF-8/cp949 재시도에서 `max_chars` 초과 체크 중복 → 함수 밖으로 분리

#### OPT-09: mcp_client.py DNS 진단/모델 파싱 통합
- **파일**: `src/ai/mcp_client.py`
- **줄**: 103-133 (DNS 진단), 203-260 (모델 목록 파싱)
- **문제**: 4개 동일한 subprocess 호출 반복, `_direct_ollama_list_models()` / `_mcp_ollama_list_models()` 파싱 로직 동일
- **개선**: subprocess 호출 리스트화 + 루프, 공통 모델 파싱 함수 추출

#### OPT-10: query_handler_simple.py dedupe 함수 통합
- **파일**: `src/ai/query_handler_simple.py`
- **줄**: 25-37 (`_dedupe_tools`), 40-56 (`_dedupe_sources`)
- **문제**: 중복 제거 로직이 **거의 동일** (key 함수만 다름)
- **개선**: `_dedupe(items, key_func)` 제네릭 함수로 통합

#### OPT-11: growth_rag_processor.py DB 조회 래퍼 통합
- **파일**: `src/ai/learning/growth_rag_processor.py`
- **줄**: 67-80
- **문제**: `_get_new_crop_entries()`, `_get_sensor_stats()`, `_get_relay_stats()` 등 유사 구조 반복
- **개선**: `_query_db_with_fallback(query, params)` 제네릭 래퍼
- **추가**: 줄 256-280 주야간 통계 접근에서 `day_stats = day_night.get("day", {})` 반복 → 변수 1회 추출

#### OPT-12: model_trainer.py 작물 등급 필드 매핑 루프화
- **파일**: `src/ai/learning/model_trainer.py`
- **줄**: 359-374
- **문제**: `grade_1_yield` ~ `grade_5_yield` 5개 등급 동일 패턴 반복
- **개선**:
```python
for i in range(1, 6):
    crop_entry[f"crop_grde_qtty_{i}"] = data.get(f"grade_{i}_yield")
```

#### OPT-13: operations.py 재시도 대기 로직 통합
- **파일**: `src/chroma/operations.py`
- **줄**: 417-473
- **문제**: `time.sleep(1.5 ** retry)` 가 줄 423, 467에서 중복, 매치 딕셔너리 구성도 비효율
- **개선**: 재시도 대기를 단일 함수로, 매치 구성은 딕셔너리 컴프리헨션 활용

#### OPT-14: reader.py 공통 예외 처리 추출
- **파일**: `src/postgresql/reader.py`
- **줄**: 30-39, 53-64, 78-89
- **문제**: db_session, try-except, return [] 패턴이 3회 반복
- **개선**: 데코레이터 `@db_query_handler` 또는 공통 래퍼 함수

#### OPT-15: conversion.py 릴레이 데이터 파싱 통합
- **파일**: `src/utils/conversion.py`
- **줄**: 24-54, 66-84
- **문제**: relay_stats JSON 파싱 로직이 동일하게 반복
- **개선**: `_parse_relay_stats(relay_data)` 공통 함수 추출

#### OPT-16: api/app.py 미들웨어 JSON 파싱 추출
- **파일**: `api/app.py`
- **줄**: 47-104
- **문제**: 요청/응답 JSON 파싱 로직 반복 (줄 59-65, 86-89)
- **개선**: `_try_parse_json(body_bytes)` 헬퍼 함수 추출
- **추가**: 줄 205, 213의 에러 로깅/통계 기록 → `_record_query_stats()` 추출

#### OPT-17: loader.py 날짜 파싱 헬퍼 추출
- **파일**: `src/chroma/loader.py`
- **줄**: 67-99, 208-224
- **문제**: `after_date` 파싱이 8줄 조건문으로 복잡, 날짜 범위 필터링도 중복
- **개선**: `_parse_date(value)` 헬퍼 함수 추출

#### OPT-18: embedder.py 전역 상태 캡슐화
- **파일**: `src/ai/rag/embedder.py`
- **줄**: 149
- **문제**: `_EMBEDDING_SERVICE_DISABLED` 전역 변수를 `global` 키워드로 수정
- **개선**: 상태를 딕셔너리 또는 단일 클래스로 캡슐화
- **추가**: 줄 226-230, 257 재시도 대기 시간 계산 중복 → 상수화

---

### 2.3 낮음 (코드 정리 · 스타일)

#### OPT-19: traceback 런타임 import 통합
- **해당 파일**: `document_processor.py` (줄 249, 331), `model_trainer.py` (줄 154, 172, 294, 382, 403, 422, 465, 489)
- **문제**: 예외 블록 안에서 `import traceback` 런타임 임포트 반복 (총 10회 이상)
- **개선**: 각 파일 상단에서 한 번만 `import traceback`

#### OPT-20: conversation_store.py 정규식 통합
- **파일**: `src/ai/conversation_store.py`
- **줄**: 202-205
- **문제**: 동일 텍스트에 4개 `re.sub()` 순차 호출
- **개선**: 미리 컴파일된 단일 정규식으로 통합
- **추가**: 줄 236 함수 내 `from datetime import ...` → 파일 상단 import로 이동

#### OPT-21: manual_control.py / relay_manager.py 상수화
- **해당 파일**: `manual_control.py` (줄 434), `relay_manager.py` (줄 77-83), `task_scheduler.py` (줄 273)
- **문제**: `range(1, 17)` 매번 생성, 배치 크기 100 매직넘버
- **개선**: `RELAY_COUNT = 16`, `BATCH_DELETE_SIZE = 100` 상수 정의

#### OPT-22: document_processor.py 중복 딕셔너리 제거
- **파일**: `src/ai/rag/document_processor.py`
- **줄**: 303-307
- **문제**: `doc_type_labels` 가 줄 21-25의 전역 `DOC_TYPE_LABELS`와 동일하게 중복 정의
- **개선**: 전역 상수 재사용

#### OPT-23: growth_rag_processor.py 계절 판정 딕셔너리화
- **파일**: `src/ai/learning/growth_rag_processor.py`
- **줄**: 160-167
- **문제**: if-elif 조건문 기반 계절 문자열 반환
- **개선**: `SEASON_MAP = {3: "봄", 4: "봄", ..., 12: "겨울"}` 딕셔너리 매핑
- **추가**: 줄 306-321의 `_pct()` 내부 함수 → 모듈 레벨 `_format_percentage()` 로 이동

#### OPT-24: config/mappers.py 검색 함수 단순화
- **파일**: `config/mappers.py`
- **줄**: 138-181
- **문제**: `search_relay_function()` 내부 중복 반복문, 중간 래퍼 함수 불필요
- **개선**: `next()` + generator 식으로 단순화, 불필요한 래퍼 제거

#### OPT-25: validators.py 예외 타입 구체화
- **파일**: `src/utils/validators.py`
- **줄**: 40
- **문제**: bare `except Exception` 사용
- **개선**: `except (ValueError, TypeError)` 으로 구체화

#### OPT-26: voice_router.py 중복 예외 처리 제거
- **파일**: `api/voice_router.py`
- **줄**: 40-41, 72-73
- **문제**: `except HTTPException: raise` 중복
- **개선**: FastAPI 자동 처리로 제거 가능

#### OPT-27: chroma/utils.py 시퀀스 재귀 통합
- **파일**: `src/chroma/utils.py`
- **줄**: 34-49
- **문제**: 딕셔너리, 리스트, 튜플, 세트 각각 별도 재귀 분기
- **개선**: 시퀀스 타입(list, tuple, set)을 통합하여 단일 재귀 호출
- **추가**: 줄 116-136 JSON 플래그 2-pass → 단일 루프 통합

---

## 3. 최적화 불필요 파일 목록 (24개)

| 파일 | 사유 |
|------|------|
| `__init__.py` (7개) | 단순 import/export |
| `config/constants.py` | 상수 정의 (경미한 개선만 해당) |
| `config/settings.py` | 설정 로드 (경미한 개선만 해당) |
| `api/models.py` | Pydantic 모델 정의 |
| `api/__main__.py` | 엔트리포인트 |
| `api/example_client.py` | 테스트/예제 코드 |
| `src/ai/stats_collector.py` | Thread-safe 잘 구현됨 |
| `src/ai/tools_definition.py` | 도구 정의 데이터 |
| `src/chroma/collections.py` | 컬렉션 설정 반환 |
| `src/chroma/config.py` | 상수 정의 |
| `src/postgresql/queries.py` | SQL 쿼리 문자열 |
| `src/utils/date_utils.py` | 간결한 유틸리티 |
| `src/voice/stt_engine.py` | PyAV 표준 방식 |
| `src/voice/tts_engine.py` | 간결한 구현 |
| `scheduler.py` | APScheduler 래퍼 |

---

## 4. 작업 순서 및 예상 효과

### Phase 1: 대규모 중복 제거 (OPT-01 ~ OPT-06)
- **예상 절감**: 약 270줄
- **영향 범위**: control, logs, postgresql, startup, learning
- **위험도**: 낮음 (기능 동일, 호출 경로만 변경)

### Phase 2: 중간 규모 리팩터링 (OPT-07 ~ OPT-18)
- **예상 절감**: 약 200줄
- **영향 범위**: ai, rag, chroma, api
- **위험도**: 낮음 (내부 구현만 변경)

### Phase 3: 코드 정리 (OPT-19 ~ OPT-27)
- **예상 절감**: 약 80줄
- **영향 범위**: 전체 (import 정리, 상수화 등)
- **위험도**: 매우 낮음

---

## 5. 검증 방법

각 Phase 완료 후 다음을 검증:
1. 서비스 정상 기동 확인 (`sudo ./agriAiCore start all`)
2. FastAPI 엔드포인트 응답 확인 (`/query`, `/voice` 등)
3. 스케줄러 정상 동작 확인 (조명/관수 제어)
4. ChromaDB 검색/임베딩 정상 동작 확인
5. LLM 대화 응답 정상 확인

---

## 6. 주의사항

- 모든 변경은 **기능 동일성 보장** 필수
- 함수 시그니처(인자, 반환 타입) 변경 시 호출부 모두 확인
- 외부 모듈(raspi, web)에서 import하는 경로가 변경되지 않도록 주의
- 각 OPT 항목별로 변경 전 백업 수행
