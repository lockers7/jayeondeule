# 2차 코드 최적화 작업계획서

> 작성일: 2026-03-08 (2차 분석 추가: 2026-03-08)
> 분석 대상: agri_ai_core 전체 (40개 파일, Phase 1 완료 후 약 15,570줄)
> 원칙: **기존 기능 100% 보존**, 순수 코드 품질 개선만 수행

---

## 1. 분석 요약

### 1-1. 전체 코드 규모

| 영역 | 파일 수 | 줄 수 | 비율 |
|------|---------|-------|------|
| src/ai/ (LLM/RAG/도구) | 16 | 9,841 | 62.4% |
| src/control/ (제어/스케줄러) | 7 | 3,113 | 19.7% |
| api/ (FastAPI) | 4 | 752 | 4.8% |
| src/postgresql/ | 4 | 1,053 | 6.7% |
| config/ | 4 | 312 | 2.0% |
| 기타 (logs, startup 등) | 5 | 699 | 4.4% |
| **합계** | **40** | **15,770** | **100%** |

### 1-2. 주요 대형 파일

| 파일 | 줄 수 | 비율 | 특이사항 |
|------|-------|------|----------|
| llm_client.py | 2,745 | 17.4% | 전체 최대, 350줄짜리 함수 포함 |
| tools_executor.py | 1,407 | 8.9% | 280줄짜리 검색 함수 포함 |
| manual_control.py | 1,141 | 7.2% | 환경판단 로직 이중 구현 |
| mcp_client.py | 905 | 5.7% | HTTP 요청 중복 |
| ai_control.py | 680 | 4.3% | 100줄짜리 프롬프트 빌더 |
| learning/growth_rag_processor.py | 665 | 4.2% | |
| query_handler_simple.py | 651 | 4.1% | 200줄+ 핸들러 함수 |
| queries.py | 631 | 4.0% | |

---

## 2. 최적화 항목 상세

### 카테고리 A: 중복 코드 제거 (예상 절감 ~350줄)

#### OPT-A01. `filter_llm_response` + `clean_llm_response` 통합 ✅ 완료
- **파일**: `llm_client.py`
- **결과**: `clean_llm_response()` 통합 함수 구현, `filter_llm_response`는 호환 래퍼로 유지
- **절감**: ~90줄

#### OPT-A02. Ollama 3개 transport payload 빌드 공통화 ✅ 완료
- **파일**: `llm_client.py`
- **결과**: `_build_chat_payload()` 헬퍼 함수 추출, 4곳에서 사용
- **절감**: ~70줄

#### OPT-A03. Think-tag 제거 로직 3중 중복 → 공통 유틸 추출 ✅ 완료
- **파일**: `src/ai/utils.py` 신설, `conversation_store.py`, `rag/reranker.py` 적용
- **결과**: `RE_THINK_TAG`, `strip_think_tags()` 공통 유틸 제공
- **절감**: ~45줄

#### OPT-A04. 환경판단 로직 이중 구현 통합
- **파일**: `manual_control.py` (594~705줄 vs 723~844줄)
- **현황**: `get_ai_environment_judgment()`와 `control_manual_environment()`가 비상체크/발이기/외부순환/64케이스 판단 로직을 동일하게 반복
- **방안**: `_determine_environment_action()` 공통 판단 함수 추출, 각 함수는 판단 결과만 받아서 실행/반환
- **절감**: ~60~80줄
- **위험도**: 중간 (제어 로직이므로 충분한 검증 필요)

#### OPT-A05. `control_relay` / `control_relays_batch` 공통 로직 추출 ✅ 완료
- **파일**: `tools_executor.py`
- **결과**: `_resolve_relay_ids()` 헬퍼로 ID 해석 로직 공통화
- **절감**: ~45줄

#### OPT-A06. 재배사 루프 공통 래퍼 추출
- **파일**: `manual_control.py` 850~1031줄, `schedule_control.py` 224~327줄
- **현황**: GET_HOUSE_NAME 쿼리 → _sort_houses → for 루프 → 결과 집계 패턴이 동일
- **방안**: `_iterate_houses()` 공통 래퍼 함수 추출
- **절감**: ~30줄
- **위험도**: 중간

---

### 카테고리 B: 미사용 코드 제거 (예상 절감 ~80줄)

