# 3단계 분리형 파이프라인 구축 계획서

> **작성일:** 2026-03-29
> **목표:** 질문유형분석(LLM) → 데이터수집(시스템+LLM) → 답변작성(LLM) 3단계 분리
> **핵심 원칙:** 현재 대화 품질을 절대 훼손하지 않으며 단계적으로 전환

---

## 1. 현재 구조 분석

### 1.1 현재 흐름 (단일 LLM Tool Use 루프)

```
사용자 질문
  ↓
query_llm_simple()                    ← query_handler_simple.py:514
  ├─ 파일 처리 (process_uploaded_files)
  ├─ 기본 도구 인자 생성 (_build_default_tool_args)
  ├─ 하이브리드 컨텍스트 로드 (_load_hybrid_context)
  └─ get_llm_response_with_tools()    ← llm_client.py:2025
       └─ [Tool Use 반복 루프 최대 8회]
            반복N: LLM 호출 → 도구 자율 선택 → 도구 실행 → 결과 정제 → messages 누적
            ...
            반복N: LLM 호출 → 도구 없음 → 최종 답변 반환
  ↓
대화 저장 + 응답 반환
```

### 1.2 현재 구조의 문제점

| 문제 | 원인 | 실제 사례 |
|------|------|-----------|
| 부정확한 데이터로 답변 | LLM이 검색 결과 품질을 잘못 판단 | 11월 블로그 데이터를 3월 현재 날씨로 답변 |
| fetch_url 미호출 | LLM이 "충분하다"고 자율 판단 | Weather.com URL이 있는데 본문 미수집 |
| 재검색 미수행 | LLM이 결과 부실을 인지 못함 | 정읍정수기렌탈 글이 날씨 출처로 사용됨 |
| 센서 데이터 누락 | LLM이 일부 재배사만 조회 | "전체 재배사" 요청에 1개만 조회 |

### 1.3 현재 보유 자산 (그대로 유지할 것)

- **7개 도구**: search_web, fetch_url_content, get_farm_realtime_data, search_farm_knowledge, control_relay, delete_farm_knowledge, search_gas_price
- **도구 결과 정제 함수**: _refine_search_web, _refine_fetch_url, _refine_realtime_data, _refine_farm_knowledge, _refine_tool_result
- **대화 컨텍스트**: 하이브리드 컨텍스트 (PostgreSQL + VectorDB)
- **시스템 프롬프트**: get_system_prompt_with_tools (300+ 줄, 도구 사용 규칙)
- **답변 후처리**: _finalize_user_facing_answer, _check_answer_retry, clean_llm_response
- **스트리밍**: query_llm_simple_stream, _split_for_streaming, _report_progress
- **대화 저장**: _save_conversation_turn_hybrid, conversation_store

---

## 2. 목표 구조 (3단계 분리형)

### 2.1 전체 흐름

```
사용자 질문
  ↓
[0단계] 전처리 (기존 유지)
  ├─ 파일 처리, 기본 도구 인자, 하이브리드 컨텍스트 로드
  ↓
[1단계] 질문유형분석 (LLM 호출 1회)
  ├─ 입력: 사용자 질문 + 대화 컨텍스트
  ├─ 출력: 구조화된 분석 결과 (JSON)
  │   {
  │     "question_type": "weather",
  │     "intent": "정읍 현재 날씨와 기온 조회",
  │     "required_data": [
  │       {"tool": "search_web", "args": {"query": "정읍 오늘 날씨 기온 2026년 3월"}},
  │       {"tool": "fetch_url_content", "args": {"url_hint": "weather.com OR 기상청"}}
  │     ],
  │     "data_freshness": "realtime",
  │     "answer_format": "text_with_numbers"
  │   }
  ↓
[2단계] 데이터 수집 (시스템 주도 + LLM 보조)
  ├─ 시스템이 1단계 계획에 따라 도구를 순차/병렬 실행
  ├─ 수집 결과 품질 검증 (날짜, 관련성, 충분성)
  ├─ 부족하면 → LLM에 보충 수집 요청 (1회 추가)
  ├─ 출력: 검증된 데이터 묶음
  ↓
[3단계] 답변 작성 (LLM 호출 1회)
  ├─ 입력: 사용자 질문 + 검증된 데이터 + 대화 컨텍스트
  ├─ LLM은 데이터 기반으로만 답변 작성 (도구 호출 불가)
  ├─ 출력: 최종 답변
  ↓
[후처리] (기존 유지)
  ├─ _finalize_user_facing_answer, clean_llm_response
  ├─ 대화 저장 (_save_conversation_turn_hybrid)
  └─ 응답 반환
```

