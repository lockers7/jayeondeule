# Agent 기능 구현 작업 진행 문서

> **이 문서를 읽고 어디서든 작업을 이어갈 수 있도록 모든 절차를 자족적으로 기록한다.**
> 다른 세션·다른 사용자가 들어와도 이 한 파일만으로 현재 진행 단계 파악 + 작업 재개 + 복원 가능해야 한다.

---

## 0. 컨텍스트

### 0.1 농장 시스템
- **자연들에 농장**, 전라북도 정읍시 영원면 성지1길 17-27
- 상황버섯 시설재배, 6개 재배사 (0-0, 0-99, 1-0, 1-1, 1-2, 1-3)
- 환경 변수: 실내·외 온습도, CO2, 수온, 16개 릴레이 (수온히터/포그/배수밸브/환풍기/순환밸브/조명/관수/흡입밸브/배출밸브/히터밸브 등)

### 0.2 기존 LLM 처리 구조
- **로컬 LLM**: `Ollama gemma3:27b` (응답 평균 45~60초/회)
- **환경제어 LLM** (`agri_ai_core/src/control/ai_control.py`):
  - 매 사이클(AI 모드: 5~10분/호기) single-shot 호출
  - `system_prompt` (9-section 4977자, inline 단일 source) + `user_prompt` (센서·릴레이·트렌드·RAG·카메라·외기 등 9~14블록)
  - `format=schema` JSON 강제, 응답 = `{action, reason, devices, circulation}` 한 객체
- **대화 LLM** (`agri_ai_core/src/ai/query_handler_simple.py`):
  - 사용자 챗봇. ANALYZER/VALIDATOR/ANSWER chunk 기반
  - ChromaDB `prompt_chunk` 컬렉션이 source

### 0.3 사용자 의도 (이 작업의 핵심)
> 현재 처리되는 스케줄에 의한 처리는 그대로 유지하고, **모니터링·값변경 등의 재배사 모니터링 관련은 agent 로** 한다.
>
> 하드웨어는 점차 upgrade. 하드웨어 스펙이 좋아지면 LLM 모델도 upgrade. **원론적이고 정확한 기능으로 구현**.

요약:
- **스케줄 제어 (algorithm 모드·AI 모드의 5초~10분 사이클) = 그대로 유지** — 결정론·안정성 중요
- **agent = 자율 모니터링·값변경 신규 영역** — 능동·추세 인지·도구 호출
- 모델 한계는 인정하되 **설계는 완전체로** — gemma3 한계는 시간 흘러 해결될 것

### 0.4 기존 인프라 (재사용 가능 자산)
- `tool_definition_m` PostgreSQL 테이블 (도구 등록·활성/비활성 토글 가능)
- `agri_ai_core/src/ai/tools_*.py` (제어/조회/관리 도구 함수)
- `agri_ai_core/src/ai/llm_transport.py` (Ollama 호출 wrapper)
- `agri_ai_core/src/prompt_registry.py` (system prompt 동적 read)
- `format=schema` JSON 강제 패턴 (이미 ai_control 이 사용 중)
- `ai_decision_log` 테이블 패턴 (agent 도 동일 패턴으로 `agent_decision_log` 추가)

---

## 1. 작업 목표

### 1.1 Phase 종합

| Phase | 범위 | 핵심 산출물 |
|---|---|---|
| **Phase 1** | 골격 + read-only 도구 | `ai_monitor_agent.py` 모듈, 도구 5개, ReAct loop, 시스템 프롬프트, 단발 실행 |
| **Phase 2** | 시스템 통합 | systemd `agent_monitor.service`, 30분 cron, `agent_decision_log` 테이블, 로그 일원화 |
| **Phase 3** | write tools (안전 가드) | 릴레이·임계·생육단계 변경 도구. 권한·일일 제한·취소 큐 |
| **Phase 4** | 알림 + Web UI | SSE 알림 채널, `/agent-history` 페이지, agent 실행/취소 UI |
| **Phase 5** (선택) | 트리거 다양화 | 이벤트 기반(센서 임계 근접), 사용자 명령("지금 분석"), 정기(30분/1h) |

### 1.2 성공 기준 (PoC)

