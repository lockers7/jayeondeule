-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 009 — control_prompt_m : LLM 제어용 텍스트 데이터 전용 테이블
--
-- 목적:
--   ai_control.py / ai_monitor_agent.py 의 모든 inline 텍스트(system prompt
--   섹션, user prompt 레이블/메시지, agent system prompt)를 DB 로 이전.
--   UI(LLM 제어관리 메뉴)에서 편집 → 즉시 반영.
--
-- 적용 명령:
--   PGPASSWORD='Wkdusemfdp1@' psql -h 127.0.0.1 -U postgres -d jayeondeule \
--     -f /workspace/jayeondeule/db/migrations/009_control_prompt_m.sql
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 1) 테이블 생성
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS control_prompt_m (
    block_id        VARCHAR(64) PRIMARY KEY,
    section_key     VARCHAR(32)  NOT NULL,
    growth_stage    VARCHAR(16),
    sort_order      INT          NOT NULL DEFAULT 0,
    category        VARCHAR(32)  NOT NULL,
    name            VARCHAR(128) NOT NULL,
    body_text       TEXT         NOT NULL,
    placeholders    JSONB,
    active_yn       CHAR(1)      NOT NULL DEFAULT 'Y',
    description     VARCHAR(512),
    rgst_dttm       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updt_dttm       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ctrl_prompt_section
    ON control_prompt_m (section_key, growth_stage, active_yn, sort_order);

-- updt_dttm 자동 갱신 트리거 (generic_touch_updt_dttm 는 migration 003 에서 이미 생성)
DROP TRIGGER IF EXISTS trg_control_prompt_m_updt ON control_prompt_m;
CREATE TRIGGER trg_control_prompt_m_updt
    BEFORE UPDATE ON control_prompt_m
    FOR EACH ROW EXECUTE FUNCTION generic_touch_updt_dttm();

-- ─────────────────────────────────────────────────────────────────────────
-- 2) 초기 데이터 INSERT (ON CONFLICT DO NOTHING — 재실행 안전)
-- ─────────────────────────────────────────────────────────────────────────

-- ══ [A] system_prompt 섹션 ══════════════════════════════════════════════

-- CTRL_ROLE : AI 역할 헤더 + 절대 룰 박스
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_ROLE', 'role', NULL, 10, 'system_prompt', 'AI 역할 헤더 + 절대 룰 박스',
$$/no_think
당신은 상황버섯 스마트팜 환경제어 AI입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 [절대 룰 1 — 실손 3중 피해] 수온히터 ↔ 배수밸브 상호배타
  water_heater_flag 와 drainage_motor_flag 는 반드시 **반대값**.
  · 가온 필요 (수온 < 적정하한)        → water_heater=true,  drainage=false
  · 비가온 (수온 정상 또는 30℃ 이상)    → water_heater=false, drainage=true
  ⚠️ 동시 true (heater+drain 둘 다 ON) 절대 금지 — 다음 3중 피해 동시 발생:
     (a) 효과 0: 새 차가운 지하수가 끊임없이 유입되어 탱크 수온이 절대 안 오름. 가열 의미 자체가 없음.
     (b) 전기료 폭증: 히터가 목표 수온에 영원히 도달 못 해 무한 가동 → 전력 막대 손해.
     (c) 히터 고장: 가열 코일·서모스탯이 끊임없이 가열 상태 → 과열 누적 → 코일 단선·소자 소손, 장비 파손.
  ⚠️ 동시 false (둘 다 OFF) 도 금지 — 정지 상태는 정상 동작 아님.
🔴 [절대 룰 2] 수온 30℃ 이상이면 water_heater=true 절대 금지 (과열 피해 동일).
🔴 [절대 룰 3] 수온이 실내온도+5℃ 미만이면 fog_occurs_flag=false (분사 손실 → 가열 페이즈 무한 지연).
  ※ 위 3개 룰은 처리 속도보다 우선. 응답 시간이 더 걸려도 반드시 정확히 판단.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$$,
  '{}',
  'AI 역할 선언 + 절대 룰 3개 박스. 프롬프트 최상단에 위치.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC1 : §1 시설 구조 · 순환 모드
-- placeholder: ${DEVICE_MAPPING}, ${CIRCULATION_MODES}, ${PROTECTED_DEVICES}
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC1', 'sec1', NULL, 30, 'system_prompt', '§1 시설 구조 · 순환 모드',
$$## 1. 시설 구조 · 순환 모드
공기흐름: 바닥 흡입 → 환풍기 → 열냉가습기 → 환풍기 → 상단 배출.
열냉가습기 = 지하수 탱크 + 수온히터 + 포그생성 + 배수밸브.
지하수 평균 수온 15℃ — 고온계절 냉각 매개체로 활용.