### 2.2 기존 Tool Use 루프와의 관계

```
┌─────────────────────────────────────────────────────┐
│ 기존 get_llm_response_with_tools (Tool Use 루프)    │
│                                                     │
│  반복1: LLM→질문분석+도구선택  ← 1단계로 분리       │
│  반복2: LLM→도구실행+결과확인  ← 2단계로 분리       │
│  반복3: LLM→추가도구 or 답변   ← 2단계/3단계로 분리 │
│  ...                                                │
│  반복N: LLM→최종답변           ← 3단계로 분리       │
└─────────────────────────────────────────────────────┘

분리 후에도 기존 Tool Use 루프는 삭제하지 않고 fallback으로 보존
```

---

## 3. 상세 설계

### 3.1 [1단계] 질문유형분석 모듈

**신규 파일:** `agri_ai_core/src/ai/pipeline/question_analyzer.py`

#### 3.1.1 질문 유형 분류 체계

| 유형 코드 | 설명 | 필수 도구 | 데이터 신선도 |
|-----------|------|-----------|-------------|
| `farm_sensor` | 센서/릴레이/생육 데이터 조회 | get_farm_realtime_data | realtime |
| `farm_control` | 장치 제어 요청 | control_relay (+ get_farm_realtime_data) | realtime |
| `farm_knowledge` | 농장 지식/학습 자료 조회 | search_farm_knowledge | cached |
| `farm_knowledge_delete` | 학습 자료 삭제 | delete_farm_knowledge | - |
| `weather` | 날씨/기상 정보 | search_web + fetch_url_content(기상사이트) | realtime |
| `web_search` | 일반 검색 (맛집/관광/가격 등) | search_web (+ fetch_url_content) | recent |
| `gas_price` | 주유소/유가 정보 | search_gas_price | realtime |
| `greeting` | 인사/일상 대화 | 없음 | - |
| `conversation_ref` | 이전 대화 참조 | 없음 (컨텍스트로 해결) | - |
| `complex` | 복합 질문 (여러 유형 혼합) | 유형별 도구 조합 | mixed |

#### 3.1.2 분석 LLM 프롬프트 (전용 경량 프롬프트)

```python
ANALYZER_SYSTEM_PROMPT = """당신은 사용자 질문을 분석하여 답변에 필요한 데이터 수집 계획을 JSON으로 출력하는 분석기입니다.

**출력 형식 (반드시 JSON만 출력):**
{
  "question_type": "farm_sensor|farm_control|weather|web_search|...",
  "intent": "질문의 핵심 의도를 한 문장으로",
  "required_data": [
    {
      "tool": "도구명",
      "args": { "파라미터": "값" },
      "priority": 1,
      "reason": "이 데이터가 필요한 이유"
    }
  ],
  "data_freshness": "realtime|recent|cached|any",
  "answer_format": "table|text|text_with_numbers|list|control_result",
  "multi_house": false,
  "house_ids": []
}

**분류 규칙:**
- 센서/온도/습도/CO2/릴레이/재배사 → farm_sensor (get_farm_realtime_data 필수)
- 켜/끄/제어/가동/중지 → farm_control (control_relay 필수)
- 날씨/기온/비/바람/기상 → weather (search_web + fetch_url_content 필수)
- 검색/찾아/추천/맛집/관광 → web_search (search_web 필수)
- 주유소/기름값/유가 → gas_price (search_gas_price 필수)
- 파일/학습/자료/문서 → farm_knowledge (search_farm_knowledge 필수)
- 삭제/지워/제거 + 파일명 → farm_knowledge_delete
- 안녕/감사/ㅎㅎ → greeting (도구 불필요)
- "각 재배사/전체/모든 재배사" → multi_house=true, house_ids=["1","2","3"]

**날씨 질문 특별 규칙:**
- search_web의 query에 반드시 연도+월 포함 (예: "정읍 날씨 2026년 3월")
- fetch_url_content를 반드시 포함하여 기상 사이트 본문 수집 지시
- url_hint에 신뢰할 수 있는 기상 사이트 명시 (weather.com, 기상청, accuweather)

**장치 제어 특별 규칙:**
- 제어 전 현재 상태 확인용 get_farm_realtime_data를 priority=1로 포함
- control_relay를 priority=2로 포함
- house_id='all' 제어 시 house_ids=["all"]

**복합 질문:**
- 여러 유형이 섞인 경우 question_type="complex", required_data에 모든 필요 도구 나열
"""
```

