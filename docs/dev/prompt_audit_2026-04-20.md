# LLM 프롬프트 감사 리포트 — C1

**작성일**: 2026-04-20  
**범위**: `agri_ai_core/src/ai/pipeline/prompts.py` + `agri_ai_core/src/ai/tools_definition.py`  
**목적**: 세션 동안 8회 보강되며 누적된 규칙의 중복·모순·비대화를 식별해 **추후** 통합·정리 작업의 기초 자료 제공.  
**방침**: 본 리포트는 **감사만**. 실제 규칙 변경은 본 문서를 근거로 건별 승인받아 별도 세션에서 진행.

---

## 1. 정량 지표

| 파일 | 총 줄 수 | "반드시" | "금지" | "절대 규칙/절대 금지" |
|---|---:|---:|---:|---:|
| `pipeline/prompts.py` | 353 | 20 | 9 | 26 |
| `tools_definition.py` | 421 | 33 | 21 | 49 |
| **합계** | **774** | **53** | **30** | **75** |

→ `"반드시/금지"` 유형 표현이 약 83회. LLM 에게 제약이 과도하면 "어느 규칙이 더 중요한지" 판단 부담 → 답변 편향·검열 위험.

## 2. 유형별 규칙 커버리지 (ANALYZER_SYSTEM_PROMPT)

| 유형 | 정의 위치 | 비고 |
|---|---|---|
| weather | prompts.py | OK |
| farm_sensor | prompts.py | 최근 `multi_house=["all"]` 규칙 보강됨 |
| farm_control | prompts.py | `devices[]` 규칙 + 장치명 whitelist 포함 |
| farm_knowledge | prompts.py | 간결 |
| farm_knowledge_delete | prompts.py | 간결 |
| web_search | prompts.py | query 한국어 강제 + fetch 폴백 |
| gas_price | prompts.py | 간결 |
| **agent_monitor** | prompts.py | Wave 1 B1 에서 신설 |
| greeting / conversation_ref / general / complex | prompts.py | 재포맷 매칭 규칙 포함 |

빠진 유형 없음. OK.

## 3. 중복·유사 규칙 후보

### 3.1 다중 재배사 규칙 (2곳 중복)

**prompts.py** (farm_sensor 유형 규칙):
> - "각 재배사/전체/모든 재배사" → multi_house=true, house_ids=["all"]
> - 실시간 모니터링/지켜봐/감시/상태 알려줘 등 특정 재배사를 명시하지 않은 요청 → multi_house=true, house_ids=["all"]

**tools_definition.py:362** (답변 규칙 1):
> 다중 재배사 질문 (절대 규칙): "각 재배사", "전체", "모든 재배사" 등 복수 재배사 요청 시 반드시 농장의 모든 재배사에 대해 각각 get_farm_realtime_data 를 호출해야 합니다.

**영향**: 같은 규칙을 두 프롬프트에 중복 명시. 한쪽만 수정 시 불일치 발생 가능.  
**권고**: ANALYZER 단계에서 이미 `multi_house=true`로 분류돼 `data_collector._expand_multi_house` 가 fan-out 하므로 **Answer 프롬프트의 중복은 제거 또는 축약** 가능. 단, LLM 이 fan-out 결과를 누락하지 않도록 하는 "도구 결과 전체 사용" 규칙은 유지.

### 3.2 장치 제어 즉시 실행 규칙 (최소 4회 등장)

`tools_definition.py` 의 "장치 제어 요청" 섹션에 동일 취지의 문구가 여러 각도로 반복:
- "반드시 `control_relay` 도구를 호출하여 실제로 제어해야 합니다"
- "**사용자 명령 즉시 실행 (절대 규칙)**"
- "**절대 규칙**: 이전 대화에서 동일한 제어 요청에 성공한 답변이 있더라도, 반드시…"

**영향**: 강조 자체는 효과적이지만 "조건부 실행(쿨다운 중 등)" 같은 예외 여지를 LLM 이 과하게 무시할 수 있음.  
**권고**: 한 블록으로 묶고 "단, 응답의 warnings 필드가 있으면 사용자에게 반드시 전달" 같은 섬세 지침 추가.

### 3.3 "절대 규칙" 과잉