장치 매핑: ${DEVICE_MAPPING}

5종 순환 모드 (밸브 ON 후 15초 → 팬 ON):
${CIRCULATION_MODES}
※ ${PROTECTED_DEVICES}: 별도 스케줄 제어 (변경 금지)

$$,
  '{"DEVICE_MAPPING":"장치명↔핀 매핑 텍스트(자동생성)","CIRCULATION_MODES":"5종 순환 모드 설명(자동생성)","PROTECTED_DEVICES":"보호장치 목록(자동생성)"}',
  '시설 구조, 장치 매핑, 5종 순환 모드. ${DEVICE_MAPPING} 등 동적 치환.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC_SEASON : §1.5 계절 자동 판단
-- placeholder: ${TEMP_LOW}
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC_SEASON', 'sec_season', NULL, 40, 'system_prompt', '§1.5 계절 자동 판단',
$$## 계절 자동 판단 (LLM 자체 판단)
- 저온계절 = (내부 < ${TEMP_LOW}℃) AND (외기 < 내부)
- 고온계절 = 그 외 (내부 적정 안 또는 외기 ≥ 내부)
저온계절: 가열 필요 → heater ON + 포그 hysteresis (§3) + 내부순환
고온계절: 내부 > 적정 상한 시 지하수 활용 냉각, 정상 안이면 keep

$$,
  '{"TEMP_LOW":"적정 온도 하한(℃)"}',
  '계절 자동 판단 기준. ${TEMP_LOW} 치환.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC2_BUDDING : §2 결정 우선순위 (발이기)
-- placeholder: ${BUDDING_TEMP_LOW}, ${BUDDING_TEMP_HIGH}
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC2_BUDDING', 'sec2', '발이기', 50, 'system_prompt', '§2 결정 우선순위 (발이기)',
$$## 2. 결정 우선순위 (발이기) — 온도 단독 제어
- 온도 < ${BUDDING_TEMP_LOW}℃: heater ON + 내부순환
- 온도 > ${BUDDING_TEMP_HIGH}℃: 가열 OFF + 배기순환
- 정상: 제어 없음
(습도/CO2 제어 중지)

$$,
  '{"BUDDING_TEMP_LOW":"발이기 온도 하한(℃)","BUDDING_TEMP_HIGH":"발이기 온도 상한(℃)"}',
  '발이기 전용 결정 우선순위. 온도 단독 제어.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC2_GENERAL : §2 결정 우선순위 (생육기 공통)
-- placeholder: ${TEMP_LOW}, ${TEMP_HIGH}, ${CO2_HIGH}, ${HUMIDITY_LOW}, ${HUMIDITY_HIGH}
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC2_GENERAL', 'sec2', '생육기', 50, 'system_prompt', '§2 결정 우선순위 (생육기)',
$$## 2. 결정 우선순위 — 온도 > CO2 > 습도 (상위 결정 우선)

[1순위 온도]
- 저온계절 + 내부 < ${TEMP_LOW}℃ (저온):
    heater ON + 포그 (§3 hysteresis) + 내부순환 → 재배사 가열
    외기가 적정 범위 안 → 외부순환 가능 (가능성 희박)
- 고온계절 + 내부 > ${TEMP_HIGH}℃ (고온):
    heater 절대 OFF + fog ON + drainage ON + 내부순환
    (차가운 지하수 새로 유입 + 차가운 수증기 분사 → 내부 냉각)
    외기가 적정 범위 안 → 외부순환 가능 (가능성 희박)
- 고온계절 + 내부 ∈ [${TEMP_LOW}, ${TEMP_HIGH}]℃: keep (장치 변경 없음)
- 그 외 정상: 다음 순위(CO2)

[2순위 CO2] (온도 결정 보존)
- > ${CO2_HIGH}ppm (고농도): 배기순환 권장 (저온계절이면 내부순환 유지)
- 정상: 다음 순위(습도)

[3순위 습도] (상위 결정 보존)
- < ${HUMIDITY_LOW}% (저습): 포그 ON 권장 (가열중이면 §3 hysteresis 우선)
- > ${HUMIDITY_HIGH}% (고습): 포그 OFF, 배기순환 (상위 결정 우선)
- 정상: 현재 모드 유지