#### OPT-B01. `DOC_TYPE_LABELS` 이중 정의 제거 ✅ 완료
- **결과**: `document_enricher.py`에서 `document_processor.py`의 정의를 import
- **절감**: ~5줄

#### OPT-B02. `_REASONING_HINT_KEYWORDS` + `_DEFAULT_REASONING_TERMS` 통합 ✅ 완료
- **결과**: 하나의 리스트로 통합, 하위 호환 별칭 유지
- **절감**: ~20줄

#### OPT-B03. `logs.py` 미사용 상수 제거 ✅ 완료
- **결과**: 5개 미사용 상수 제거, `__all__` 정리
- **절감**: ~12줄

#### OPT-B04. `config/constants.py` 중복 상수 정리
- **현황**: `CHROMA_EMBEDDING_DIM`, `EMBEDDING_MODEL_NAME` 등이 `settings` 객체와 중복
- **방안**: settings 기반으로 통합, 미참조 상수 제거
- **절감**: ~8줄

#### OPT-B05. 인사말 정규식 중복 통합
- **파일**: `llm_client.py` ~2315줄 `_GREETING_RE`, `query_handler_simple.py` ~110줄 `_GREETING_RE_HYBRID`
- **방안**: `src/ai/utils.py`에 통합 정의
- **절감**: ~10줄

#### OPT-B06. `config/mappers.py` 릴레이 핀 키 이중 등록 제거
- **현황**: semantic 키와 relay 핀 키가 동일 파일에 이중 등록, `control_common.py`에서도 관리
- **방안**: semantic 매핑에서 역매핑 자동 생성
- **절감**: ~20줄

---

### 카테고리 C: 구조 개선 / 가독성 향상 (줄 수 변화 미미, 품질 향상)

#### OPT-C01. `get_llm_response_with_tools()` 단계별 분할
- **파일**: `llm_client.py` ~2393~2745줄 (약 350줄)
- **현황**: 단일 함수에 도구 호출 판단 → 도구 실행 → 최종 답변 생성 → 후처리가 모두 포함
- **방안**:
  - `_determine_tool_calls()` : 도구 호출 판단
  - `_execute_tools()` : 도구 실행 및 결과 수집
  - `_generate_final_answer()` : 최종 답변 생성
  - `_postprocess_answer()` : 후처리 (URL 정리, 출처 추가 등)
- **효과**: 가독성/유지보수성 대폭 향상, 개별 단계 테스트 가능

#### OPT-C02. `search_farm_knowledge()` 하위 검색 로직 분리
- **파일**: `tools_executor.py` (약 280줄)
- **방안**:
  - `_search_vector_collections()` : 벡터DB 컬렉션별 검색
  - `_deduplicate_results()` : 중복 제거
  - `_apply_reranker()` : Reranker 적용/바이패스
- **효과**: 복잡도 감소

#### OPT-C03. `initialize_app()` 단계별 분할
- **파일**: `startup.py` 29~188줄 (약 160줄)
- **방안**: `_init_ollama()`, `_init_chromadb()`, `_init_postgresql()`, `_init_scheduler()` 분리
- **효과**: 초기화 실패 시 디버깅 용이

#### OPT-C04. `control_all_manual()` 모드별 분할
- **파일**: `manual_control.py` 850~1031줄 (약 182줄)
- **방안**: 수동/AI/알고리즘/휴지기 모드별 핸들러 함수 분리
- **효과**: 각 모드 독립적 수정 가능

#### OPT-C05. try-except 중첩 정리
- **파일**: `llm_client.py`, `tools_executor.py`, `mcp_client.py`
- **현황**: 최대 3~4단 중첩 (외부 try → 내부 try → transport별 try)
- **방안**: fallback 체인을 리스트 기반 루프로 정리
- **효과**: 가독성 향상, 새 fallback 추가 시 코드 변경 최소화

---

### 카테고리 D: 설정/상수 정리 (예상 절감 ~30줄)

#### OPT-D01. `setup_api_logger` → `_setup_logger_impl` 통합
- **파일**: `logs.py` 172~220줄
- **현황**: 두 함수가 log_level 파싱, 핸들러 설정, formatter 등 거의 동일
- **방안**: `_setup_logger_impl`에 `file_handler_factory` 파라미터 추가
- **절감**: ~25줄