#### 3.1.3 LLM 호출 설정

```python
# 분석용 LLM 호출 (빠른 응답을 위해 최소 토큰)
def analyze_question(user_query, conversation_context, farm_id, house_id, current_datetime):
    """
    1단계: 질문유형분석
    - LLM에 질문 + 컨텍스트를 전달하여 수집 계획 JSON을 받음
    - num_predict=512 (JSON만 생성하므로 짧게)
    - temperature=0.1 (일관된 분류를 위해 낮게)
    - tools=None (도구 호출 없이 JSON 텍스트만 생성)
    """
    messages = [
        {"role": "system", "content": ANALYZER_SYSTEM_PROMPT},
        {"role": "user", "content": f"현재 시각: {current_datetime}\n농장ID: {farm_id}\n재배사ID: {house_id}\n\n질문: {user_query}"}
    ]

    if conversation_context:
        # 직전 2턴만 포함 (분석에 전체 히스토리 불필요)
        messages.insert(1, {"role": "system", "content": f"[직전 대화 맥락]\n{conversation_context}"})

    response = _ollama_chat(
        model=model_name,
        messages=messages,
        tools=None,          # 도구 미제공 (JSON 텍스트 생성만)
        options={
            "temperature": 0.1,
            "num_predict": 512,
            "num_ctx": 4096,  # 분석용으로 작은 컨텍스트 충분
        }
    )

    return _parse_analysis_json(response)
```

#### 3.1.4 규칙 기반 사전 필터 (LLM 호출 절약)

```python
# LLM 호출 전에 명확한 패턴은 규칙으로 바로 분류 (기존 _classify_topic 확장)
FAST_CLASSIFY_PATTERNS = {
    "greeting": re.compile(r'^(안녕|감사|고마|ㅎㅎ|ㅋㅋ|네|예|아니)'),
    "farm_control": re.compile(r'(켜|끄|가동|중지|작동|제어).*(팬|밸브|히터|조명|관수|릴레이)|(팬|밸브|히터|조명|관수|릴레이).*(켜|끄|가동|중지|반대|반전)'),
    "gas_price": re.compile(r'주유소|기름값|유가|휘발유|경유'),
}

def fast_classify(query):
    """규칙으로 명확히 분류 가능한 경우 LLM 호출 없이 즉시 반환"""
    for qtype, pattern in FAST_CLASSIFY_PATTERNS.items():
        if pattern.search(query):
            return qtype
    return None  # None이면 LLM 분석 필요
```

#### 3.1.5 greeting 유형의 경우 기존처럼 바로 LLM 답변 (3단계 스킵)

```python
if analysis.question_type == "greeting":
    # 인사/일상 대화는 도구 없이 바로 3단계 답변 생성
    return await generate_answer(user_query, collected_data=None, ...)
```

---

### 3.2 [2단계] 데이터 수집 모듈

**신규 파일:** `agri_ai_core/src/ai/pipeline/data_collector.py`

#### 3.2.1 핵심 설계 원칙

1. **시스템이 주도**: LLM이 아닌 코드가 도구 실행 순서와 조건을 제어
2. **결과 검증**: 수집된 데이터의 날짜, 관련성, 충분성을 프로그래밍적으로 검증
3. **보충 수집**: 검증 실패 시 query 수정 재검색 또는 fetch_url 추가 실행
4. **기존 도구 재사용**: tools_executor.execute_tool()을 그대로 호출

#### 3.2.2 데이터 수집 실행기

