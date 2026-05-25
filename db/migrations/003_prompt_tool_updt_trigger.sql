-- ═════════════════════════════════════════════════════════════════════════
-- Migration 003 — PROMPT_BLOCK_M / TOOL_DEFINITION_M updt_dttm 자동 갱신 트리거
--
-- 목적: 두 테이블 모두 updt_dttm 컬럼은 이미 있으나 Hibernate 등의 자동 갱신
--       메커니즘 부재. UPDATE 시 NOW() 로 갱신되도록 트리거 추가.
--       prompt_registry 캐시 invalidate 의 신뢰성 확보.
-- 적용 명령:
--   PGPASSWORD='Wkdusemfdp1@' psql -h 127.0.0.1 -U postgres -d jayeondeule \
--     -f /workspace/jayeondeule/db/migrations/003_prompt_tool_updt_trigger.sql
-- ═════════════════════════════════════════════════════════════════════════

BEGIN;

-- ────────────────────────────────────────────────────────────────────
-- 공통 trigger function — UPDATE 시 NEW.updt_dttm := NOW()
-- (sensor_m_setting 의 touch_updt 와 동일 패턴이지만 컬럼 이름 동일하므로 재사용 가능)
-- ────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION generic_touch_updt_dttm()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updt_dttm := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ────────────────────────────────────────────────────────────────────
-- PROMPT_BLOCK_M 트리거
-- ────────────────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_prompt_block_m_updt ON prompt_block_m;
CREATE TRIGGER trg_prompt_block_m_updt
    BEFORE UPDATE ON prompt_block_m
    FOR EACH ROW EXECUTE FUNCTION generic_touch_updt_dttm();

-- ────────────────────────────────────────────────────────────────────
-- TOOL_DEFINITION_M 트리거
-- ────────────────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_tool_definition_m_updt ON tool_definition_m;
CREATE TRIGGER trg_tool_definition_m_updt
    BEFORE UPDATE ON tool_definition_m
    FOR EACH ROW EXECUTE FUNCTION generic_touch_updt_dttm();

COMMIT;

-- 확인:
-- SELECT trigger_name, event_object_table FROM information_schema.triggers
--  WHERE event_object_table IN ('prompt_block_m','tool_definition_m');
