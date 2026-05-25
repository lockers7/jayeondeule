-- ═════════════════════════════════════════════════════════════════════════
-- Migration 002 — SENSOR_M_SETTING 에 updt_dttm 추가 + 자동 갱신 트리거
--
-- 목적: ai_thresholds 캐시가 setn_dttm 만 비교하면 UPDATE(기존 row 수정) 시
--       캐시가 업데이트 안 됨. updt_dttm 컬럼을 추가하여 INSERT/UPDATE 모두
--       즉시 감지 가능하게 한다.
-- 적용 대상: jayeondeule (postgres)
-- 적용 명령:
--   PGPASSWORD='Wkdusemfdp1@' psql -h 127.0.0.1 -U postgres -d jayeondeule \
--     -f /workspace/jayeondeule/db/migrations/002_sensor_m_setting_updt_dttm.sql
-- 롤백:
--   ALTER TABLE sensor_m_setting DROP COLUMN updt_dttm;
--   DROP FUNCTION IF EXISTS sensor_m_setting_touch_updt() CASCADE;
-- ═════════════════════════════════════════════════════════════════════════

BEGIN;

-- 1) updt_dttm 컬럼 추가 (멱등 — IF NOT EXISTS)
ALTER TABLE sensor_m_setting
  ADD COLUMN IF NOT EXISTS updt_dttm timestamp NOT NULL DEFAULT NOW();

COMMENT ON COLUMN sensor_m_setting.updt_dttm IS
  'row INSERT/UPDATE 시각 — ai_thresholds 캐시 변경 감지용';

-- 2) 기존 row 의 updt_dttm 을 setn_dttm 으로 백필 (정확한 audit 보존)
UPDATE sensor_m_setting
   SET updt_dttm = setn_dttm
 WHERE updt_dttm IS NULL OR updt_dttm = setn_dttm;
-- (위 조건 두 번째: ALTER 직후 DEFAULT NOW() 가 들어간 row 만 setn_dttm 으로 되돌림)

-- 3) UPDATE 트리거 — UPDATE 시 updt_dttm 자동 NOW()
CREATE OR REPLACE FUNCTION sensor_m_setting_touch_updt()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updt_dttm := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sensor_m_setting_updt ON sensor_m_setting;
CREATE TRIGGER trg_sensor_m_setting_updt
    BEFORE UPDATE ON sensor_m_setting
    FOR EACH ROW EXECUTE FUNCTION sensor_m_setting_touch_updt();

COMMIT;

-- 확인:
-- SELECT farm_id, hous_id, setn_dttm, updt_dttm FROM sensor_m_setting
--  ORDER BY farm_id, hous_id, setn_dttm DESC LIMIT 10;