```python
class DataCollector:
    """
    1단계 분석 결과(required_data)에 따라 도구를 실행하고 결과를 검증하는 모듈
    """

    def __init__(self, default_tool_args, current_datetime):
        self.default_tool_args = default_tool_args
        self.current_datetime = current_datetime
        self.collected_data = []      # 수집된 데이터
        self.collected_sources = []   # 출처 URL
        self.tools_used = []          # 사용된 도구 목록

    async def collect(self, analysis_result):
        """
        분석 결과의 required_data를 순차 실행하고 결과를 검증
        """
        required_data = analysis_result.get("required_data", [])
        data_freshness = analysis_result.get("data_freshness", "any")

        # priority 순서로 정렬하여 실행
        sorted_tasks = sorted(required_data, key=lambda x: x.get("priority", 99))

        for task in sorted_tasks:
            tool_name = task["tool"]
            tool_args = self._merge_args(tool_name, task.get("args", {}))

            # 도구 실행
            result = execute_tool(tool_name, tool_args)
            refined = _refine_tool_result(tool_name, result, analysis_result.get("intent", ""))

            # 결과 검증
            validation = self._validate_result(tool_name, refined, data_freshness)

            if validation["valid"]:
                self.collected_data.append({
                    "tool": tool_name,
                    "result": refined,
                    "validation": validation
                })
                self.tools_used.append(tool_name)
                # 출처 수집 (search_web의 경우)
                if tool_name == "search_web":
                    self._collect_sources(result)
            else:
                # 검증 실패 → 보충 수집
                補充결과 = await self._补充_collect(tool_name, task, validation)
                if 補充결과:
                    self.collected_data.append(補充결과)

        return {
            "data": self.collected_data,
            "sources": self.collected_sources,
            "tools_used": self.tools_used,
            "sufficient": self._check_sufficiency(analysis_result)
        }
```

#### 3.2.3 결과 검증기

```python
def _validate_result(self, tool_name, result, freshness_requirement):
    """
    수집 결과의 품질을 프로그래밍적으로 검증

    Returns:
        {"valid": bool, "issues": [], "suggestions": []}
    """
    issues = []
    suggestions = []

    # 1. 빈 결과 체크
    if not result or len(result.strip()) < 50:
        issues.append("결과가 비어있거나 너무 짧음")
        suggestions.append("query를 수정하여 재검색 필요")

    # 2. 날짜 신선도 체크 (realtime 요구 시)
    if freshness_requirement == "realtime" and tool_name == "search_web":
        date_check = self._check_data_freshness(result)
        if not date_check["is_fresh"]:
            issues.append(f"데이터가 최신이 아님: {date_check['detected_date']}")
            suggestions.append("날짜를 포함한 query로 재검색 또는 fetch_url 필요")

    # 3. 관련성 체크 (검색 결과가 질문과 무관한 경우)
    if tool_name == "search_web":
        relevance = self._check_relevance(result)
        if relevance["score"] < 0.3:
            issues.append(f"검색 결과와 질문의 관련성이 낮음 (score={relevance['score']:.1f})")
            suggestions.append("검색 query 수정 필요")

    # 4. 센서 데이터 완전성 체크
    if tool_name == "get_farm_realtime_data":
        if "sensor" not in result.lower() and "온도" not in result:
            issues.append("센서 데이터가 결과에 포함되지 않음")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "suggestions": suggestions
    }
```

#### 3.2.4 날짜 신선도 검증기

```python
def _check_data_freshness(self, result):
    """
    검색 결과에서 날짜를 추출하여 현재 날짜와 비교

    - "2024년 11월" 같은 패턴 감지
    - 현재 월과 1개월 이상 차이나면 "not fresh"
    """
    import re
    from datetime import datetime

    now = datetime.now()

    # 날짜 패턴들
    date_patterns = [
        r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',  # 2024년 11월 17일
        r'(\d{4})\.(\d{1,2})\.(\d{1,2})',             # 2024.11.17
        r'(\d{4})-(\d{1,2})-(\d{1,2})',               # 2024-11-17
        r'(\d{4})년\s*(\d{1,2})월',                    # 2024년 11월
    ]

    detected_dates = []
    for pattern in date_patterns:
        matches = re.findall(pattern, result)
        for match in matches:
            year = int(match[0])
            month = int(match[1])
            detected_dates.append((year, month))

    if not detected_dates:
        return {"is_fresh": True, "detected_date": "날짜 미감지"}  # 날짜 없으면 통과

    # 가장 최근 날짜 기준
    latest = max(detected_dates, key=lambda d: d[0] * 12 + d[1])
    latest_year, latest_month = latest

    # 현재 월과 비교
    months_diff = (now.year - latest_year) * 12 + (now.month - latest_month)

    return {
        "is_fresh": months_diff <= 1,  # 1개월 이내면 신선
        "detected_date": f"{latest_year}년 {latest_month}월",
        "months_diff": months_diff
    }
```

