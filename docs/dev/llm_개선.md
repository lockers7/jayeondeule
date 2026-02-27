# LLM 대화 처리 파이프라인 개선안

> 작성일: 2026-02-26
> 대상: `agri_ai_core/src/ai/llm_client.py` 중심, 관련 모듈 포함
> 원칙: **현재 답변 품질 유지**, LLM 주도 Tool Use 구조 보존, 인프라 레벨 최적화

---

## 0. 현황 요약 (로그 기반 분석)

### 0-1. 분석 대상 로그

| 날짜 | 로그 파일 | 크기 | 질문 수 |
|------|----------|------|---------|
| 2/25 | `llm_2026_02_25.log` | 11MB | 8건 |
| 2/26 | `llm_2026_02_26.log` | 1.4MB | 2건 |

### 0-2. 핵심 수치

| 항목 | 2/25 평균 | 2/26 평균 | 비고 |
|------|----------|----------|------|
| 총 응답 시간 | **249초** (4분 9초) | **71초** | 스트리밍 모드 도입 효과 |
| LLM 1차 호출 (답변 생성) | 123~232초 | 49~94초 | |
| LLM 2차 호출 (문체교정) | 19~131초 | 8.8~22초 | **항상 실행** |
| 생성 텍스트 중 필터링 비율 | **60~89%** | 68~75% | 대부분 `<think>` 블록 |
| 도구 사용 비율 | 0/8 (0%) | 1/2 (50%) | 2/25 전체 미사용 |
| sources 반환 비율 | 0/8 (0%) | 0/2 (0%) | 출처 항상 빈 배열 |

### 0-3. 핵심 문제 요약

```
[사용자 질문] → LLM 1차 호출 (답변 생성, num_predict=5120)
                     ↓
              5~6단계 필터링 (60~89% 텍스트 삭제)
                     ↓
              LLM 2차 호출 (문체교정, num_predict=5120) ← 항상 실행
                     ↓
              5~6단계 필터링 (재실행)
                     ↓
              [최종 답변] ← 원본 대비 10~30% 분량만 전달
```

**문제**: 2회 LLM 호출 × 2회 필터링 파이프라인 = 전체 시간의 90% 이상 소비

---

## 1. 호출 구조 간소화 — 조건부 문체교정

### 1-1. 현재 구조 (코드 증거)

`llm_client.py:1496` — `_enforce_honorific_response()`는 reasoning 흔적이 없는 **모든** 답변에 실행:
```python
if not _contains_reasoning_trace(candidate):
    candidate = _enforce_honorific_response(...)  # 무조건 2차 LLM 호출
```

`llm_client.py:1366-1367` — 환경변수 `FORCE_HONORIFIC_RESPONSE` 기본값 `"true"`:
```python
def _force_honorific_response_enabled() -> bool:
    return _is_true(os.getenv("FORCE_HONORIFIC_RESPONSE", "true"))
```

**2/25 로그 증거**: 8건 모두 2차 호출 발생, 문체교정에 19~131초 추가 소요

### 1-2. 개선안: 빠른 존댓말 판별 → 조건부 호출

LLM 2차 호출 전에 **정규식 기반 빠른 판별**을 추가하여, 이미 존댓말인 답변은 스킵:

```python
_HONORIFIC_ENDINGS = re.compile(
    r"(합니다|습니다|세요|해요|드립니다|주세요|겠습니다|됩니다|입니다|바랍니다|있습니다|없습니다)"
    r"[.!?\s]*$",
    re.MULTILINE,
)
_BANMAL_ENDINGS = re.compile(
    r"(한다|된다|이다|있다|없다|했다|봐라|해라|하자|할게|할거야|거야)"
    r"[.!?\s]*$",
    re.MULTILINE,
)

def _needs_honorific_rewrite(text: str) -> bool:
    """반말 문장이 있거나 존댓말 비율이 낮으면 True"""
    sentences = [s.strip() for s in re.split(r'[.!?\n]', text) if s.strip()]
    if not sentences:
        return False
    banmal_count = sum(1 for s in sentences if _BANMAL_ENDINGS.search(s))
    if banmal_count > 0:
        return True  # 반말이 하나라도 있으면 교정 필요
    honorific_count = sum(1 for s in sentences if _HONORIFIC_ENDINGS.search(s))
    # 전체 문장의 70% 이상이 존댓말이면 스킵
    return honorific_count < len(sentences) * 0.7
```