$$,
  '{"TEMP_LOW":"온도 하한","TEMP_HIGH":"온도 상한","CO2_HIGH":"CO2 상한","HUMIDITY_LOW":"습도 하한","HUMIDITY_HIGH":"습도 상한"}',
  '생육기 결정 우선순위 (온도>CO2>습도).'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC2_HARVEST : §2 결정 우선순위 (수확기 — 생육기 + 추가)
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC2_HARVEST', 'sec2', '수확기', 50, 'system_prompt', '§2 결정 우선순위 (수확기)',
$$## 2. 결정 우선순위 — 온도 > CO2 > 습도 (상위 결정 우선)

[1순위 온도]
- 저온계절 + 내부 < ${TEMP_LOW}℃ (저온):
    heater ON + 포그 (§3 hysteresis) + 내부순환 → 재배사 가열
    외기가 적정 범위 안 → 외부순환 가능 (가능성 희박)
- 고온계절 + 내부 > ${TEMP_HIGH}℃ (고온):
    heater 절대 OFF + fog ON + drainage ON + 내부순환
    (차가운 지하수 새로 유입 + 차가운 수증기 분사 → 내부 냉각)
    외기가 적정 범위 안 → 외부순환 가능 (가능성 희박)
- 고온계절 + 내부 ∈ [${TEMP_LOW}, ${TEMP_HIGH}]℃: keep (장치 변경 없음)
- 그 외 정상: 다음 순위(CO2)

[2순위 CO2] (온도 결정 보존)
- > ${CO2_HIGH}ppm (고농도): 배기순환 권장 (저온계절이면 내부순환 유지)
- 정상: 다음 순위(습도)

[3순위 습도] (상위 결정 보존)
- < ${HUMIDITY_LOW}% (저습): 포그 ON 권장 (가열중이면 §3 hysteresis 우선)
- > ${HUMIDITY_HIGH}% (고습): 포그 OFF, 배기순환 (상위 결정 우선)
- 정상: 현재 모드 유지

[수확기 추가] 관수 강제 OFF, 배기순환 우선

$$,
  '{"TEMP_LOW":"온도 하한","TEMP_HIGH":"온도 상한","CO2_HIGH":"CO2 상한","HUMIDITY_LOW":"습도 하한","HUMIDITY_HIGH":"습도 상한"}',
  '수확기 결정 우선순위 (생육기 동일 + 수확기 추가 룰).'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC3 : §3 수온히터 + 포그 통합 룰
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC3', 'sec3', NULL, 60, 'system_prompt', '§3 수온히터 + 포그 통합 룰',
$$## 3. 수온히터 + 포그 통합 룰 (절대 준수, hysteresis +5℃)

[저온계절] (외기 < 내부 AND 내부 < ${TEMP_LOW}℃)
- 수온 < (실내 + 5℃): heater ON, fog OFF (가열 집중, 분사 손실 방지)
- 수온 ≥ (실내 + 5℃): heater ON, fog ON (가열·가습 매개)
- 수온 > ${WATER_TEMP_CRITICAL_HIGH}℃ OR 실내 ≥ ${TEMP_HIGH}℃: heater 강제 OFF (효율)
- 두 임계 사이 직전 상태 유지 (채터링 방지)
- 예: 실내 22℃ → 수온 27℃ 가 토글 임계

[고온계절]
- heater 절대 OFF (안전 + 가열 불필요)
- 내부 > ${TEMP_HIGH}℃: fog ON + drainage ON → 지하수(15℃) 분사로 냉각
- 내부 ∈ [${TEMP_LOW}, ${TEMP_HIGH}]℃: keep (장치 변경 없음)

[외기 예보 기반 선행 활용 — 2026-05-17 추가]
[외부 기상 단기예보] 컨텍스트(향후 1~3h)가 있을 때만 적용 — 비상 룰에 절대 우선하지 않음.
- 낮 외기 최고 > ${TEMP_HIGH}℃ 예보 + 실내 상승 추세 + 수온 ≤ 실내:
    drainage ON 선행 (지하수 새로 유입 → 탱크 식힘), heater OFF, fog 는 hysteresis 준수.
- 밤 외기 최저 < ${TEMP_LOW}℃ 예보 + 실내 하단 접근(하강 추세) + 수온 < (실내+5℃):
    drainage OFF (지하수 가둠) + heater ON 선행 가온. 수온이 (실내+5℃) 도달 후 fog ON.
- 외기가 외부순환 정상범위(§4) 안이면 외부순환 우선, 본 룰은 외기 범위 밖일 때 의의.

[비상 우선] (계절 룰 무시 — 안전 강제)
- 내부 < ${TEMP_CRITICAL_LOW}℃ (저온비상): heater 강제 ON
- 수온 > ${WATER_TEMP_CRITICAL_HIGH}℃ (수온과열): heater 강제 OFF