#### 3.2.5 보충 수집 전략

```python
async def _supplement_collect(self, tool_name, original_task, validation):
    """
    검증 실패 시 보충 수집 (최대 2회 시도)
    """
    suggestions = validation.get("suggestions", [])

    for attempt in range(2):
        if "재검색" in str(suggestions) and tool_name == "search_web":
            # query에 날짜 추가하여 재검색
            original_query = original_task["args"].get("query", "")
            now = datetime.now()
            new_query = f"{original_query} {now.year}년 {now.month}월"
            result = execute_tool("search_web", {"query": new_query, "n_results": 5})

        elif "fetch_url" in str(suggestions) and tool_name == "search_web":
            # 검색 결과 중 신뢰 가능한 URL에서 본문 수집
            urls = self._extract_trustworthy_urls(self.collected_data)
            for url in urls[:2]:
                fetch_result = execute_tool("fetch_url_content", {"url": url})
                if fetch_result and len(fetch_result) > 200:
                    return {"tool": "fetch_url_content", "result": fetch_result}

        else:
            break

    return None
```

#### 3.2.6 유형별 수집 전략 (시스템 강제 규칙)

```python
# 1단계 분석 결과와 무관하게, 유형별로 반드시 실행해야 하는 도구
MANDATORY_TOOLS = {
    "weather": [
        # 날씨는 반드시 search_web + 기상 사이트 fetch_url
        {"tool": "search_web", "args_template": {"query": "{location} 오늘 날씨 기온 {year}년 {month}월"}},
        {"tool": "fetch_url_content", "url_selector": "weather_site",
         "fallback_urls": [
             "https://weather.com/ko-KR/weather/today/l/{location_code}",
             "https://www.weather.go.kr/w/obs-climate/land/city-obs.do",
         ]},
    ],
    "farm_sensor": [
        # multi_house=true이면 house_ids 각각에 대해 실행
        {"tool": "get_farm_realtime_data", "args_template": {"data_type": "all"}},
        {"tool": "search_farm_knowledge", "args_template": {"query": "{intent}"}},
    ],
    "farm_control": [
        # 제어 전 현재 상태 반드시 조회
        {"tool": "get_farm_realtime_data", "args_template": {"data_type": "relay"}, "priority": 1},
        {"tool": "control_relay", "from_analysis": True, "priority": 2},
    ],
}
```

---

### 3.3 [3단계] 답변 작성 모듈

**신규 파일:** `agri_ai_core/src/ai/pipeline/answer_generator.py`

#### 3.3.1 핵심 설계 원칙

1. **도구 호출 불가**: 3단계 LLM에는 tools를 전달하지 않음 (순수 답변만 생성)
2. **데이터 기반 답변**: 2단계에서 수집된 검증된 데이터만 사용
3. **기존 시스템 프롬프트 재사용**: 말투, 답변 원칙, 표 형식 규칙 등은 그대로 유지
4. **기존 후처리 재사용**: _finalize_user_facing_answer, clean_llm_response 그대로 사용

#### 3.3.2 답변 생성 프롬프트

```python
def _build_answer_prompt(analysis, collected_data, conversation_context):
    """
    3단계 답변 생성용 프롬프트 구성

    기존 시스템 프롬프트의 말투/답변 원칙 부분은 그대로 유지하되,
    "도구 사용 규칙" 부분을 "데이터 활용 규칙"으로 교체
    """
    data_section = _format_collected_data(collected_data)

    return f"""
{기존_시스템프롬프트_말투_부분}

**데이터 활용 규칙 (절대 준수):**
1. 아래 [수집된 데이터]에 포함된 정보만 사용하여 답변하세요.
2. 데이터에 없는 정보를 추측하거나 만들어내지 마세요.
3. 수치, 날짜, 장소명은 데이터에 명시된 것만 사용하세요.
4. 데이터가 부족하면 "확인된 정보가 제한적이에요"라고 안내하세요.
5. 출처 URL은 답변에 포함하지 마세요 (시스템이 별도 표시합니다).
6. 표 형식이 적합한 경우 반드시 마크다운 표를 사용하세요.

[수집된 데이터]
{data_section}

[질문 분석]
- 질문 유형: {analysis['question_type']}
- 핵심 의도: {analysis['intent']}
- 답변 형식: {analysis['answer_format']}
"""
```

