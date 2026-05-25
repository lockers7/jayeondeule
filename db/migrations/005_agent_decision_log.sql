-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 005 — agent_decision_log 테이블 신설 (Phase 2)
--
-- 목적:
--   AI 모니터링 agent (ai_monitor_agent.py) 의 모든 실행 결과를 영속화.
--   기존 ai_decision_log (스케줄 LLM 결정) 와 분리된 별도 테이블 —
--   agent 는 ReAct 다단계 + 도구 호출 + 최종 보고 형태로 다른 schema.
--
-- 사용처:
--   · agent_scheduler.py 의 30분 cron → 매 실행 INSERT
--   · web UI '/agent-history' → SELECT (Phase 4)
--
-- 멱등 — 재실행해도 안전 (CREATE TABLE IF NOT EXISTS).
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_decision_log (
  id            BIGSERIAL PRIMARY KEY,
  started_at    TIMESTAMP NOT NULL DEFAULT NOW(),
  ended_at      TIMESTAMP,
  trigger_type  VARCHAR(20) NOT NULL,        -- 'schedule' / 'event' / 'user'
  farm_id       INT,                          -- 분석 대상 농장 (NULL = 다농장)
  task          TEXT NOT NULL,                -- 사용자/스케줄러 지시문
  steps         JSONB,                        -- ReAct step history (thought/tool/args/result/final)
  final_report  TEXT,                         -- final 보고 본문 (NULL = 미도달)
  success       BOOLEAN NOT NULL,
  reason        TEXT,                         -- 실패 사유 (success=FALSE 시)
  duration_sec  NUMERIC(8,2),
  llm_calls     INT,                          -- 사이클 안 LLM 호출 횟수
  tool_calls    JSONB,                        -- 도구별 호출 카운트 {tool_name: count, ...}
  model         VARCHAR(50)                   -- 사용한 LLM 모델명 (gemma3:27b 등)
);

-- 검색 인덱스 — 최근 시각 역순 조회가 가장 빈번
CREATE INDEX IF NOT EXISTS idx_agent_log_started_desc
  ON agent_decision_log (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_log_trigger
  ON agent_decision_log (trigger_type, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_log_farm
  ON agent_decision_log (farm_id, started_at DESC) WHERE farm_id IS NOT NULL;

-- 코멘트
COMMENT ON TABLE agent_decision_log IS 'AI 모니터링 agent 실행 이력 (Phase 2, 2026-05-25)';
COMMENT ON COLUMN agent_decision_log.steps IS 'ReAct step 배열. 각 step: {step, thought, tool?, args?, tool_result?, final?, error?}';
COMMENT ON COLUMN agent_decision_log.tool_calls IS '도구별 호출 카운트. 예: {"get_sensor_window": 2, "compare_houses": 1}';