적용 위치 — `_enforce_honorific_response()` 내부:
```python
def _enforce_honorific_response(...):
    candidate = (answer_text or "").strip()
    if not candidate or not _force_honorific_response_enabled():
        return candidate
    if not _needs_honorific_rewrite(candidate):   # ← 추가
        logger.info("[존댓말교정] 이미 존댓말 → 스킵")
        return candidate
    # 기존 LLM 호출 로직...
```

### 1-3. 예상 효과

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 문체교정 LLM 호출 | 100% (매번) | 10~30% (반말 감지 시만) |
| 2차 호출 소요 시간 | 19~131초 | 0초 (스킵 시) |
| 답변 품질 영향 | - | 없음 (이미 존댓말인 경우에만 스킵) |

---

## 2. `<think>` 태그 노출 방지 강화

### 2-1. 현재 문제 (코드 증거 3건)

**문제 A** — `_rewrite_to_honorific()`에 `think=False` 미설정 (`llm_client.py:1398-1403`):
```python
options={
    "temperature": 0.0,
    "top_p": 0.1,
    "top_k": 1,
    "num_predict": NUM_PREDICT,
    # think=False 누락!
},
```

**문제 B** — `_rewrite_without_reasoning()`에도 `think=False` 미설정 (`llm_client.py:1355-1360`):
```python
options={
    "temperature": 0.0,
    "top_p": 0.1,
    "top_k": 1,
    "num_predict": NUM_PREDICT,
    # think=False 누락!
},
```

**문제 C** — `_summarize_old_turns()`에 `<think>` 태그 필터 없음 (`conversation_store.py:196`):
```python
summary = data.get("response", "").strip()  # <think> 태그 포함 가능
# → 이 요약이 다음 대화의 conversation_history에 주입됨
```

### 2-2. 개선안

**A/B 수정** — 두 함수의 options에 `"think": False` 추가:
```python
options={
    "temperature": 0.0,
    "top_p": 0.1,
    "top_k": 1,
    "num_predict": NUM_PREDICT,
    "think": False,  # ← 추가
},
```

**C 수정** — 대화 요약 후 `<think>` 태그 제거:
```python
summary = data.get("response", "").strip()
# <think> 태그 제거
summary = re.sub(r"<think>.*?</think>\s*", "", summary, flags=re.DOTALL)
summary = re.sub(r"<think>.*", "", summary, flags=re.DOTALL)
```

### 2-3. 예상 효과

- `<think>` 블록 생성량 자체가 감소 (think=False 적용으로)
- 대화 히스토리 오염 차단
- 필터링 단계 부하 감소 (제거할 텍스트 자체가 줄어듦)

---

## 3. 응답 지연 직접 원인 해소

### 3-1. num_predict 고정값 문제

현재 **모든** LLM 호출에 `num_predict=5120` 고정 (`config/constants.py`):

| 호출 유도 | 용도 | 실제 필요 토큰 | 설정값 | 낭비율 |
|-----------|------|---------------|--------|--------|
| 1차 답변 생성 | Tool Use 루프 | 500~2000 | 5120 | 61~90% |
| 문체교정 | 기존 텍스트 교정 | 원문 길이 × 1.2 | 5120 | 70~98% |
| reasoning 제거 재작성 | 정리만 | 원문 길이 × 1.0 | 5120 | 80~98% |
| 대화 요약 | 3문장 이내 | ~150 | 150 | 0% (이미 적정) |

**2/25 로그 증거**: 필터링 전 원본 2000~8000자 생성 → 최종 답변 300~1200자

### 3-2. 개선안: 용도별 num_predict 차등 적용

```python
# config/constants.py에 추가
NUM_PREDICT = 5120              # 1차 답변 생성 (Tool Use) — 도구 결과 반영 필요
NUM_PREDICT_REWRITE = 2048      # 문체교정 / reasoning 제거 — 원문 축약만
```

적용 위치:
- `_rewrite_to_honorific()`: `num_predict` → `NUM_PREDICT_REWRITE`
- `_rewrite_without_reasoning()`: `num_predict` → `NUM_PREDICT_REWRITE`

### 3-3. 1차 답변 생성의 num_predict 동적 조정 (선택사항)