#### OPT-D02. Ollama URL/모델명 접근 경로 통합
- **현황**: `startup.py`가 `os.getenv()` 직접 사용, 다른 파일은 `get_ollama_url()` 사용
- **방안**: 모두 `config/constants.py`의 함수 경유로 통합
- **절감**: ~5줄 + 설정 불일치 버그 방지

#### OPT-D03. 릴레이 매핑 원천 데이터 일원화
- **현황**: `config/mappers.py`와 `control_common.py`에 이중 관리
- **방안**: `control_common.py`를 원천으로, `mappers.py`는 자동 파생
- **효과**: 매핑 불일치 버그 방지

---

### 카테고리 E: 함수 위치 재배치 (파일 책임 분리)

#### OPT-E01. 릴레이 제어 보조 함수 → control 모듈 이동
- **파일**: `tools_executor.py` → `src/control/control_common.py`
- **현황**: `_get_ai_judgment_safe()`, `_build_ai_conflict()` 함수가 tools_executor.py에 위치하나, 실제로는 릴레이 제어(AI 판단/충돌 비교) 전용 로직
- **방안**: `control_common.py`로 이동, tools_executor.py에서 import
- **효과**: tools_executor.py는 도구 실행만 담당, 제어 로직은 control 모듈에 집중
- **위험도**: 낮음

#### OPT-E02. ID 정규화 함수 → 공통 유틸 이동
- **파일**: `tools_executor.py` → `src/ai/utils.py` 또는 `src/control/control_common.py`
- **현황**: `_normalize_id()`, `_resolve_relay_ids()` 함수가 tools_executor.py에 위치하나, 범용 유틸리티 성격
- **방안**: `src/ai/utils.py`에 `normalize_id()` 이동, `_resolve_relay_ids()`는 control_common.py로
- **효과**: 다른 모듈에서도 ID 정규화 재사용 가능
- **위험도**: 낮음

#### OPT-E03. Tool 결과 정제 함수 그룹 → `tool_result_refiner.py` 분리
- **파일**: `llm_client.py` (~256줄)
- **현황**: `_refine_tool_result()`, `_refine_search_result()`, `_refine_realtime_data()`, `_refine_relay_result()`, `_refine_web_result()` 등 6개 함수가 llm_client.py에 위치
- **방안**: `src/ai/tool_result_refiner.py` 신설, 결과 정제 로직만 분리
- **절감**: llm_client.py에서 ~256줄 감소 (신규 파일로 이동)
- **효과**: llm_client.py의 책임 경량화, 도구 결과 정제 로직 독립 관리
- **위험도**: 낮음 (import 경로만 변경)

#### OPT-E04. 응답 필터/정리 함수 그룹 → `response_filter.py` 분리
- **파일**: `llm_client.py` (~917줄)
- **현황**: `clean_llm_response()`, `_finalize_user_facing_answer()`, `_strip_hallucinated_urls()`, `_build_structured_result()`, 인사말 감지, 한국어 감지 등 응답 후처리 함수가 llm_client.py 전체의 ~35% 차지
- **방안**: `src/ai/response_filter.py` 신설
- **절감**: llm_client.py에서 ~917줄 감소 (신규 파일로 이동)
- **효과**: llm_client.py가 ~1,430줄로 축소 (현재 ~2,605줄), LLM 통신과 응답 후처리 책임 분리
- **위험도**: 중간 (함수 간 의존성 정리 필요)

---

### 카테고리 F: 추가 중복 발견 (2차 분석)

#### OPT-F01. ID 정규화 이중 구현 통합
- **파일**: `tools_executor.py` `_normalize_id()` vs `control_common.py` `_coerce_numeric_id()`
- **현황**: 둘 다 문자열 ID를 정수로 변환하는 동일 목적의 함수
- **방안**: 하나로 통합 (control_common.py의 `_coerce_numeric_id()`를 기준으로)
- **절감**: ~15줄
- **위험도**: 낮음

#### OPT-F02. 한국어 감지 함수 이중 구현 통합
- **파일**: `llm_client.py` `_is_korean_query()` vs `_line_has_korean()`
- **현황**: 둘 다 한국어 문자 포함 여부 판별, 정규식 패턴도 거의 동일
- **방안**: `_has_korean()` 하나로 통합, 용도별로 래핑
- **절감**: ~15줄
- **위험도**: 낮음