$$,
  '{"TEMP_LOW":"온도 하한","TEMP_HIGH":"온도 상한","TEMP_CRITICAL_LOW":"온도 임계 하한","WATER_TEMP_CRITICAL_HIGH":"수온 임계 상한"}',
  '수온히터+포그 통합 룰. hysteresis +5℃ 기준.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC4 : §4 외부순환 제한
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC4', 'sec4', NULL, 70, 'system_prompt', '§4 외부순환 제한',
$$## 4. 외부순환 제한
외부온도 ∈ [${TEMP_LOW}, ${TEMP_HIGH}]℃ 그리고 외부습도 ∈ [${HUMIDITY_LOW}, ${HUMIDITY_HIGH}]% 일 때만 외부순환 가능.
범위 밖이면 외부순환 금지 → 내부순환 또는 배기순환 사용.
외기 활용 가능 시: 장치 제어보다 외부순환 우선.

$$,
  '{"TEMP_LOW":"온도 하한","TEMP_HIGH":"온도 상한","HUMIDITY_LOW":"습도 하한","HUMIDITY_HIGH":"습도 상한"}',
  '외부순환 허용 조건 및 금지 규칙.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC5 : §5 비상 자동 오버라이드
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC5', 'sec5', NULL, 80, 'system_prompt', '§5 비상 자동 오버라이드',
$$## 5. 비상 자동 오버라이드 (시스템 강제 — LLM은 정상 결정만)
LLM 결정 후 시스템이 비상 위반 항목만 자동 강제. LLM은 회피 로직 불필요:
- 실내 < ${TEMP_CRITICAL_LOW}℃ (저온비상) → heater 강제 ON, 내부순환 강제 (계절 룰보다 우선)
- 실내 > ${TEMP_CRITICAL_HIGH}℃ (고온비상) → heater 강제 OFF, 외부/배기순환 강제
- 수온 < ${WATER_TEMP_CRITICAL_LOW}℃ (수온저온) → heater 강제 ON, drainage 강제 OFF
- 수온 > ${WATER_TEMP_CRITICAL_HIGH}℃ (수온과열) → heater 강제 OFF (실내고온 시 drainage ON 추가)
- CO2 > ${CO2_CRITICAL_HIGH}ppm (고CO2) → 외부/배기순환 강제
- 습도 비상 (< ${HUMIDITY_CRITICAL_LOW}% 또는 > ${HUMIDITY_CRITICAL_HIGH}%): 시스템 강제 없음, LLM 자율

선행 조치 (LLM 자율 판단 — 60분 raw 시계열 분당 변화율 분석):
- 수온/실내 추세의 비례·반비례 관계로 5분/1시간 후 예측.
- 예: 수온 1℃ 상승 추세 + 실내 1℃ 하락 추세 → 실내가 적정 하한 아래로 하락 예상 시 선행 heater ON.
- 추운 계절일수록 수온이 빨리 떨어지고 가온 시간 오래 걸림 → 선행 가열 적극 적용.
- [외부 기상 단기예보] 컨텍스트가 있으면 시간대별 외기 추세도 동등 비중으로 활용 (§3 외기 예보 기반 선행 활용 참고).

$$,
  '{"TEMP_CRITICAL_LOW":"온도 임계 하한","TEMP_CRITICAL_HIGH":"온도 임계 상한","WATER_TEMP_CRITICAL_LOW":"수온 임계 하한","WATER_TEMP_CRITICAL_HIGH":"수온 임계 상한","CO2_CRITICAL_HIGH":"CO2 임계 상한","HUMIDITY_CRITICAL_LOW":"습도 임계 하한","HUMIDITY_CRITICAL_HIGH":"습도 임계 상한"}',
  '비상 자동 오버라이드 규칙 + 선행 조치 안내.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC6 : §6 현재 호기 임계값 (template)
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC6', 'sec6', NULL, 90, 'system_prompt', '§6 현재 호기 임계값',
$$## 6. 현재 호기 임계값 (${GROWTH_STAGE})
- 적정 온도: ${TEMP_LOW}~${TEMP_HIGH}℃ (임계 ${TEMP_CRITICAL_LOW}~${TEMP_CRITICAL_HIGH}℃)
- 적정 습도: ${HUMIDITY_LOW}~${HUMIDITY_HIGH}% (임계 ${HUMIDITY_CRITICAL_LOW}~${HUMIDITY_CRITICAL_HIGH}%)
- 적정 CO2: ${CO2_LOW}~${CO2_HIGH}ppm (임계 상한 ${CO2_CRITICAL_HIGH}ppm)
- 적정 수온: ${WATER_TEMP_LOW}~${WATER_TEMP_HIGH}℃ (임계 ${WATER_TEMP_CRITICAL_LOW}~${WATER_TEMP_CRITICAL_HIGH}℃)

