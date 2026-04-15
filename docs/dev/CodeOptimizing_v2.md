# agri_ai_core 코드 최적화 작업계획서 v2

**작성일**: 2026-03-02
**분석 대상**: agri_ai_core/ (57개 파일, 16,459줄)
**원칙**: 현재 기능을 절대 변경하지 않으며, 코드 구조와 유지보수성만 개선

---

## 분석 요약

| 항목 | 건수 |
|------|------|
| Ollama 페이로드 빌드 중복 | 4곳 (llm_client.py 내부) |
| `/api/generate` 호출 패턴 중복 | 4개 파일 |
| float 변환 함수 중복 | 3개 함수 |
| 인사 정규식 중복 | 2곳 (완전 동일) |
| `logger.error` + `traceback.format_exc()` 패턴 | 17개 파일, 44회 |
| 모델명 하드코딩/결정 함수 이원화 | 4곳 (기본값 불일치) |
| 응답 필터 체인 반복 | 4곳 (llm_client.py 내부) |
| device_settings 중복 딕셔너리 | 4곳 (2곳 완전 동일) |
| 과대 파일 (1,000줄 이상) | 2개 (2,469줄 + 1,082줄) |

---

## 최적화 항목

### [OPT-v2-01] Ollama 페이로드 빌드 함수 통합 (llm_client.py)
- **우선순위**: 높음
- **예상 절감**: ~40줄
- **현황**: `_package_ollama_chat`, `_direct_ollama_chat`, `_mcp_ollama_chat`, `_log_llm_request_json` 4곳에서 동일한 payload 딕셔너리 구성 로직 반복
- **개선**: `_build_chat_payload(model, messages, options, tools, keep_alive, think)` 공통 빌더 함수 추출
- **파일**: `src/ai/llm_client.py` (194-206, 279-291, 322-334, 369-379)

### [OPT-v2-02] `/api/generate` LLM 호출 패턴 통합
- **우선순위**: 높음
- **예상 절감**: ~80줄
- **현황**: 4개 파일에서 거의 동일한 구조 반복
  - `src/ai/rag/document_enricher.py` → `_call_llm()` (42-78)
  - `src/control/ai_control.py` → `_call_llm()` (397-437)
  - `src/ai/rag/reranker.py` → `rerank_results()` 내부 (113-159)
  - `src/ai/conversation_store.py` → `summarize_conversation()` 내부 (196-225)
- **개선**: `src/ai/llm_utils.py`에 `generate_text(prompt, temperature, num_predict, timeout)` 공통 함수 추출
- **동일 패턴**:
  ```python
  ollama_url = get_ollama_url()
  model_name = get_model_name()
  payload = {"model": model_name, "prompt": prompt, "stream": False, "options": {...}}
  status_code, data, error_text = mcp_http_request("POST", f"{ollama_url}/api/generate", ...)
  response_text = data.get("response", "") if isinstance(data, dict) else ""
  ```

### [OPT-v2-03] float 변환 함수 통합
- **우선순위**: 중간
- **예상 절감**: ~15줄
- **현황**: 3개 함수가 동일 목적으로 존재
  - `src/control/ai_control.py:72` → `_to_float(value)` (None 반환)
  - `src/utils/conversion.py:21` → `safe_float(value, default)` (기본값 반환)
  - `src/utils/validators.py:30` → `clean_sensor_value(value)` (정규식 파싱 포함)
- **개선**: `ai_control.py`의 `_to_float`를 `safe_float(value, default=None)`으로 대체

### [OPT-v2-04] 인사 정규식 패턴 통합
- **우선순위**: 중간
- **예상 절감**: ~5줄
- **현황**: 완전히 동일한 정규식이 2곳에 정의
  - `src/ai/llm_client.py:2130` → `_GREETING_RE`
  - `src/ai/query_handler_simple.py:106` → `_GREETING_RE_HYBRID`
- **개선**: 한곳에서 정의하고 import하여 사용

### [OPT-v2-05] 응답 필터 체인 함수화 (llm_client.py)
- **우선순위**: 높음
- **예상 절감**: ~30줄
- **현황**: 동일한 3단계 필터 체인이 4회 반복
  ```python
  candidate = _strip_reasoning_paragraphs(candidate)
  candidate = _strip_non_korean_reasoning_for_korean_query(candidate, ...)
  candidate = _force_korean_surface_for_korean_query(candidate, ...)
  ```
  - 줄 1643-1648, 1689-1698, 1760-1766, 1794-1799
- **개선**: `_apply_korean_filters(text, user_query, user_lang)` 래퍼 함수 추출
- **파일**: `src/ai/llm_client.py`