#### 3.3.3 LLM 호출 설정

```python
async def generate_answer(user_query, analysis, collected_data,
                          conversation_context, farm_name, speech_style):
    """
    3단계: 수집된 데이터 기반 답변 생성
    - tools=None (도구 호출 불가)
    - num_predict=NUM_PREDICT (충분한 답변 길이)
    - temperature=0.5 (기존과 동일)
    """
    system_prompt = _build_answer_prompt(analysis, collected_data, conversation_context)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # 대화 컨텍스트 주입 (기존 _build_conversation_context 로직 재사용)
    if conversation_context:
        _build_conversation_context(messages, conversation_context, user_query)

    messages.append({"role": "user", "content": user_query})

    response = _ollama_chat(
        model=model_name,
        messages=messages,
        tools=None,  # 핵심: 도구 미제공 → 순수 답변만 생성
        options={
            "temperature": 0.5,
            "num_predict": NUM_PREDICT,
            "num_ctx": NUM_CTX,
        }
    )

    raw_answer = _extract_message_content(response)
    finalized = _finalize_user_facing_answer(model_name, user_query, farm_name, raw_answer)

    return {
        "response": finalized,
        "sources": collected_data.get("sources", []),
        "tools_used": collected_data.get("tools_used", []),
        "response_type": _determine_response_type(collected_data.get("tools_used", []))
    }
```

---

## 4. 파일 구조

### 4.1 신규 생성 파일

```
agri_ai_core/src/ai/pipeline/
├── __init__.py
├── question_analyzer.py     # 1단계: 질문유형분석
├── data_collector.py        # 2단계: 데이터 수집 + 검증
├── answer_generator.py      # 3단계: 답변 작성
├── prompts.py               # 1/3단계 전용 프롬프트 관리
└── validators.py            # 2단계 데이터 검증 로직
```

### 4.2 수정 대상 파일

| 파일 | 변경 내용 | 변경 규모 |
|------|----------|----------|
| `query_handler_simple.py` | query_llm_simple()에서 3단계 파이프라인 호출로 전환 | 중 |
| `llm_client.py` | get_llm_response_with_tools()는 유지 (fallback), 새 함수 추가 불필요 | 소 |
| `tools_definition.py` | 1단계 전용 프롬프트 추가 (기존 프롬프트 변경 없음) | 소 |
| `tools_executor.py` | 변경 없음 (기존 execute_tool 그대로 사용) | 없음 |

### 4.3 변경하지 않는 파일 (대화 품질 보존)

| 파일/함수 | 이유 |
|-----------|------|
| `tools_executor.py` (execute_tool) | 7개 도구 실행 로직 그대로 재사용 |
| `_refine_*` 함수 전체 | 검증된 데이터 정제 로직 |
| `_finalize_user_facing_answer` | 검증된 후처리 로직 |
| `_check_answer_retry` | 답변 검증 로직 (3단계에서도 활용 가능) |
| `_save_conversation_turn_hybrid` | 대화 저장 로직 |
| `_load_hybrid_context` | 하이브리드 컨텍스트 |
| `get_system_prompt_with_tools` | 기존 프롬프트 (fallback용으로 보존) |
| `conversation_store.py` 전체 | 대화 관리 |
| `file_processor.py` 전체 | 파일 처리 |

---

## 5. 전환 전략 (Dual-Mode 안전 전환)

### 5.1 Phase 1: Dual-Mode 구현 (기존 + 신규 병렬 운영)

```python
# query_handler_simple.py 수정
async def query_llm_simple(user_query, ...):
    # 환경변수로 모드 전환 (기본: 기존 모드)
    use_pipeline = os.getenv("USE_3STAGE_PIPELINE", "false").lower() == "true"

    if use_pipeline:
        # 신규 3단계 파이프라인
        result = await _run_3stage_pipeline(user_query, ...)
    else:
        # 기존 Tool Use 루프 (변경 없음)
        result = await _call_llm_with_timeout(full_query, ...)

    yield result
```

### 5.2 Phase 2: A/B 테스트 (품질 비교)

