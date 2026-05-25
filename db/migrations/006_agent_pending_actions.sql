-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 006 — agent_pending_actions 테이블 신설 (Phase 3)
--
-- 목적:
--   AI agent 가 호출한 *write 도구* 를 즉시 실행하지 않고 30초 큐에 보관.
--   사용자가 30초 안 취소 가능. 시간 도달 시 별도 worker (agent_pending_worker)
--   가 status=pending → executed 로 전환하며 실제 하드웨어/DB 변경 수행.
--
-- 비상가드 disable 정책 (2026-05-17) 상태에서 agent set_relay 가 유일한 자동
-- 대응 경로 → 이 큐가 마지막 방어선:
--   ① cancellable_seconds (기본 30) 사용자 취소권
--   ② daily_limit (기본 호기당 10회) — write 시점 검증
--   ③ cooldown_seconds (기본 60) 동일 도구 재호출 차단
--   ④ relay_manager 인터록 게이트 (실행 단계에서)
--
-- 멱등 — 재실행 안전.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_pending_actions (
  id               BIGSERIAL PRIMARY KEY,
  created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
  execute_at       TIMESTAMP NOT NULL,                     -- created_at + cancellable_seconds
  agent_log_id     BIGINT REFERENCES agent_decision_log(id) ON DELETE SET NULL,
  trigger_type     VARCHAR(20) NOT NULL,                   -- 'schedule' / 'event' / 'user'
  tool_name        VARCHAR(50) NOT NULL,                   -- 'set_relay', 'set_threshold', 'set_growth_stage', 'send_user_alert'
  args             JSONB NOT NULL,                         -- 도구 호출 인자
  reason           TEXT,                                   -- LLM 이 결정한 사유 (final_report 발췌)
  status           VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending / executed / cancelled / failed
  executed_at      TIMESTAMP,                              -- 실제 실행 시각
  exec_result      JSONB,                                  -- {success, message, ...}
  cancelled_by     VARCHAR(50),                            -- 'user:<id>' / 'system:<reason>'
  cancelled_reason TEXT
);

-- worker polling 용 — pending + 실행시점 도달 row 빠른 조회
CREATE INDEX IF NOT EXISTS idx_pending_status_exec_at
  ON agent_pending_actions (status, execute_at)
  WHERE status = 'pending';

-- agent_decision_log → pending action 역추적
CREATE INDEX IF NOT EXISTS idx_pending_log
  ON agent_pending_actions (agent_log_id)
  WHERE agent_log_id IS NOT NULL;

-- 최근 활동 조회 (Web UI Phase 4)
CREATE INDEX IF NOT EXISTS idx_pending_created_desc
  ON agent_pending_actions (created_at DESC);

-- 도구별 cooldown / daily_limit 검증
CREATE INDEX IF NOT EXISTS idx_pending_tool
  ON agent_pending_actions (tool_name, created_at DESC);

-- 코멘트
COMMENT ON TABLE agent_pending_actions IS 'AI agent write 도구의 취소 가능 큐 (Phase 3, 2026-05-25)';
COMMENT ON COLUMN agent_pending_actions.execute_at IS 'created_at + cancellable_seconds. 이 시각 도달 + status=pending 일 때 worker 가 실행';
COMMENT ON COLUMN agent_pending_actions.status IS 'pending: 큐 대기 / executed: 실행 완료 / cancelled: 사용자/시스템 취소 / failed: 실행 실패';
COMMENT ON COLUMN agent_pending_actions.cancelled_by IS '취소 주체. user:<id> 또는 system:cooldown / system:daily_limit / system:interlock';