다음 시나리오를 agent 가 인지·보고하면 PoC 성공:
1. **수온 추세 위험**: 1-3 수온 25→27→29→30→32℃ 추세에서 agent 가 32℃ 도달 *전* (예: 29℃ 시점) "위험 임박" 알림
2. **CO2 임계 근접**: 1-1 CO2 1000→1200→1400→1500ppm 추세에서 1500 도달 *전* (1400 시점) "환기 검토 필요" 알림
3. **호기 간 비교**: 같은 외기에서 1-3 만 수온 비정상 상승 = 이상치 알림

→ 즉 **현재 single-shot LLM 이 후행 반응했던 케이스를 agent 가 선제적으로 잡아내는지**.

---

## 2. 백업 정보 (복원 절차)

### 2.1 백업 식별자

- **git commit**: `a31dc70` ("backup: agent 구현 시작 전 baseline (2026-05-25)")
- **git tag**: `baseline_agent_20260525`
- **tar.gz**: `/workspace/jayeondeule/backups/baseline_agent_20260525_121756.tar.gz` (1.6GB)

### 2.2 복원 절차

**부분 복원 (특정 파일만)**:
```bash
cd /workspace/jayeondeule
git checkout baseline_agent_20260525 -- <파일경로>
```

**전체 복원 (현재 작업 모두 폐기)**:
```bash
cd /workspace/jayeondeule
git stash                                    # 현재 변경사항 임시 보관
git reset --hard baseline_agent_20260525     # baseline 으로 hard reset
```

**git 외 복원 (저장소 자체 손상 시)**:
```bash
cd ~
tar -xzf /workspace/jayeondeule/backups/baseline_agent_20260525_121756.tar.gz -C /tmp/restore/
# 필요 파일 수동 복사
```

### 2.3 작업 중 추가 백업
각 Phase 완료 시:
```bash
git add -A
git commit -m "agent phase <N>: <설명>"
git tag "agent_phase<N>_$(date +%Y%m%d)"
```

---

## 3. 설계 원칙

### 3.1 안전성 (Top Priority)
- **현 비상가드 disable 정책** 상태에서 agent 가 *새 위험원* 이 되면 안 됨
- 모든 write 도구는: ① 권한 확인 ② 일일 호출 제한 ③ 취소 가능 ④ `agent_decision_log` 기록
- 첫 단계는 **read-only 만**. write 는 검증 후 단계적 도입

### 3.2 모듈 분리
- 기존 `ai_control.py` (스케줄 제어) 와 **import 경로 분리**
- 신규 모듈: `agri_ai_core/src/control/ai_monitor_agent.py`
- 도구 모음: `agri_ai_core/src/ai/tools_agent.py` (또는 기존 `tools_*.py` 재사용)
- 시스템 프롬프트: `prompt_block_m` 에 `AGENT_*` block_id 로 저장

### 3.3 결정 기록·재현 가능성
- 모든 agent 사이클: 입력(센서/지시) → ReAct 단계별 (thought/tool/result) → 최종 답 → DB 기록
- `agent_decision_log` 테이블에 *모든 단계* JSON 저장
- 추후 같은 입력으로 재현 + 디버깅 가능

### 3.4 LLM 모델 교체 가능성
- `gemma3:27b` 의 한계가 명확하므로, **모델 명 환경변수화**:
  ```python
  AGENT_LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "gemma3:27b")
  ```
- 미래 모델 (gemma4, qwen3, llama4, 또는 Claude API) 교체 시 코드 0줄 수정으로 전환

### 3.5 점진적 통합
- Phase 1 PoC 검증 전엔 운영 영향 0
- Phase 2 부터 운영 서버 systemd unit 추가
- Phase 3 write 도구는 *반드시* PoC 검증 후

---

## 4. Phase 별 상세 구현 가이드

### Phase 1: 골격 + Read-only ReAct Loop

**목표**: ReAct 패턴으로 LLM 이 read-only 도구 호출하며 모니터링 보고 작성

**산출물**:
- `agri_ai_core/src/control/ai_monitor_agent.py` (신규)
- `agri_ai_core/src/ai/tools_agent.py` (신규)
- `prompt_block_m` 에 `AGENT_MONITOR_SYSTEM` block (신규)
- 단발 CLI 실행: `python -m agri_ai_core.src.control.ai_monitor_agent --farm 1`

