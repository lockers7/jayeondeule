-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 007 — agent_subscriptions + agent_user_alerts (Phase 4 B 단계)
--
-- 목적:
--   채팅창에서 "1시간마다 X 모니터링하라" 같은 *반복 의도* 를 등록 가능.
--   agent_scheduler 가 매 분 polling 으로 due subscription 을 ai_monitor_agent
--   에 실행 위임. 결과 중 사용자가 봐야 할 내용은 agent_user_alerts 에 영속.
--   채팅 프론트엔드는 마지막 read_id 부터 폴링 (또는 향후 SSE).
--
--   기존 schedule_monitor (간단 임계값 체크) 와 분리 — agent_subscriptions 는
--   ai_monitor_agent.run_agent (ReAct 다단계 분석) 호출.
--
-- 멱등 — 재실행 안전 (CREATE TABLE IF NOT EXISTS).
-- ═══════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────
-- 1) agent_subscriptions — 반복 agent task 등록부
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_subscriptions (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  user_id         VARCHAR(50),                       -- 채팅 발신자 식별 (없으면 NULL = global)
  farm_id         INT,
  house_id        INT,                                -- NULL = 다호기 / "all"
  interval_min    INT NOT NULL CHECK (interval_min >= 1 AND interval_min <= 1440),
  task            TEXT NOT NULL,                      -- agent 에 전달할 작업 (한국어)
  intent          TEXT,                               -- 사용자 자연어 원문 (감사용)
  last_run_at     TIMESTAMP,                          -- 마지막 사이클 시각 (NULL = 미실행)
  next_run_at     TIMESTAMP NOT NULL DEFAULT NOW(),   -- 다음 사이클 예정 시각
  active          BOOLEAN NOT NULL DEFAULT TRUE,      -- false = 사용자 취소
  cancelled_at    TIMESTAMP,
  cancelled_by    VARCHAR(50),                        -- 'user' / 'system:...'
  total_runs      INT NOT NULL DEFAULT 0
);

-- worker polling — active + next_run_at 도달 row 빠른 조회
CREATE INDEX IF NOT EXISTS idx_sub_active_next
  ON agent_subscriptions (next_run_at)
  WHERE active = TRUE;

-- 사용자별 list 조회
CREATE INDEX IF NOT EXISTS idx_sub_user
  ON agent_subscriptions (user_id, active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sub_farm
  ON agent_subscriptions (farm_id, active, created_at DESC);


-- ─────────────────────────────────────────────────────────────────────────
-- 2) agent_user_alerts — agent 결과 중 사용자 알림용 큐
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_user_alerts (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  user_id         VARCHAR(50),                        -- 수신자 (NULL = broadcast)
  subscription_id BIGINT REFERENCES agent_subscriptions(id) ON DELETE SET NULL,
  agent_log_id    BIGINT REFERENCES agent_decision_log(id) ON DELETE SET NULL,
  level           VARCHAR(20) NOT NULL DEFAULT 'info', -- 'info' / 'warning' / 'critical'
  title           VARCHAR(200),
  body            TEXT NOT NULL,                       -- final_report 또는 LLM 요약
  read_at         TIMESTAMP,                           -- NULL = unread
  delivered_via   VARCHAR(20) DEFAULT 'queue'          -- 'queue' / 'sse' / 'webhook'
);

-- 사용자별 unread 알림 빠른 조회
CREATE INDEX IF NOT EXISTS idx_alert_user_unread
  ON agent_user_alerts (user_id, created_at DESC)
  WHERE read_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_alert_subscription
  ON agent_user_alerts (subscription_id, created_at DESC)
  WHERE subscription_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_alert_created_desc
  ON agent_user_alerts (created_at DESC);


-- ─────────────────────────────────────────────────────────────────────────
-- 코멘트
-- ─────────────────────────────────────────────────────────────────────────
COMMENT ON TABLE agent_subscriptions IS '사용자 채팅 등록 반복 agent task (Phase 4 B, 2026-05-25)';
COMMENT ON COLUMN agent_subscriptions.next_run_at IS 'agent_scheduler 가 매 분 polling. 도달 시 ai_monitor_agent.run_agent 실행 후 next_run_at += interval_min';
COMMENT ON COLUMN agent_subscriptions.active IS 'FALSE = 사용자 취소 — polling 무시';

COMMENT ON TABLE agent_user_alerts IS 'agent 결과 중 사용자 알림용 큐 (Phase 4 B, 2026-05-25)';
COMMENT ON COLUMN agent_user_alerts.read_at IS '채팅 프론트엔드가 alert 표시 후 markread 호출 → read_at=NOW()';