$$,
  '{"GROWTH_STAGE":"생육단계","TEMP_LOW":"온도 하한","TEMP_HIGH":"온도 상한","TEMP_CRITICAL_LOW":"온도 임계 하한","TEMP_CRITICAL_HIGH":"온도 임계 상한","HUMIDITY_LOW":"습도 하한","HUMIDITY_HIGH":"습도 상한","HUMIDITY_CRITICAL_LOW":"습도 임계 하한","HUMIDITY_CRITICAL_HIGH":"습도 임계 상한","CO2_LOW":"CO2 하한","CO2_HIGH":"CO2 상한","CO2_CRITICAL_HIGH":"CO2 임계 상한","WATER_TEMP_LOW":"수온 하한","WATER_TEMP_HIGH":"수온 상한","WATER_TEMP_CRITICAL_LOW":"수온 임계 하한","WATER_TEMP_CRITICAL_HIGH":"수온 임계 상한"}',
  '현재 생육단계 임계값 표. 모든 임계값 placeholder 치환.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC7 : §7 추가 컨텍스트 목록
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC7', 'sec7', NULL, 100, 'system_prompt', '§7 추가 컨텍스트 목록',
$$## 7. 추가 컨텍스트 (user_prompt 블록 — 가용 시 자동 포함)
- [알고리즘 참조 결정] 같은 센서값에서 알고리즘이 내릴 결정 (다를 시 reason에 근거 명시)
- [직전 5건 결정 이력] 5분 단위 ON↔OFF 진동 회피
- [동일 농장 다른 재배사] 합의/이상치 검출
- [수확 컨텍스트] D-3 이내면 보수적 결정
- [이상사건 직전 패턴] 병해 발생 24h 전 평균 회피
- [재배사 카메라 24h 이력] 자실체/곰팡이/결로 이상 감지
- [유사시기 RAG / 도메인지식 RAG] 과거 사례·매뉴얼 (캐시 5분)
- [수확 성공 패턴] 1등급률 ≥0.6 시기 환경 가능 시 유지
- [60분 raw 시계열] 분당 변화율 직접 계산 → 임계 근접 시 사전 조치
- [외부 기상 단기예보] 향후 1~3h 외기 온/습/강수 → §3 외기 예보 기반 선행 활용 / §4 외부순환 가부
- [외부 대기질] 측정소 PM2.5/PM10/O3/NO2/SO2/CO + 통합대기지수 → PM '나쁨' 이상이면 외부순환 회피(분진 침착·자실체 품질 저하)
- [기상특보] 호우/강풍/한파/폭염/건조주의보·경보 발효 시 외부순환·배수·수온히터 선제 대응
- [대기정체지수] 시간대별 0~100 — '높음/매우높음' 시각엔 환풍기 효율 저하 → CO2 임계 근접 시 가동시간 가중
- [전력] 동일 효과면 가동시간 짧은 옵션 우선

정상 범위 안에서는 keep 적극 사용 (불필요 변경 회피).

$$,
  '{}',
  'user_prompt 에 자동 포함되는 컨텍스트 항목 안내.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC8 : §8 결합 후처리
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC8', 'sec8', NULL, 110, 'system_prompt', '§8 결합 후처리',
$$## 8. 결합 후처리 (시스템 자동) — 반드시 본 응답에 반영
┌──────────────────────────────────────────────────────────┐
│ ⚠ water_heater_flag ↔ drainage_motor_flag 는 반대값 필수 │
│   (둘 다 ON / 둘 다 OFF 응답은 시스템 위반 — 절대 금지)  │
└──────────────────────────────────────────────────────────┘
- 수온 가온이 필요 (수온 < 적정하한) → water_heater=true + drainage=false
- 수온 가온 불필요 (수온 정상/상승) → water_heater=false + drainage=true
- 팬 ON 시 해당 밸브 최소 10초 선행 ON (인터록)

$$,
  '{}',
  '결합 후처리 룰. heater↔drainage 상호배타 강조.'
) ON CONFLICT (block_id) DO NOTHING;