**도구 정의 (read-only 5개)**:
```python
{
  "get_sensor_window":      {"farm": int, "house": int, "minutes": int},   # 평균/min/max
  "get_recent_decisions":   {"farm": int, "house": int, "hours": int},     # LLM 결정 이력
  "get_relay_state":        {"farm": int, "house": int},                   # 현재 16핀 상태
  "compare_houses":         {"farm": int, "metric": str},                  # 같은 농장 호기 비교
  "get_thresholds":         {"farm": int, "house": int}                    # sensor_m_setting 임계
}
```

**시스템 프롬프트 골격** (`AGENT_MONITOR_SYSTEM` block):
```
당신은 스마트팜 모니터링 agent 다.

목표:
- 모든 호기의 센서·릴레이·LLM 결정을 자율 분석
- 위험 추세 (수온/내부온도/CO2/습도 임박 변화) 선제 감지
- 호기 간 비교로 이상치 검출
- 결론 보고 (한국어, JSON)

사용 가능 도구:
[도구 list 동적 주입]

응답 형식 (반드시 JSON):
  {"thought": "사고 과정", "tool": "<도구명>", "args": {...}}
또는 종료 시:
  {"thought": "최종 결론 사고", "final": "한국어 보고 본문"}

MAX_STEPS: 8단계 안에 final 도달. 그렇지 못하면 자동 종료.
```

**ReAct loop 코드 골격**:
```python
def run_agent(task: str, farm_id: int, max_steps: int = 8) -> dict:
    """단발 ReAct 루프. 최종 보고 dict 반환."""
    system = get_block('AGENT_MONITOR_SYSTEM', tools=TOOL_REGISTRY.spec())
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task}]
    history = []   # 각 단계 기록

    for step in range(max_steps):
        resp = call_llm(messages, format='json')   # gemma3:27b
        parsed = json.loads(resp)
        history.append({"step": step, **parsed})

        if 'final' in parsed:
            return {"success": True, "final": parsed['final'], "steps": history}

        # tool 호출
        tool_name = parsed.get('tool')
        args = parsed.get('args', {})
        if tool_name not in TOOL_REGISTRY:
            messages.append({"role": "assistant", "content": resp})
            messages.append({"role": "user", "content": f"Tool '{tool_name}' not found."})
            continue

        try:
            result = TOOL_REGISTRY[tool_name](**args)
        except Exception as e:
            result = {"error": str(e)}

        messages.append({"role": "assistant", "content": resp})
        messages.append({"role": "user", "content": json.dumps({"tool_result": result}, ensure_ascii=False)})

    return {"success": False, "reason": "MAX_STEPS exceeded", "steps": history}
```

**검증 (Phase 1 PoC)**:
- 단발 실행: `python -m agri_ai_core.src.control.ai_monitor_agent --task "1-3 호기 수온 추세 분석"`
- 기대: agent 가 `get_sensor_window(1, 3, 60)` 호출 → 결과 분석 → "수온 25→32℃ 빠른 상승, 모니터 강화 권장" 보고
- 실패 케이스 기록 (gemma3 의 JSON 깨짐, 도구 잘못 호출 등)

**예상 작업 시간**: 2~3시간

---

### Phase 2: 시스템 통합

**목표**: 30분마다 자동 실행되는 데몬 + 결과 DB 영속

**산출물**:
- `agent_decision_log` 테이블 (migration `db/migrations/005_agent_decision_log.sql`)
- `etc/systemd/system/agent_monitor.service`
- `agri_ai_core/src/control/agent_scheduler.py` (신규, 30분 cron)
- 로그 일원화: `logs/agent_YYYY-MM-DD.log`

**테이블 스키마**:
```sql
CREATE TABLE agent_decision_log (
  id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMP NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMP,
  trigger_type VARCHAR(20) NOT NULL,    -- 'schedule' / 'event' / 'user'
  task TEXT NOT NULL,                    -- 사용자/스케줄러가 준 입력
  steps JSONB,                           -- 전체 step history
  final_report TEXT,                     -- final 보고 본문
  success BOOLEAN,
  duration_sec NUMERIC(8,2),
  llm_calls INT,
  tool_calls JSONB                       -- {tool_name: count, ...}
);
CREATE INDEX idx_agent_log_started ON agent_decision_log(started_at DESC);
```