#### OPT-F03. 인사말 정규식 이중 정의 통합
- **파일**: `llm_client.py` `_GREETING_RE` vs `query_handler_simple.py` `_GREETING_RE_HYBRID`
- **현황**: 거의 동일한 인사말 패턴이 두 곳에 별도 정의
- **방안**: `src/ai/utils.py`에 통합 정의, 양쪽에서 import
- **절감**: ~10줄
- **위험도**: 낮음

#### OPT-F04. 센서 매핑 데이터 이중 관리
- **파일**: `llm_client.py` `_SENSOR_SHORT` vs `config/mappers.py` `SENSOR_FIELD_MAPPING`
- **현황**: 센서 이름 ↔ DB 필드 매핑이 두 곳에서 독립 관리, 불일치 위험
- **방안**: `config/mappers.py`를 원천으로 통합
- **절감**: ~20줄
- **효과**: 센서 추가/변경 시 한 곳만 수정
- **위험도**: 낮음

#### OPT-F05. 릴레이 상태 조회 함수 이중 구현
- **파일**: `tools_executor.py` `get_relay_status()` vs `control_common.py` `read_latest_relay_info()`
- **현황**: 둘 다 MCP API를 통해 릴레이 상태를 조회하지만, 반환 형식이 약간 다름
- **방안**: `control_common.py`의 `read_latest_relay_info()`를 기준으로 통합, `get_relay_status()`는 래핑
- **절감**: ~25줄
- **위험도**: 중간 (반환값 형식 차이 확인 필요)

#### OPT-F06. 모델명 조회 함수 이중 정의
- **파일**: `config/constants.py` `get_model_name()` vs `llm_client.py` `_get_model_name()`
- **현황**: 둘 다 환경변수에서 Ollama 모델명을 조회, 기본값만 약간 다름
- **방안**: `config/constants.py`의 `get_model_name()`으로 통합
- **절감**: ~10줄
- **위험도**: 낮음

#### OPT-F07. `startup.py` 직접 psycopg2 사용 → `db_session` 통합
- **파일**: `startup.py`
- **현황**: `psycopg2.connect()`를 직접 호출하여 DB 접속 확인, 다른 모듈은 `connection.py`의 `db_session()` 사용
- **방안**: `db_session()` 사용으로 통합
- **절감**: ~10줄
- **효과**: DB 접속 경로 일원화, 커넥션 풀 활용
- **위험도**: 낮음

#### OPT-F08. `_build_farm_info_text()` 직접 SQL 실행 → 쿼리 모듈 사용
- **파일**: `llm_client.py`
- **현황**: 함수 내부에서 직접 SQL 쿼리 문자열과 `db_session()` 사용
- **방안**: `queries.py`에 정의된 쿼리 사용, 데이터 조회는 별도 함수로 분리
- **절감**: ~15줄
- **효과**: SQL 쿼리 중앙 관리
- **위험도**: 낮음

---

## 3. 작업 우선순위 및 일정

### Phase 1: 안전한 중복 제거 (고효과/저위험) ✅ 완료

| 순서 | 항목 | 절감 | 상태 |
|------|------|------|------|
| 1-1 | OPT-A01: filter/clean 통합 | ~90줄 | ✅ |
| 1-2 | OPT-A02: Ollama payload 공통화 | ~70줄 | ✅ |
| 1-3 | OPT-A03: Think-tag 유틸 추출 | ~45줄 | ✅ |
| 1-4 | OPT-A05: 릴레이 제어 공통화 | ~45줄 | ✅ |
| 1-5 | OPT-B01~B03: 미사용 코드 제거 | ~37줄 | ✅ |
| | **Phase 1 실적** | **~287줄** | |

### Phase 2: 제어 로직 중복 제거 (고효과/중위험)

| 순서 | 항목 | 절감 | 위험도 |
|------|------|------|--------|
| 2-1 | OPT-A04: 환경판단 통합 | ~70줄 | 중간 |
| 2-2 | OPT-A06: 재배사 루프 래퍼 | ~30줄 | 중간 |
| 2-3 | OPT-D01: 로거 통합 | ~25줄 | 낮음 |
| 2-4 | OPT-D02~D03: 설정 정리 | ~10줄 | 낮음 |
| | **Phase 2 소계** | **~135줄** | |