1차 답변 생성에서도 질문 길이 기반 동적 조정 가능:
```python
def _calc_num_predict(user_query: str, has_tool_results: bool) -> int:
    base = 2048
    if has_tool_results:
        base = 3072  # 도구 결과 요약 필요
    if len(user_query) > 500:
        base = min(base + 1024, NUM_PREDICT)
    return base
```

> **주의**: 1차 답변의 num_predict 축소는 장문 답변 품질에 영향 가능. 단계적 적용 권장.

### 3-4. 예상 효과

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 문체교정 생성 토큰 | 최대 5120 | 최대 2048 |
| 문체교정 소요 시간 | 19~131초 | ~8~52초 (추정 40% 감소) |
| reasoning 제거 소요 시간 | 동일 비율 감소 | |

---

## 4. 대화 히스토리 `<think>` 오염 차단 (보안)

### 4-1. 현재 문제

대화 요약(`_summarize_old_turns`)이 `/api/generate` 엔드포인트를 사용하며, `think=False` 옵션 불가(generate API는 options에 think 미지원).
`/no_think` 텍스트를 프롬프트에 넣어도 qwen3:32b는 여전히 `<think>` 블록 생성 가능.

### 4-2. 개선안

요약 결과에 대해 **반환 전** `<think>` 태그를 정규식으로 제거:

`conversation_store.py:_summarize_old_turns()` 수정:
```python
summary = data.get("response", "").strip() if isinstance(data, dict) else ""
if not summary:
    return None

# <think> 태그 오염 제거
import re
summary = re.sub(r"<think>.*?</think>\s*", "", summary, flags=re.DOTALL)
summary = re.sub(r"<think>.*", "", summary, flags=re.DOTALL)
summary = summary.strip()
if not summary:
    return None
```

### 4-3. 예상 효과

- 멀티턴 대화 시 이전 대화 요약에 `<think>` 블록이 주입되는 것을 차단
- 이후 대화의 1차 답변에서 `<think>` 패턴 모방 가능성 감소

---

## 5. 도구 활용률 개선

### 5-1. 현재 문제 (로그 증거)

2/25 로그에서 8건의 질문 중 **0건**이 도구를 사용:
```
질문: "○○ 딸기 농장이 어디에 있어?"  → tools=[]  (검색 미수행, 좌표 허위 생성)
질문: "농장 실시간 데이터 알려줘"      → tools=[]  (DB 조회 미수행, 일반론 답변)
질문: "딸기 재배 방법 알려줘"          → tools=[]  (웹검색/RAG 미수행, 일반 지식만)
```

도구를 사용하지 않아 **허위 정보(hallucination)** 생성 위험:
- 존재하지 않는 좌표/주소 생성
- 실시간 센서 데이터 없이 "정상입니다" 답변

### 5-2. 원인 분석

시스템 프롬프트(`tools_definition.py`)에 도구 사용 지시가 있으나,
qwen3:32b가 자체 지식으로 답변 가능하다고 판단하면 도구를 호출하지 않음.
특히 **농장 이름/위치** 같은 팩트 질문에서도 도구 미사용.

### 5-3. 개선안: 시스템 프롬프트 도구 사용 강화

시스템 프롬프트에 도구 사용 의무 규칙 강화:
```
**반드시 도구를 사용해야 하는 경우:**
- 농장/재배사의 현재 상태, 센서값, 릴레이 상태 질문 → get_farm_realtime_data 필수
- 농장 위치, 주소, 연락처 등 사실 정보 → search_farm_knowledge 필수
- 최신 재배 기술, 병충해 정보 → search_web 필수
- 절대 도구 없이 사실 정보를 추측하여 답변하지 마세요.
```

> **주의**: 프롬프트 변경은 답변 품질에 직접 영향. 현재 동작하는 프롬프트의 핵심 구조를 유지하면서 도구 사용 규칙만 추가.

---

## 6. 답변 정확성 보강 장치

### 6-1. 데이터 시점 명시

센서 데이터/DB 조회 결과에 타임스탬프 포함:
```python
# tools_executor.py의 get_farm_realtime_data 결과에 시점 추가
result = f"[데이터 조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}]\n{result}"
```

### 6-2. 출처 반환 구조 개선

