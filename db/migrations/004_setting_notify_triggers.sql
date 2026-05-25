-- ═════════════════════════════════════════════════════════════════════════
-- Migration 004 — setting 테이블 변경 시 PostgreSQL NOTIFY 발화
--
-- 목적: web UI 또는 다른 클라이언트가 setting 테이블을 INSERT/UPDATE/DELETE 하면
--       Python 측이 폴링 없이 즉시 캐시 invalidate 가능. (Phase 5)
--
-- 채널: setting_changed
-- payload (JSON): {"table": "<table_name>", "op": "INSERT|UPDATE|DELETE", "ids": "<keys>"}
--
-- 적용 대상 테이블:
--   - light_irrigation_s_setting   (관수/조명)
--   - sensor_m_setting             (센서 임계)
--   - schedule_m_setting           (통합 스케줄)
--   - prompt_block_m               (시스템 프롬프트)
--   - tool_definition_m            (도구 정의)
--   - farm_m_info                  (농장)
--   - farmhouse_m_info             (재배사)
--
-- 적용 명령:
--   PGPASSWORD='Wkdusemfdp1@' psql -h 127.0.0.1 -U postgres -d jayeondeule \
--     -f /workspace/jayeondeule/db/migrations/004_setting_notify_triggers.sql
-- ═════════════════════════════════════════════════════════════════════════

BEGIN;

-- ────────────────────────────────────────────────────────────────────
-- 공통 NOTIFY 함수 — TG_TABLE_NAME / TG_OP 자동 활용.
-- payload 는 단순 문자열 (Python json.loads 로 디코드).
-- ────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION setting_notify_change()
RETURNS TRIGGER AS $$
DECLARE
    payload text;
BEGIN
    payload := json_build_object(
        'table', TG_TABLE_NAME,
        'op',    TG_OP,
        'ts',    extract(epoch from NOW())
    )::text;
    PERFORM pg_notify('setting_changed', payload);
    -- AFTER 트리거이므로 RETURN 값은 무시됨
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- ────────────────────────────────────────────────────────────────────
-- 각 테이블에 AFTER INSERT/UPDATE/DELETE STATEMENT 트리거 부착.
-- STATEMENT 레벨 — 다중 row 변경 시 1회만 NOTIFY (payload 부풀림 방지).
-- ────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    t text;
    tables text[] := ARRAY[
        'light_irrigation_s_setting',
        'sensor_m_setting',
        'schedule_m_setting',
        'prompt_block_m',
        'tool_definition_m',
        'farm_m_info',
        'farmhouse_m_info'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_notify ON %I;', t, t);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_notify '
            ' AFTER INSERT OR UPDATE OR DELETE ON %I '
            ' FOR EACH STATEMENT EXECUTE FUNCTION setting_notify_change();',
            t, t
        );
    END LOOP;
END $$;

COMMIT;

-- 확인:
-- SELECT trigger_name, event_object_table, event_manipulation
--   FROM information_schema.triggers
--  WHERE trigger_name LIKE 'trg_%_notify'
--  ORDER BY event_object_table;