### [OPT-v2-06] `logger.error` + `traceback.format_exc()` → `logger.exception()` 통합
- **우선순위**: 낮음 (동작 동일, 코드 정리 목적)
- **예상 절감**: ~44줄
- **현황**: 17개 파일, 44곳에서 2줄 패턴 반복
  ```python
  logger.error(f"오류: {e}")
  logger.error(traceback.format_exc())
  ```
- **개선**: `logger.exception(f"오류: {e}")` 1줄로 대체 (동일 출력)
- **대상 파일**: startup.py, llm_client.py, query_handler_simple.py, tools_executor.py, chunker.py, document_processor.py, model_trainer.py, data_analyzer.py, growth_rag_processor.py, operations.py, loader.py, client.py, manual_control.py, ai_control.py, task_scheduler.py, schedule_control.py, relay_manager.py

### [OPT-v2-07] 모델명 결정 로직 통합
- **우선순위**: 중간
- **예상 절감**: ~10줄
- **현황**: 모델명 결정 로직이 2곳에 존재하며 기본값이 불일치
  - `config/constants.py:58` → `get_model_name()` → 기본값 `"qwen3:32b"`
  - `src/ai/llm_client.py:692` → `_get_model_name()` → 기본값 `"qwen3:14b"`
  - `src/ai/conversation_store.py:200` → 인라인 로직 → 기본값 `"qwen3:32b"`, 속성명 `"model_name"` (불일치)
- **개선**: `conversation_store.py`는 `get_model_name()` 호출로 대체. `_get_model_name()`의 기본값을 `get_model_name()`과 통일

### [OPT-v2-08] device_settings 딕셔너리 팩토리 함수화 (manual_control.py)
- **우선순위**: 낮음
- **예상 절감**: ~15줄
- **현황**: 줄 551, 564, 576, 706에서 동일 구조 딕셔너리 반복 (564, 576은 완전 동일)
- **개선**: `_make_device_settings(heater, fog, indoor_heater, valve)` 팩토리 함수 추출

### [OPT-v2-09] control_all_manual / control_all_ai 공통 구조 추출
- **우선순위**: 낮음
- **예상 절감**: ~40줄
- **현황**: 두 함수(730-902, 909-986)가 DB조회→하우스순회→결과집계→에러핸들링 동일 구조
- **개선**: `_execute_for_all_houses(control_fn)` 공통 프레임 함수 추출
- **파일**: `src/control/manual_control.py`

### [OPT-v2-10] data_analyzer.py 미사용 헬퍼 활용
- **우선순위**: 낮음
- **예상 절감**: ~15줄
- **현황**: `_collect_day_night_values()` 헬퍼가 존재하나, `analyze_temperature_conditions()`에서는 미사용하고 동일 로직을 수동 작성
- **개선**: `analyze_temperature_conditions()`에서 `_collect_day_night_values()` 활용
- **파일**: `src/ai/learning/data_analyzer.py` (268-294)

---

## 우선순위별 실행 계획

### Phase 1 (높은 우선순위) — 약 150줄 절감
| 항목 | 작업 |
|------|------|
| OPT-v2-01 | Ollama 페이로드 빌더 공통 함수 추출 |
| OPT-v2-02 | `/api/generate` 호출 공통 유틸리티 함수 추출 |
| OPT-v2-05 | 응답 필터 체인 래퍼 함수 추출 |

### Phase 2 (중간 우선순위) — 약 30줄 절감
| 항목 | 작업 |
|------|------|
| OPT-v2-03 | float 변환 함수 통합 |
| OPT-v2-04 | 인사 정규식 상수 통합 |
| OPT-v2-07 | 모델명 결정 로직/기본값 통일 |

### Phase 3 (낮은 우선순위) — 약 115줄 절감
| 항목 | 작업 |
|------|------|
| OPT-v2-06 | logger.exception() 전환 (17개 파일) |
| OPT-v2-08 | device_settings 팩토리 함수화 |
| OPT-v2-09 | control_all 공통 구조 추출 |
| OPT-v2-10 | data_analyzer 헬퍼 활용 |

---

## 총 예상 효과

| 구분 | 줄 수 |
|------|-------|
| Phase 1 | ~150줄 절감 |
| Phase 2 | ~30줄 절감 |
| Phase 3 | ~115줄 절감 |
| **합계** | **~295줄 절감** |

**비고**: 단순 줄 수 절감보다 중요한 것은 **유지보수성 향상**입니다. 특히 OPT-v2-02(LLM 호출 통합)와 OPT-v2-07(모델명 통일)은 향후 모델 변경 시 1곳만 수정하면 되므로 실질적 효과가 큽니다.