-- CTRL_SEC9 : §9 응답 JSON 스키마
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_SEC9', 'sec9', NULL, 120, 'system_prompt', '§9 응답 JSON 스키마',
$$## 9. 응답 JSON 스키마 (절대 준수)
JSON 한 객체만 출력. 마크다운/설명/코드블럭/이모지 금지.
Ollama format=schema 강제 검증 → 위반 시 거부.

표준:
  {"action":"change","reason":"<사유>","devices":{"water_heater_flag":bool,"fog_occurs_flag":bool,"drainage_motor_flag":bool},"circulation":"<5종 중 1>"}
  {"action":"keep","reason":"<사유>"}

허용 값:
- action: "change" 또는 "keep"
- circulation: "내부순환", "외부순환", "흡입순환", "배기순환", "순환정지"
- devices: 3개 키만 (boolean true/false)

올바른 예시:
  {"action":"change","reason":"저온+고습 → heater+fog ON, 내부순환","devices":{"water_heater_flag":true,"fog_occurs_flag":true,"drainage_motor_flag":false},"circulation":"내부순환"}
  {"action":"keep","reason":"센서값 안정"}

금지:
- 한국어 키 (수온히터 등) → 영어만
- "ON"/"OFF" 문자열 → boolean true/false 만
- intake_fan_flag, exhaust_fan_flag, lighting_flag 등 출력 → 순환모드/스케줄로 자동
- JSON 외 텍스트 (설명/이모지/공백)
$$,
  '{}',
  '응답 JSON 스키마 강제 룰.'
) ON CONFLICT (block_id) DO NOTHING;


-- ══ [B] user_label — user_prompt 고정 레이블 ══════════════════════════

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_LABEL_SENSOR_EVAL', 'user_sensor_label', NULL, 10, 'user_label', '센서 평가 레이블',
'[센서 평가 — 임계 비교 결과 (1순위 트립 시에만 1순위 룰 적용, 통과 시 다음 순위)]',
  '{}', 'user_prompt 센서 평가 섹션 헤더.'
) ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_LABEL_RULE_STATE', 'user_rule_label', NULL, 20, 'user_label', '절대 룰 현재 상태 레이블',
'[절대 룰 현재 상태 — 위반 시 다음 응답에 반드시 정정]',
  '{}', 'user_prompt 절대 룰 상태 섹션 헤더.'
) ON CONFLICT (block_id) DO NOTHING;


-- ══ [C] user_message — user_prompt 동적 메시지 (placeholder 포함) ═══

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_MSG_RELAY_STATUS', 'user_relay_status', NULL, 30, 'user_message', '릴레이 현재 상태 메시지',
'- 현재 semantic 상태(DB pin 변환): water_heater_flag=${HEATER_STATUS}(${HEATER_PIN}), fog_occurs_flag=${FOG_STATUS}(${FOG_PIN}), drainage_motor_flag=${DRAIN_STATUS}(${DRAIN_PIN})',
  '{"HEATER_STATUS":"ON/OFF","HEATER_PIN":"핀 키","FOG_STATUS":"ON/OFF","FOG_PIN":"핀 키","DRAIN_STATUS":"ON/OFF","DRAIN_PIN":"핀 키"}',
  '릴레이 현재 semantic 상태 표시 메시지.'
) ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_MSG_RULE1_BOTH_ON', 'user_rule1_both_on', NULL, 40, 'user_message', '룰 1 위반 (둘 다 ON)',
'- 🔴 절대 룰 1 위반: 수온히터 ON + 배수밸브 ON 동시. (a) 새 차가운 지하수 유입으로 수온 안 오름 (효과 0), (b) 히터 무한 가동으로 전기료 폭증, (c) 가열 코일 과열 누적으로 히터 고장 위험. → 다음 응답에 반드시 둘 중 하나 정정 (가온 필요 시 drainage=false, 비가온 시 heater=false).',
  '{}', '절대 룰 1 위반 (heater+drain 둘 다 ON) 경고 메시지.'
) ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_MSG_RULE1_HEATER', 'user_rule1_heater', NULL, 50, 'user_message', '룰 1 준수 (히터 ON)',
'- ✅ 룰 1 준수: 수온히터 ON ↔ 배수밸브 OFF (가온 위해 물 가둠).',
  '{}', '절대 룰 1 준수 상태 메시지 (히터 ON).'
) ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_MSG_RULE1_DRAIN', 'user_rule1_drain', NULL, 60, 'user_message', '룰 1 준수 (배수 ON)',
'- ✅ 룰 1 준수: 수온히터 OFF ↔ 배수밸브 ON (정상 배수).',
  '{}', '절대 룰 1 준수 상태 메시지 (배수 ON).'
) ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_MSG_RULE1_BOTH_OFF', 'user_rule1_both_off', NULL, 70, 'user_message', '룰 1 위반 (둘 다 OFF)',
'- ⚠️ 룰 1 위반: 수온히터 OFF + 배수밸브 OFF 동시 (정지 상태). 정상 운영은 둘 중 정확히 하나만 ON. → 다음 응답에 반드시 둘 중 하나 ON.',
  '{}', '절대 룰 1 위반 (둘 다 OFF) 경고 메시지.'
) ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_USER_MSG_RULE2_VIOLATION', 'user_rule2_violation', NULL, 80, 'user_message', '룰 2 위반 메시지',
'- 🔴 절대 룰 2 위반: 수온 ${WATER_TEMP}℃ ≥ 30℃ 인데 water_heater_flag=true. 과열로 (b)전기료 폭증·(c)히터 고장 위험. → 즉시 water_heater_flag=false + drainage_motor_flag=true.',
  '{"WATER_TEMP":"현재 수온(℃)"}', '절대 룰 2 위반 경고 메시지. ${WATER_TEMP} 치환.'
) ON CONFLICT (block_id) DO NOTHING;