`tools_definition.py` 에 `"절대 규칙"` 10회+, `"절대 금지"` 다수. LLM 이 모든 걸 동일 우선순위로 인식하면 새로 추가되는 절대 규칙이 묽어지는 효과가 있음.  
**권고**: 우선순위 계층 도입 (`🔴 최우선: 안전 · 🟠 필수: 정확도 · 🟡 권장: 스타일`). 지금은 전부 🔴 로 취급됨.

### 3.4 환각 금지 규칙 3곳

- `build_answer_system_prompt` data_rules A~D 블록
- `_generate_simple_response` conversation_ref 프롬프트
- `tools_definition.py` 답변 원칙

**권고**: 현재 각 목적이 조금씩 달라 유지는 타당. 다만 새 환각 이슈 발견 시 한 곳에만 추가하지 말고 세 곳 모두 반영 여부를 체크하는 **프롬프트 변경 체크리스트** 필요.

## 4. 잠재적 모순

### 4.1 "즉시 실행" vs "확인 후 실행"

- `tools_definition.py`: "제어 실행 전에 확인을 요청하거나, AI 판단을 이유로 제어를 보류·거부하는 것은 절대 금지"
- 동시에: "ai_conflict 가 있으면 반드시 ⚠️ 주의: … 형식으로 차이점을 명확히 안내"

**해석**: "거부는 안 되지만 경고는 필요" 로 일관되게 해석 가능. 모순 아님. 다만 LLM 이 "확인 질문" 과 "경고 안내" 를 혼동할 여지 있음 → 명시적 예시로 구분 권고.

### 4.2 conversation_ref 판정 경합

- 재포맷 요청("표로", "요약") → conversation_ref
- 센서 조회 요청 중 "다시 조회" → farm_sensor (새 수집)

**패턴 경합 예**: "다시 표로 보여줘" — 재포맷 맞는데 "다시" 때문에 farm_sensor 로 갈 수 있음.  
**현재 방어**: `_REFORMAT_RE`가 `"지금/새로/최신/다시\s*조회/다시\s*확인"` 만 제외하므로 "다시 표로" 는 conversation_ref 로 분류됨 (테스트에서 확인).  
**평가**: 잘 동작 중. 규칙 문서화 보강만 권고.

## 5. 유지보수 제안 (별도 세션)

### 5.1 구조 개편
- **공용 상수** (장치명 매핑, 임계값 범위, 재배사 규칙) 를 별도 `prompts_fragments.py` 로 추출 후 두 프롬프트에서 참조
- 기능별 규칙 블록을 dataclass + 텍스트 렌더러로 전환 (단위 테스트 가능)

### 5.2 규칙 우선순위 3단계 도입
- 🔴 SAFETY (안전/권한) — 현재 "절대 규칙" 중 진짜 위험 방지만
- 🟠 CORRECTNESS (데이터 정확성) — 환각 금지, 수치 유지
- 🟡 STYLE (말투·길이·포맷) — 현재 "~이어야 한다" 수준

### 5.3 프롬프트 변경 체크리스트
- [ ] 관련 규칙이 다른 파일/섹션에도 있는가?
- [ ] 해당 규칙에 대응하는 회귀 테스트가 `tests/ai/` 에 있는가?
- [ ] LLM 에 노출되는 파라미터 이름이 스키마(tools_definition)와 일치하는가?
- [ ] 권한 변경이면 `tools_auth` 가드와 일치하는가?

## 6. 이번 세션에서 이미 해결된 항목

| 항목 | 처리 Wave |
|---|---|
| multi_house=["1","2","3"] 하드코딩 | patch1 → `["all"]` + DB 동적 fan-out |
| 재포맷 요청 맥락 상실 | patch1/patch2 → conversation_ref 규칙 + 환각 금지 프롬프트 강화 |
| 나열 시 일부 재배사 생략 | patch4 → "조건 만족 재배사 모두 명시" 규칙 추가 |
| list/cancel_monitor 자연어 미인식 | Wave 1 B1 → agent_monitor 유형 규칙 신설 |
| Tool Use 루프 deprecate | Wave 1 D1 → WARNING 로그 |

## 7. 결론

- **긴급 수정 필요 항목 없음**. 지금 상태로 서비스 안정.
- **중복 축소·우선순위 도입**은 운영 부담 완화 차원의 기술 부채. 별도 리팩토링 세션에서 진행 권고.
- 본 리포트는 향후 프롬프트 변경 시 참고 근거로 활용.