**systemd unit**:
```ini
[Unit]
Description=Agent Monitor Scheduler
After=network.target postgresql.service ollama.service

[Service]
ExecStart=/workspace/jayeondeule/venv/bin/python -m agri_ai_core.src.control.agent_scheduler
WorkingDirectory=/workspace/jayeondeule
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

**agent_scheduler.py 골격**:
```python
import time
from datetime import datetime
from agri_ai_core.src.control.ai_monitor_agent import run_agent

INTERVAL_MIN = int(os.getenv("AGENT_INTERVAL_MIN", "30"))

def main():
    while True:
        now = datetime.now()
        if now.minute % INTERVAL_MIN == 0 and now.second < 5:
            for farm_id in [1]:
                result = run_agent(
                    task=f"정기 30분 모니터링 — {now:%H:%M} 농장 {farm_id} 전체",
                    farm_id=farm_id,
                    trigger_type='schedule',
                )
                # DB 기록 + 알림 (Phase 4)
            time.sleep(50)  # 1분 안 중복 실행 방지
        time.sleep(1)
```

**검증**:
- `systemctl start agent_monitor` → 30분 정각마다 agent 자동 실행
- `agent_decision_log` 에 row 누적
- LLM 호출 횟수·duration 합리적인지 모니터

**예상 작업 시간**: 3~4시간

---

### Phase 3: Write 도구 (단계적, 안전 가드)

**목표**: agent 가 *실제 릴레이/설정 변경* 할 수 있게. 단 엄격한 안전 가드.

**도구 추가**:
```python
{
  "set_relay":          {"farm": int, "house": int, "semantic": str, "on": bool},
  "set_threshold":      {"farm": int, "house": int, "key": str, "value": float},
  "set_growth_stage":   {"farm": int, "house": int, "stage": str},
  "send_user_alert":    {"level": str, "message": str}                    # 알림은 항상 안전
}
```

**안전 가드 (`tools_agent.py`)**:
```python
@safety_guard(
    require_admin=True,                                # 관리자 권한 필요
    daily_limit=10,                                    # 호기당 일일 10회
    cooldown_seconds=60,                               # 같은 도구 60초 cooldown
    cancellable_within_seconds=30,                     # 30초 안 취소 가능 큐
    log_table='agent_decision_log',
)
def set_relay(farm, house, semantic, on):
    ...