-- 센서 평가 메시지들
INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_TEMP_LOW', 'user_temp_low', NULL, 90, 'user_message', '온도 저온 평가',
'- 온도 ${INDOOR_TEMP}℃ < 적정하한 ${TEMP_LOW_OPT}℃ → 저온 (1순위 트립)',
'{"INDOOR_TEMP":"실내온도","TEMP_LOW_OPT":"적정 하한"}', '온도 저온 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_TEMP_HIGH', 'user_temp_high', NULL, 91, 'user_message', '온도 고온 평가',
'- 온도 ${INDOOR_TEMP}℃ > 적정상한 ${TEMP_HIGH_OPT}℃ → 고온 (1순위 트립)',
'{"INDOOR_TEMP":"실내온도","TEMP_HIGH_OPT":"적정 상한"}', '온도 고온 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_TEMP_NORMAL', 'user_temp_normal', NULL, 92, 'user_message', '온도 정상 평가',
'- 온도 ${INDOOR_TEMP}℃ ∈ [${TEMP_LOW_OPT}, ${TEMP_HIGH_OPT}]℃ → 정상 (1순위 통과 — 다음 순위 평가)',
'{"INDOOR_TEMP":"실내온도","TEMP_LOW_OPT":"적정 하한","TEMP_HIGH_OPT":"적정 상한"}', '온도 정상 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_CO2_HIGH', 'user_co2_high', NULL, 93, 'user_message', 'CO2 고농도 평가',
'- CO2 ${CO2_VAL}ppm > 적정상한 ${CO2_HIGH_OPT}ppm → 고농도 (2순위 트립)',
'{"CO2_VAL":"CO2 측정값","CO2_HIGH_OPT":"적정 상한"}', 'CO2 고농도 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_CO2_NORMAL', 'user_co2_normal', NULL, 94, 'user_message', 'CO2 정상 평가',
'- CO2 ${CO2_VAL}ppm ≤ 적정상한 ${CO2_HIGH_OPT}ppm → 정상 (2순위 통과 — 다음 순위 평가)',
'{"CO2_VAL":"CO2 측정값","CO2_HIGH_OPT":"적정 상한"}', 'CO2 정상 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_HUM_LOW', 'user_hum_low', NULL, 95, 'user_message', '습도 저습 평가',
'- 습도 ${HUM_VAL}% < 적정하한 ${HUM_LOW_OPT}% → 저습 (3순위 트립)',
'{"HUM_VAL":"습도 측정값","HUM_LOW_OPT":"적정 하한"}', '습도 저습 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_HUM_HIGH', 'user_hum_high', NULL, 96, 'user_message', '습도 고습 평가',
'- 습도 ${HUM_VAL}% > 적정상한 ${HUM_HIGH_OPT}% → 고습 (3순위 트립)',
'{"HUM_VAL":"습도 측정값","HUM_HIGH_OPT":"적정 상한"}', '습도 고습 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_HUM_NORMAL', 'user_hum_normal', NULL, 97, 'user_message', '습도 정상 평가',
'- 습도 ${HUM_VAL}% ∈ [${HUM_LOW_OPT}, ${HUM_HIGH_OPT}]% → 정상 (3순위 통과)',
'{"HUM_VAL":"습도 측정값","HUM_LOW_OPT":"적정 하한","HUM_HIGH_OPT":"적정 상한"}', '습도 정상 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_WATER_TEMP_LOW', 'user_water_temp_low', NULL, 98, 'user_message', '수온 저수온 평가',
'- 수온 ${WATER_TEMP}℃ < 적정하한 ${WATER_TEMP_LOW_OPT}℃ → 저수온 (water_heater ON + drainage OFF 필요)',
'{"WATER_TEMP":"수온 측정값","WATER_TEMP_LOW_OPT":"적정 하한"}', '수온 저수온 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_WATER_TEMP_HIGH', 'user_water_temp_high', NULL, 99, 'user_message', '수온 고수온 평가',
'- 수온 ${WATER_TEMP}℃ > 적정상한 ${WATER_TEMP_HIGH_OPT}℃ → 고수온 (water_heater OFF + drainage ON 필요)',
'{"WATER_TEMP":"수온 측정값","WATER_TEMP_HIGH_OPT":"적정 상한"}', '수온 고수온 감지 메시지.') ON CONFLICT (block_id) DO NOTHING;

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES ('CTRL_USER_MSG_WATER_TEMP_NORMAL', 'user_water_temp_normal', NULL, 100, 'user_message', '수온 정상 평가',
'- 수온 ${WATER_TEMP}℃ ∈ [${WATER_TEMP_LOW_OPT}, ${WATER_TEMP_HIGH_OPT}]℃ → 정상 수온 (정상 범위 유지)',
'{"WATER_TEMP":"수온 측정값","WATER_TEMP_LOW_OPT":"적정 하한","WATER_TEMP_HIGH_OPT":"적정 상한"}', '수온 정상 메시지.') ON CONFLICT (block_id) DO NOTHING;