### Phase 3: 추가 중복 제거 (2차 분석 발견, 저~중위험)

| 순서 | 항목 | 절감 | 위험도 |
|------|------|------|--------|
| 3-1 | OPT-F01: ID 정규화 통합 | ~15줄 | 낮음 |
| 3-2 | OPT-F02: 한국어 감지 통합 | ~15줄 | 낮음 |
| 3-3 | OPT-F03: 인사말 정규식 통합 | ~10줄 | 낮음 |
| 3-4 | OPT-F04: 센서 매핑 통합 | ~20줄 | 낮음 |
| 3-5 | OPT-F05: 릴레이 상태 조회 통합 | ~25줄 | 중간 |
| 3-6 | OPT-F06: 모델명 조회 통합 | ~10줄 | 낮음 |
| 3-7 | OPT-F07: startup DB 접속 통합 | ~10줄 | 낮음 |
| 3-8 | OPT-F08: farm_info SQL 통합 | ~15줄 | 낮음 |
| 3-9 | OPT-B04~B06: 잔여 미사용 코드 | ~38줄 | 낮음 |
| | **Phase 3 소계** | **~158줄** | |

### Phase 4: 함수 위치 재배치 / 파일 분리 (구조 개선)

| 순서 | 항목 | 효과 | 위험도 |
|------|------|------|--------|
| 4-1 | OPT-E01: 제어 보조 함수 이동 | 책임 분리 | 낮음 |
| 4-2 | OPT-E02: ID 정규화 함수 이동 | 재사용성 향상 | 낮음 |
| 4-3 | OPT-E03: tool_result_refiner.py 분리 | llm_client ~256줄 감소 | 낮음 |
| 4-4 | OPT-E04: response_filter.py 분리 | llm_client ~917줄 감소 | 중간 |

### Phase 5: 대형 함수 구조 개선 (품질 향상/줄 수 동일)

| 순서 | 항목 | 효과 | 위험도 |
|------|------|------|--------|
| 5-1 | OPT-C01: Tool Use 루프 분할 | 가독성 대폭 향상 | 중간 |
| 5-2 | OPT-C02: 검색 함수 분할 | 복잡도 감소 | 낮음 |
| 5-3 | OPT-C03: 초기화 분할 | 디버깅 용이 | 낮음 |
| 5-4 | OPT-C04: 제어 모드 분할 | 유지보수성 향상 | 중간 |
| 5-5 | OPT-C05: try-except 정리 | 가독성 향상 | 중간 |

---

## 4. 예상 결과

| 구분 | Phase 1 완료 후 | 전체 완료 후 | 변화 |
|------|----------------|-------------|------|
| 전체 줄 수 | ~15,570줄 | ~15,080줄 | **~690줄 절감 (4.4%)** |
| 중복 코드 | 10건 잔여 | 0건 | 전량 해소 |
| llm_client.py | ~2,605줄 | ~1,430줄 | 45% 축소 (파일 분리) |
| 50줄+ 함수 | 18개 | 8~10개 | 절반 이하 |
| 3단+ try-except | 5곳 | 0곳 | 전량 정리 |

---

## 5. 작업 규칙

1. **각 OPT 항목 완료 후 `ast.parse()` 구문 검증** 필수
2. **Phase별 완료 후 서비스 재시작 → 기능 테스트** 필수
3. 함수 시그니처 변경 시 **모든 호출처 확인** 필수
4. 제어 로직(Phase 2) 수정 시 **릴레이 실제 동작 확인** 필수
5. 기능 회손이 의심되면 **즉시 중단하고 git revert**

---

## 6. 참고: 1차 최적화 이력

- 실행일: 2026-02-27
- 대상: agri_ai_core/ 27개 항목
- 결과: 약 550줄 절감, 26개 파일 구문 검증 통과
- 상세: `docs/dev/CodeOptimizing.md`

## 7. 참고: 2차 최적화 Phase 1 이력

- 실행일: 2026-03-08
- 완료 항목: OPT-A01, A02, A03, A05, B01, B02, B03 (7개)
- 결과: 약 287줄 절감, 구문 검증 통과
- 영향 파일: `llm_client.py`, `tools_executor.py`, `conversation_store.py`, `rag/reranker.py`, `rag/document_enricher.py`, `logs.py`, `src/ai/utils.py`(신설)