```

**취소 가능 큐 구조**:
1. agent 가 `set_relay` 호출 → DB `agent_pending_actions` 에 INSERT (status='pending', execute_at=NOW()+30s)
2. 30초 동안 web UI 에 표시, 사용자가 "취소" 누를 수 있음
3. 30초 후 status='executed' 로 변경되며 실제 릴레이 변경 실행
4. 취소되면 status='cancelled', 변경 안 일어남

**검증 시나리오**:
- agent 가 "1-3 수온 위험" 인지 → `set_relay(1, 3, 'water_heater', False)` 호출
- web UI 알림: "30초 후 1-3 수온히터 OFF 예정. 취소하시려면 클릭"
- 사용자 미반응 → 30초 후 실제 OFF
- 사용자 취소 → 변경 안 됨

**예상 작업 시간**: 4~5시간

---

### Phase 4: 알림 + Web UI

**목표**: agent 활동 + 결정을 사용자가 직관적으로 보고 통제 가능

**산출물**:
- `web/frontend/src/pages/admin/AgentHistoryPage.jsx` (신규)
- `agri_ai_core/api/agent_router.py` (신규 FastAPI router)
  - `GET /api/v1/agent/history` — agent_decision_log 조회
  - `GET /api/v1/agent/pending` — 대기 중 action 큐
  - `POST /api/v1/agent/pending/{id}/cancel` — 취소
  - `POST /api/v1/agent/trigger` — 사용자 수동 trigger
  - `GET /api/v1/agent/stream` (SSE) — 실시간 알림
- `AdminNavLink.jsx` 에 "Agent 이력" 메뉴 추가

**UI 구성**:
1. **타임라인 뷰**: 시각별 agent 실행 → ReAct steps 펼치기 → final 보고
2. **대기 큐 박스**: 30초 카운트다운 + 취소 버튼
3. **수동 trigger**: 텍스트 입력 + "지금 분석" 버튼
4. **실시간 알림 토스트**: SSE 로 agent 의 `send_user_alert` 도구 호출 시 즉시 표시

**예상 작업 시간**: 4~6시간

---

### Phase 5 (선택): 트리거 다양화

**이벤트 트리거**:
- `setting_listener` 와 같은 LISTEN/NOTIFY 패턴
- 트리거 조건: 센서가 임계 ±10% 진입 / LLM 5회 연속 keep / 카메라 이상 감지 / DB INSERT 0건 5분+
- 발생 시 즉시 agent 호출 (스케줄 30분 대기 안 함)

**예상 작업 시간**: 3~4시간

---

## 5. 검증 체크리스트

### Phase 1 완료 조건
- [ ] `python -m agri_ai_core.src.control.ai_monitor_agent --task "..."` 명령 5회 연속 성공
- [ ] gemma3 의 JSON 깨짐 < 20% (실패 시 retry 또는 가이드 추가)
- [ ] PoC 시나리오 3개 (수온/CO2/이상치) 중 최소 2개 적중

### Phase 2 완료 조건
- [ ] systemd `agent_monitor.service` active + enabled
- [ ] 30분마다 `agent_decision_log` 에 row 신규
- [ ] 24시간 무재시작 가동
- [ ] 평균 LLM 호출 < 10회/사이클 (한 사이클당 LLM token 비용 합리화)

### Phase 3 완료 조건
- [ ] 모든 write 도구가 `agent_pending_actions` 거쳐 30초 지연 실행
- [ ] 사용자 취소 동작 정상
- [ ] 일일 제한·cooldown 가드 작동
- [ ] `set_relay` 가 기존 `relay_manager.set_relay_value` 호출 (인터록 게이트 통과)

### Phase 4 완료 조건
- [ ] `/agent-history` 페이지 정상 표시
- [ ] SSE 알림 도착
- [ ] 수동 trigger 동작

---

## 6. 다음 세션에서 작업 이어가는 방법

**이 문서를 처음 보는 세션이라면**:

### 6.1 현재 진행 단계 파악
```bash
cd /workspace/jayeondeule
git log --oneline --all | grep -E "agent phase|baseline_agent" | head
```
- `baseline_agent_20260525` 이후 commit/tag 들이 작업 진척 표시

### 6.2 다음 작업할 Phase 식별
1. 이 문서의 §4 Phase 별 가이드에서 *마지막 완료된 Phase + 1* 찾기
2. 해당 Phase 의 §5 체크리스트 확인
3. 산출물 파일 존재 여부 점검

### 6.3 작업 재개
```bash
# 1. 환경 확인
source venv/bin/activate
git status

# 2. 작업할 Phase 의 산출물 파일 생성 또는 수정

# 3. 검증
pytest tests/ -k agent   # 또는 단발 CLI 실행