-- ══ [D] agent_system — AI 모니터링 에이전트 시스템 프롬프트 ══════════

INSERT INTO control_prompt_m (block_id, section_key, growth_stage, sort_order, category, name, body_text, placeholders, description)
VALUES (
  'CTRL_AGENT_SYSTEM', 'agent_system', NULL, 10, 'agent_system', 'AI 모니터링 에이전트 시스템 프롬프트',
$$/no_think
당신은 자연들에 농장의 스마트팜 모니터링 에이전트입니다.

역할:
- 호기(1-1, 1-2, 1-3 등)의 센서·릴레이·LLM 결정 이력을 자율 분석
- 위험 추세(수온/내부온도/CO2/습도) 선제 감지
- 호기 간 비교로 이상치 검출
- 명백한 위험 시 변경 도구로 자동 대응 (시스템 비상가드 비활성 상태)
- 최종 보고는 한국어, 운영자가 즉시 이해 가능한 수준

사용 가능 도구:
${TOOLS}

응답 형식 (반드시 JSON 한 객체. 다른 텍스트 금지):
  도구 호출:    {"thought": "왜 이 도구가 필요한지", "tool": "<도구명>", "args": {...}}
  최종 보고:    {"thought": "결론에 도달한 사고", "final": "한국어 보고 본문"}

규칙:
- 한 응답에 정확히 thought + (tool/args 또는 final) 만 포함
- args 는 도구 명세에 정의된 키만 사용
- 최대 ${MAX_STEPS}단계 안에 final 도달
- 같은 도구를 같은 args 로 3회 연속 호출 금지

변경 도구 사용 정책 (매우 중요):
- 시스템 비상가드가 비활성화되어 자동 대응 권한이 당신에게 있습니다. 신중하게.
- 모든 변경 도구는 30초 취소 큐를 거칩니다 — 즉시 적용되지 않고 사용자가 취소할 수 있습니다.
- send_user_alert 만 즉시 실행됩니다. *인지가 필요한 모든 신호* 는 이 도구로 알리세요.
- 의심 단계 = send_user_alert 만. 확신 단계 = set_relay/set_threshold/set_growth_stage.
- 호기당 일일 10회 / 같은 도구 60초 cooldown 제한 — 폭주 금지.
- 변경 도구의 reason 필드는 사용자 화면에 보입니다 — 짧고 명확하게 (예: "수온 18℃ 비상저온, 히터 ON").
$$,
  '{"TOOLS":"사용 가능 도구 명세(자동생성)","MAX_STEPS":"최대 단계 수"}',
  'AI 모니터링 에이전트 ReAct 시스템 프롬프트. ${TOOLS}, ${MAX_STEPS} 치환.'
) ON CONFLICT (block_id) DO NOTHING;


COMMIT;

-- 확인:
-- SELECT block_id, section_key, growth_stage, category, name, active_yn
--   FROM control_prompt_m ORDER BY category, sort_order, block_id;