현재 `sources`가 항상 빈 배열인 원인: `search_web` 도구가 호출되지 않기 때문.
→ 항목 5(도구 활용률 개선)가 선행되면 자연스럽게 해결.

추가로, RAG 검색 결과에서도 출처 수집:
```python
# tools_executor.py의 search_farm_knowledge 결과 처리 시
if tool_name == "search_farm_knowledge" and tool_result:
    # 메타데이터에서 source 추출하여 _collected_sources에 추가
```

---

## 7. growth_rag 함수 오류 수정

### 7-1. 현재 문제 (로그 증거)

2/26 로그에서 `get_growth_rag_data()` 함수 완전 실패:
```
TypeError: query_growth_data() got an unexpected keyword argument 'farm_id'
```

### 7-2. 원인

`growth_rag_processor.py`의 호출 시그니처와 실제 `queries.py`의 함수 시그니처 불일치.

### 7-3. 개선안

함수 시그니처 조사 후 호출부 수정 (별도 작업).

---

## 8. 구현 우선순위

| 순위 | 항목 | 난이도 | 효과 | 위험도 |
|------|------|--------|------|--------|
| **1** | 2. `<think>` 태그 — think=False 추가 (A/B) | 낮음 | 중 | **없음** |
| **2** | 4. 대화 요약 `<think>` 제거 (C) | 낮음 | 중 | **없음** |
| **3** | 1. 조건부 문체교정 (빠른 판별 추가) | 중 | **높음** | 낮음 |
| **4** | 3. num_predict 차등 적용 (rewrite 계열) | 낮음 | 중 | **없음** |
| **5** | 5. 도구 활용률 (프롬프트 강화) | 중 | **높음** | 중 (프롬프트 변경) |
| **6** | 6. 데이터 시점/출처 명시 | 낮음 | 중 | **없음** |
| **7** | 7. growth_rag 오류 수정 | 중 | 낮음 | 낮음 |

### 권장 단계별 적용

**1단계 (안전, 즉시 적용)**: 항목 1, 2, 3, 4
- `<think>` 태그 방지 강화 + 문체교정 조건부 호출 + num_predict 축소
- 답변 품질 변화 없이 **응답 시간 40~60% 단축** 기대

**2단계 (신중 적용)**: 항목 5, 6
- 시스템 프롬프트 수정은 답변 행동에 영향 → 충분한 테스트 후 적용
- 데이터 시점 명시는 안전하나 출력 형식 변경

**3단계 (별도 작업)**: 항목 7
- growth_rag 시그니처 조사 필요

---

## 부록: 현재 파이프라인 상세 흐름

```
query_llm_simple / query_llm_simple_stream
  │
  ├─ get_llm_response_with_tools()                    [llm_client.py:1875]
  │   ├─ get_system_prompt_with_tools()               [tools_definition.py]
  │   ├─ _ollama_chat() (1차 호출, think=False)       [llm_client.py:1959]
  │   │   ├─ tool_calls 감지 시 → execute_tool()      [tools_executor.py]
  │   │   └─ 도구 없으면 → 최종 답변
  │   │
  │   └─ _finalize_user_facing_answer()               [llm_client.py:1446]
  │       ├─ filter_llm_response()                    [1단계 필터]
  │       ├─ clean_llm_response()                     [2단계 필터]
  │       ├─ _strip_reasoning_paragraphs()            [3단계 필터]
  │       ├─ _strip_non_korean_reasoning()            [4단계 필터]
  │       ├─ _force_korean_surface()                  [5단계 필터]
  │       │
  │       ├─ _contains_reasoning_trace() 검사
  │       │   ├─ 없으면 → _enforce_honorific_response()
  │       │   │             ├─ _rewrite_to_honorific() (2차 LLM 호출, think 미설정!)
  │       │   │             ├─ filter + clean (재실행)
  │       │   │             └─ strip + force_korean (재실행)
  │       │   │
  │       │   └─ 있으면 → _rewrite_without_reasoning() (추가 LLM 호출, think 미설정!)
  │       │              ├─ filter + clean + strip (재실행)
  │       │              └─ _enforce_honorific_response() (또 다른 LLM 호출)
  │       │
  │       └─ 최종 답변 반환
  │
  └─ _save_conversation_turn()
      └─ _summarize_old_turns() (대화 요약 LLM 호출, <think> 필터 없음)
```