# 4. commit
git add -A
git commit -m "agent phase <N>: <변경 내용>"
git tag "agent_phase<N>_$(date +%Y%m%d)"
```

### 6.4 막힘 / 결정 필요 시
- 이 문서의 §3 설계 원칙 우선
- 사용자에게 묻기 전에 §4 Phase 가이드 다시 확인
- 그래도 모호하면 **사용자에게 명확한 옵션과 함께 질문** (단일 선택 불가능한 임의 결정 금지)

---

## 7. 참고 자료 (기존 코드 위치)

| 카테고리 | 파일 | 비고 |
|---|---|---|
| LLM 호출 wrapper | `agri_ai_core/src/ai/llm_transport.py` | Ollama HTTP 호출, format=schema |
| 환경제어 LLM | `agri_ai_core/src/control/ai_control.py` | 9-section inline system prompt + JSON 응답 |
| 대화 LLM | `agri_ai_core/src/ai/query_handler_simple.py` | ANALYZER/VALIDATOR/ANSWER chunk |
| 도구 함수 | `agri_ai_core/src/ai/tools_control.py` `tools_data.py` `tools_admin.py` `tools_definition.py` | 기존 도구. agent 도 재사용 |
| 도구 DB | `tool_definition_m` 테이블 (PostgreSQL) | active_yn 토글 가능 |
| 시스템 프롬프트 DB | `prompt_block_m` 테이블 (PostgreSQL) | `AGENT_*` block_id 신규 추가 |
| DB 헬퍼 | `agri_ai_core/src/postgresql/connection.py` | `db_session()`, `fetch_all`, `execute_query` |
| 로깅 | `agri_ai_core/logs/__init__.py` | `setup_logger(name)` |
| 운영 결정 이력 | `ai_decision_log` 테이블 | agent 도 같은 패턴 |
| Web UI 라우팅 | `web/frontend/src/routes/AdminRoutes.jsx` | 신규 메뉴 추가 시 수정 |
| Web 백엔드 | `agri_ai_core/api/app.py` (FastAPI) | 신규 router 추가 시 수정 |

---

## 8. 위험·안전 가드 (필독)

### 8.1 비상가드 disable 정책과의 관계
- 현재 시스템은 **`environment_logic._emergency_override` 가 항상 (False, None, None, False)** 반환 (5/17 사용자 정책)
- agent 가 비상 상황 인지하더라도 *시스템 자동 강제* 가 작동하지 않음
- agent 의 `set_relay` 가 *유일한* 자동 대응 경로가 될 수 있음 → **신중한 권한 가드 필수**

### 8.2 LLM 환각 대응
- gemma3:27b 는 *없는 도구* 호출, *잘못된 args*, *잘못된 결과 해석* 가능
- 매 tool 호출 시 **args validation** (Pydantic 또는 manual)
- final 보고 시 **수치 일관성 체크** (예: 보고서 안 수온값 = 실제 sensor read 결과 일치)

### 8.3 무한 loop 방지
- MAX_STEPS=8 강제
- 같은 tool + 같은 args 가 3회 연속 = 종료
- 한 사이클당 wall-clock timeout (예: 10분)

### 8.4 비용·자원 한계
- gemma3:27b 한 호출 50초 → Phase 2 의 30분 cron 에서 한 사이클이 5분 넘으면 다음 cron 과 충돌 가능
- `agent_scheduler.py` 는 *이전 사이클 종료 후* 다음 시작 (sleep + check pattern)

---

## 9. 변경 이력 (이 문서)

| 날짜 | 작성자 | 변경 |
|---|---|---|
| 2026-05-25 12:18 | initial | 문서 신설. baseline commit `a31dc70` + tag `baseline_agent_20260525` 기록 |
| 2026-05-25 | Claude | **Phase 1 완료**. `tools_agent_read.py` (5 도구) + `ai_monitor_agent.py` (ReAct loop) + `AGENT_MONITOR_SYSTEM` 프롬프트. pytest 17+23 PASS. gemma3 PoC 2/3 성공 (2-step 90s, 3-step 88s). |
| 2026-05-25 | Claude | **Phase 2.1~2.3 완료**. migration `005_agent_decision_log.sql` 적용. `_persist_agent_log()` DB 영속 (commit 패턴 정정). `agent_scheduler.py` 30분 cron 데몬. pytest 58 PASS (tools 17 + monitor 26 + scheduler 15). |
| 2026-05-25 | Claude | **Phase 2.4 완료**. `setup/system-configs/systemd/agent_monitor.service` 신설 (Type=simple daemon, Requires=ollama+postgresql, Restart=on-failure). `agriAiCore` 스크립트 16번 서비스 통합 (수동만 — ALL/APP 자동 시작 미포함). `bash -n` + `systemd-analyze verify` 통과. |
| 2026-05-25 | Claude | **Phase 2.5 완료**. 단축 cron 1사이클 (`AGENT_INTERVAL_MIN=1`) 실측: 13:04:00 cycle 시작 → 13:06:43 완료 (163.1s, gemma3 LLM 8회, 도구 7회 — `get_sensor_window×3, get_thresholds×3, compare_houses×1`). `agent_decision_log` id=16 INSERT 검증 완료 (trigger=schedule, success=true, model=gemma3:27b). 두번째 사이클 13:07:00 자동 진행 후 SIGTERM 우아한 종료. |

다음 phase 진행 시 이 표에 추가:
- 진행자 (Claude / 사용자) / 변경 요약 / commit hash·tag

---

**작업 시작점**: §4 Phase 1 (`ai_monitor_agent.py` 골격 + read-only 5개 도구)부터.

| 2026-05-25 13:30 | Claude | Phase 1 완료 — `tools_agent_read.py` (5 도구) + `ai_monitor_agent.py` (ReAct loop) + `AGENT_MONITOR_SYSTEM` block. pytest 40/40 PASS (17 tools + 23 agent). PoC 3 시나리오 검증: 2 성공 + 1 MAX_STEPS 초과 후 프롬프트 강화. |