```python
# 환경변수로 A/B 테스트 비율 조정
PIPELINE_AB_RATIO = float(os.getenv("PIPELINE_AB_RATIO", "0.0"))  # 0.0~1.0

import random
if random.random() < PIPELINE_AB_RATIO:
    # 신규 파이프라인
    result = await _run_3stage_pipeline(...)
    logger.info("[AB테스트] 3단계 파이프라인 사용")
else:
    # 기존 Tool Use
    result = await _call_llm_with_timeout(...)
    logger.info("[AB테스트] 기존 Tool Use 사용")
```

### 5.3 Phase 3: 완전 전환

- A/B 테스트에서 3단계 파이프라인의 답변 품질이 기존 이상임을 확인 후
- `USE_3STAGE_PIPELINE=true`로 전환
- 기존 Tool Use 루프는 코드에 보존 (긴급 rollback용)

---

## 6. 스트리밍 대응

### 6.1 현재 스트리밍 구조

```
query_llm_simple_stream()
  ├─ progress_queue를 통해 단계별 상태 전달
  │   "질문을 분석하고 있습니다..." (llm_analyzing)
  │   "센서 데이터를 조회하고 있습니다..." (tool_executing)
  │   "답변을 정리하고 있습니다..." (finalizing)
  └─ _split_for_streaming()으로 최종 답변 청크 분할
```

### 6.2 3단계 스트리밍 매핑

```
[1단계 실행 중] → "질문을 분석하고 있습니다..." (llm_analyzing)
[2단계 실행 중] → "데이터를 수집하고 있습니다..." (data_collecting)
  ├─ 도구 실행마다 → "센서 데이터를 조회하고 있습니다..." (tool_executing)
  ├─ 검증 중 → "데이터를 검증하고 있습니다..." (validating)
  └─ 보충 수집 → "추가 데이터를 수집하고 있습니다..." (supplementing)
[3단계 실행 중] → "답변을 작성하고 있습니다..." (llm_generating)
[후처리] → "답변을 정리하고 있습니다..." (finalizing)
```

---

## 7. 품질 보존 체크리스트

### 7.1 기존 대화 시나리오별 검증 항목

| 시나리오 | 검증 방법 | 합격 기준 |
|----------|----------|----------|
| "재배사 센서값 알려줘" | 3개 재배사 모두 데이터 포함 | 기존과 동일한 센서 항목 수 |
| "흡입팬 켜줘" | control_relay 실행 + AI judgment 포함 | 기존과 동일한 응답 형식 |
| "정읍 날씨" | 현재 날짜 기준 실시간 데이터 | 기존보다 정확 (개선 목표) |
| "주변 맛집 추천" | search_web 결과 기반 답변 | 기존과 동일한 품질 |
| "학습 자료 목록" | search_farm_knowledge 결과 | 기존과 동일한 파일 리스트 |
| "이전 대화 뭐였지?" | 컨텍스트 기반 답변 | 기존과 동일 |
| "안녕하세요" | 도구 없이 즉시 응답 | 기존과 동일한 응답 속도 |
| 파일 첨부 질문 | 파일 처리 + 답변 | 기존과 동일 |

### 7.2 성능 기준

| 항목 | 기존 | 3단계 목표 | 비고 |
|------|------|-----------|------|
| 인사 응답 시간 | ~3초 | ~3초 | greeting은 1단계 규칙 분류로 LLM 스킵 |
| 센서 조회 응답 시간 | ~15초 | ~18초 | 1단계 LLM 추가 (~3초) |
| 웹 검색 응답 시간 | ~30초 | ~25초 | 불필요한 반복 제거로 개선 가능 |
| 장치 제어 응답 시간 | ~10초 | ~13초 | 1단계 LLM 추가 (~3초) |
| 답변 정확도 | 변동적 | 일관적 향상 | 데이터 검증으로 오답 방지 |

---

## 8. 작업 단계 및 일정

### Phase 1: 기반 구축 (1단계 모듈)

| 순서 | 작업 | 상세 | 영향 범위 |
|------|------|------|----------|
| 1-1 | `pipeline/` 디렉터리 생성 | __init__.py, prompts.py | 신규 파일만 |
| 1-2 | question_analyzer.py 구현 | 분석 프롬프트 + fast_classify + JSON 파싱 | 신규 파일만 |
| 1-3 | 단위 테스트 | 20개 질문 유형별 분류 정확도 검증 | 테스트만 |
| 1-4 | 1단계 LLM 호출 최적화 | num_predict/num_ctx 튜닝, 응답 시간 3초 이내 확인 | 신규 파일만 |

