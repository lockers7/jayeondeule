-- ════════════════════════════════════════════════════════════════════════════
-- [2026-04-28] SENSOR_M_SETTING 비상·발이기 임계 컬럼 추가
-- 사용자 요구: "센서값은 절대 하드코딩 금지 — 테이블 컬럼 값만 변경하면 되어야 한다"
-- 기존 정상 범위 컬럼(tprt_min/max 등)에 더해 비상 범위·발이기 임계를 모두
-- 테이블에서 관리하도록 컬럼 추가. 기존 행은 자동 백필.
--
-- 운영 안내:
--   • 본 SQL 은 IF NOT EXISTS 조건이라 여러 번 실행해도 안전.
--   • UPDATE 문은 NULL 인 컬럼만 백필하므로 운영자가 이미 입력한 값은 보존.
--   • 실행:
--       sudo -u postgres psql -d <DB명> -f setup/migrate_sensor_setting_thresholds.sql
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE SENSOR_M_SETTING
    ADD COLUMN IF NOT EXISTS tprt_crit_min       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS tprt_crit_max       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmdt_crit_min       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmdt_crit_max       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS co2_crit_max        NUMERIC,
    ADD COLUMN IF NOT EXISTS watr_tprt_crit_min  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS watr_tprt_crit_max  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bud_tprt_min        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bud_tprt_max        DOUBLE PRECISION;

-- 기존 행 백필 — 운영자가 아직 비상 범위를 입력하지 않은 행에만 자동 도출 적용
UPDATE SENSOR_M_SETTING SET
    tprt_crit_min      = COALESCE(tprt_crit_min,      tprt_min - 2),
    tprt_crit_max      = COALESCE(tprt_crit_max,      tprt_max + 3),
    hmdt_crit_min      = COALESCE(hmdt_crit_min,      GREATEST(0::double precision,   hmdt_min - 5)),
    hmdt_crit_max      = COALESCE(hmdt_crit_max,      LEAST(100::double precision,    hmdt_max + 10)),
    co2_crit_max       = COALESCE(co2_crit_max,       (co2_max * 1.25)::numeric),
    watr_tprt_crit_min = COALESCE(watr_tprt_crit_min, watr_tprt_min - 5),
    watr_tprt_crit_max = COALESCE(watr_tprt_crit_max, watr_tprt_max + 5),
    bud_tprt_min       = COALESCE(bud_tprt_min,       29::double precision),
    bud_tprt_max       = COALESCE(bud_tprt_max,       33::double precision);

-- 검증 — 결과 확인용 (실행 후 사용자가 직접 SELECT 로 확인 가능)
COMMENT ON COLUMN SENSOR_M_SETTING.tprt_crit_min      IS '온도 비상 최저 (저온비상 임계)';
COMMENT ON COLUMN SENSOR_M_SETTING.tprt_crit_max      IS '온도 비상 최고 (고온비상 임계)';
COMMENT ON COLUMN SENSOR_M_SETTING.hmdt_crit_min      IS '습도 비상 최저';
COMMENT ON COLUMN SENSOR_M_SETTING.hmdt_crit_max      IS '습도 비상 최고';
COMMENT ON COLUMN SENSOR_M_SETTING.co2_crit_max       IS 'CO2 비상 최고';
COMMENT ON COLUMN SENSOR_M_SETTING.watr_tprt_crit_min IS '수온 비상 최저';
COMMENT ON COLUMN SENSOR_M_SETTING.watr_tprt_crit_max IS '수온 비상 최고';
COMMENT ON COLUMN SENSOR_M_SETTING.bud_tprt_min       IS '발이기 적정 최저 (생육단계=발이기 시 사용)';
COMMENT ON COLUMN SENSOR_M_SETTING.bud_tprt_max       IS '발이기 적정 최고';
