-- ═════════════════════════════════════════════════════════════════════════
-- Migration 001 — SCHEDULE_M_SETTING (통합 스케줄 관리 테이블)
--
-- 목적: 모든 백그라운드 작업(cron / interval) 시간표를 단일 테이블에서 관리.
--       web UI 변경 즉시 반영(updt_dttm 비교) — 코드 상수·환경변수 의존 제거.
-- 적용 대상: jayeondeule (postgres)
-- 적용 명령:
--   PGPASSWORD='Wkdusemfdp1@' psql -h 127.0.0.1 -U postgres -d jayeondeule \
--     -f /workspace/jayeondeule/db/migrations/001_schedule_m_setting.sql
-- 롤백:
--   DROP TABLE IF EXISTS schedule_m_setting CASCADE;
--   DROP FUNCTION IF EXISTS schedule_m_setting_touch_updt();
-- ═════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS schedule_m_setting (
    task_name        varchar(100) PRIMARY KEY,
    enabled          boolean      NOT NULL DEFAULT TRUE,
    schedule_type    varchar(20)  NOT NULL CHECK (schedule_type IN ('interval','cron')),
    interval_seconds integer      CHECK (interval_seconds IS NULL OR interval_seconds > 0),
    cron_expr        varchar(100),
    target_farm_id   bigint,
    target_house_id  bigint,
    params_json      jsonb,
    description      text,
    updt_dttm        timestamp    NOT NULL DEFAULT NOW(),
    created_dttm     timestamp    NOT NULL DEFAULT NOW(),
    -- schedule_type 별 필수 필드 강제
    CONSTRAINT schedule_m_setting_type_consistency CHECK (
        (schedule_type = 'interval' AND interval_seconds IS NOT NULL AND cron_expr IS NULL)
        OR
        (schedule_type = 'cron'     AND cron_expr        IS NOT NULL AND interval_seconds IS NULL)
    )
);

COMMENT ON TABLE  schedule_m_setting IS '통합 스케줄 관리 테이블 — task_scheduler 가 polling 으로 읽어 동적 적용';
COMMENT ON COLUMN schedule_m_setting.task_name        IS '작업 식별자 (job_id) — APScheduler 등록 키';
COMMENT ON COLUMN schedule_m_setting.enabled          IS 'true=활성, false=비활성(작업 등록 해제)';
COMMENT ON COLUMN schedule_m_setting.schedule_type    IS 'interval | cron';
COMMENT ON COLUMN schedule_m_setting.interval_seconds IS 'interval 타입의 주기(초)';
COMMENT ON COLUMN schedule_m_setting.cron_expr        IS 'cron 5필드 표현식 "분 시 일 월 요일" (예: 0 4 * * *)';
COMMENT ON COLUMN schedule_m_setting.target_farm_id   IS 'NULL=전체. 특정 농장 한정 시 지정';
COMMENT ON COLUMN schedule_m_setting.target_house_id  IS 'NULL=전체. 특정 호기 한정 시 지정';
COMMENT ON COLUMN schedule_m_setting.params_json      IS '작업별 추가 인자 (jsonb)';
COMMENT ON COLUMN schedule_m_setting.updt_dttm        IS 'row 변경 시각 — task_scheduler polling 이 변경 감지에 사용';

-- ────────────────────────────────────────────────────────────────────
-- updt_dttm 자동 갱신 트리거 — UPDATE 시 NOW() 로 갱신
-- ────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION schedule_m_setting_touch_updt()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updt_dttm := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_schedule_m_setting_updt ON schedule_m_setting;
CREATE TRIGGER trg_schedule_m_setting_updt
    BEFORE UPDATE ON schedule_m_setting
    FOR EACH ROW EXECUTE FUNCTION schedule_m_setting_touch_updt();

-- ────────────────────────────────────────────────────────────────────
-- seed: 현재 task_scheduler.py 의 모든 cron/interval 정의를 그대로 이관.
-- 기존 동작과 100% 동등 — Phase 2 가 이 row 들을 읽어 동작.
-- ────────────────────────────────────────────────────────────────────
INSERT INTO schedule_m_setting
    (task_name, schedule_type, interval_seconds, cron_expr, description)
VALUES
    ('learning_job',            'cron',     NULL, '0 4 * * *',  '매일 04:00 학습 작업'),
    ('stats_job',               'interval', 600,  NULL,         '10분 주기 통계 처리 (STATS_INTERVAL_MINUTES=10)'),
    ('relay_control_job',       'interval', 5,    NULL,         '5초 주기 수동/알고리즘 환경제어 + AI 비상모니터'),
    ('ai_control_loop',         'interval', 60,   NULL,         'AI 순환 루프 재배사 간 대기(초). 별도 스레드 운영'),
    ('growth_rag_job_noon',     'cron',     NULL, '0 12 * * *', '매일 12:00 생육 RAG 수집'),
    ('growth_rag_job_midnight', 'cron',     NULL, '5 0 * * *',  '매일 00:05 생육 RAG 수집 (자정 직후)'),
    ('daily_log_cleanup',       'cron',     NULL, '0 0 * * *',  '매일 00:00 로그 파일 정리'),
    ('pg_pool_heartbeat',       'interval', 300,  NULL,         '5분 주기 PG 커넥션 풀 상태 모니터'),
    ('chunk_cleanup_job',       'cron',     NULL, '0 3 * * *',  '매일 03:00 RAG 청크 180일 초과 정리'),
    ('opinet_daily_job',        'cron',     NULL, '0 10 * * *', '매일 10:00 Opinet 유가 정보 수집'),
    ('camera_archive_hourly',   'cron',     NULL, '0 * * * *',  '매시간 정각 재배사 카메라 아카이브 + Vision LLM'),
    ('camera_archive_cleanup',  'cron',     NULL, '0 4 * * *',  '매일 04:00 카메라 이미지 보존정리'),
    ('lotto_weekly_job',        'cron',     NULL, '0 22 * * 6', '매주 토요일 22:00 로또 당첨번호 수집/분석')
ON CONFLICT (task_name) DO NOTHING;

COMMIT;

-- ────────────────────────────────────────────────────────────────────
-- 확인 쿼리 (참고용)
-- ────────────────────────────────────────────────────────────────────
-- SELECT task_name, enabled, schedule_type,
--        COALESCE(interval_seconds::text, cron_expr) AS schedule, description
--   FROM schedule_m_setting ORDER BY task_name;