### Phase 2: 데이터 수집 모듈

| 순서 | 작업 | 상세 | 영향 범위 |
|------|------|------|----------|
| 2-1 | data_collector.py 구현 | 기존 execute_tool + _refine_* 재사용 | 신규 파일만 |
| 2-2 | validators.py 구현 | 날짜 검증, 관련성 검증, 충분성 검증 | 신규 파일만 |
| 2-3 | 보충 수집 로직 구현 | query 수정 재검색, fetch_url 자동 실행 | 신규 파일만 |
| 2-4 | 유형별 강제 수집 규칙 | MANDATORY_TOOLS 정의 | 신규 파일만 |

### Phase 3: 답변 생성 모듈

| 순서 | 작업 | 상세 | 영향 범위 |
|------|------|------|----------|
| 3-1 | answer_generator.py 구현 | 기존 후처리 함수 재사용 | 신규 파일만 |
| 3-2 | 답변 프롬프트 작성 | 기존 시스템 프롬프트의 말투/원칙 부분 추출 + 데이터 활용 규칙 | 신규 파일만 |

### Phase 4: 통합 및 Dual-Mode

| 순서 | 작업 | 상세 | 영향 범위 |
|------|------|------|----------|
| 4-1 | query_handler_simple.py에 파이프라인 통합 | _run_3stage_pipeline() 추가, 환경변수 전환 | 기존 파일 수정 (추가만) |
| 4-2 | 스트리밍 대응 | progress_queue 이벤트 매핑 | 기존 스트리밍 로직 보존 |
| 4-3 | Dual-Mode 테스트 | 환경변수로 기존/신규 전환 테스트 | 운영 환경 |

### Phase 5: 검증 및 전환

| 순서 | 작업 | 상세 | 영향 범위 |
|------|------|------|----------|
| 5-1 | 시나리오별 비교 테스트 | 7.1 체크리스트 전체 항목 | 테스트만 |
| 5-2 | A/B 테스트 운영 | 10% → 30% → 50% → 100% 단계적 전환 | 운영 환경 |
| 5-3 | 완전 전환 | USE_3STAGE_PIPELINE=true | 환경변수 변경만 |

---

## 9. 리스크 및 대응

| 리스크 | 영향 | 대응 방안 |
|--------|------|----------|
| 1단계 LLM 분류 오류 | 잘못된 도구 실행 | fast_classify 규칙 기반 사전 필터 + fallback |
| 1단계 추가 LLM 호출로 응답 지연 | 3초 증가 예상 | greeting/control 등 명확한 패턴은 규칙으로 스킵 |
| 2단계 검증 오탐 (정상 데이터를 부실로 판단) | 불필요한 재검색 | 검증 임계값 보수적 설정 + 로그 모니터링 |
| 3단계 LLM이 데이터 무시하고 환각 | 부정확한 답변 | "데이터에 없는 정보 생성 금지" 프롬프트 강화 |
| 기존 대화 품질 저하 | 사용자 불만 | **Dual-Mode로 즉시 rollback 가능** |
| 복합 질문 처리 실패 | 불완전 답변 | complex 유형 → 기존 Tool Use 루프 fallback |

---

## 10. 기대 효과

| 항목 | 현재 | 3단계 적용 후 |
|------|------|-------------|
| 날씨 질문 정확도 | 과거 데이터 답변 위험 | 날짜 검증 + fetch_url 강제로 실시간 보장 |
| 센서 데이터 누락 | LLM 판단에 의존 | 시스템이 multi_house 강제 실행 |
| fetch_url 호출 누락 | LLM이 "충분하다"고 판단 시 미호출 | 2단계에서 시스템이 강제 호출 |
| 재검색 누락 | LLM이 결과 부실을 인지 못함 | 검증기가 자동 감지 후 보충 수집 |
| 디버깅 용이성 | 루프 내부 추적 어려움 | 단계별 로그로 문제 지점 즉시 파악 |
| 프롬프트 관리 | 300줄 단일 프롬프트 | 단계별 경량 프롬프트 분리 관리 |
