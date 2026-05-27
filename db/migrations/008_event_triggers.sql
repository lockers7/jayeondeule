-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 008 — Phase 5 이벤트 트리거 (센서 임계 근접 / LLM keep 연속)
--
-- 목적:
--   폴링 30분을 기다리지 않고, 이벤트 발생 즉시 agent_subscriptions 를
--   next_run_at = NOW() 로 갱신 → agent_scheduler 의 다음 polling(60초 내)
--   에서 run_agent 실행.
--
-- 트리거 1 — sensor_l_recording INSERT (매 초 발화)
--   · 삽입된 센서값 vs sensor_m_setting 임계값 비교
--   · 온도(indr_tprt_valu) 가 tprt_min/tprt_max 의 ±10% 이내 진입
--     또는 수온(watr_tprt_valu) 이 watr_tprt_min/watr_tprt_max 의 ±10% 이내
--   · sensor_l_recording INSERT 가 5분(300초) 없으면 "데이터 단절" 경고 NOTIFY
--     (단, 이 체크는 Python 측 hearbeat_watcher 에서 담당 — SQL 트리거는 INSERT 시점만)
--
-- 트리거 2 — ai_decision_log INSERT
--   · 동일 farm_id/house_id 에서 가장 최근 5건이 모두 action='keep'
--   · 조건 만족 시 채널 'agent_event' 로 NOTIFY
--
-- 채널: agent_event
-- payload (JSON):
--   {"event": "sensor_threshold", "farm_id": N, "house_id": N,
--    "sensor": "tprt|watr_tprt", "value": V, "threshold": V, "direction": "high|low"}
--   {"event": "llm_keep_streak", "farm_id": N, "house_id": N, "streak": 5}
--
-- Python listener (agent_event_listener.py) 가 NOTIFY 수신 →
--   agent_subscriptions.next_run_at = NOW() 업데이트.
--
-- 멱등 — 재실행 안전 (CREATE OR REPLACE, DROP TRIGGER IF EXISTS).
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 1) 센서 임계 근접 체크 함수
--    sensor_m_setting 에서 최신 임계값을 조회해 ±10% 버퍼 진입 여부 확인.
--    조건 성립 시 채널 'agent_event' 에 JSON payload NOTIFY.
-- ─────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_sensor_threshold_event()
RETURNS TRIGGER AS $$
DECLARE
    v_setting   RECORD;
    v_tprt      NUMERIC;
    v_watr_tprt NUMERIC;
    v_tprt_min  NUMERIC;
    v_tprt_max  NUMERIC;
    v_watr_min  NUMERIC;
    v_watr_max  NUMERIC;
    v_buf_tprt_lo  NUMERIC;
    v_buf_tprt_hi  NUMERIC;
    v_buf_watr_lo  NUMERIC;
    v_buf_watr_hi  NUMERIC;
    v_payload   TEXT;
BEGIN
    -- 최신 임계값 조회 (최신 setn_dttm 기준 1건)
    SELECT tprt_min, tprt_max, watr_tprt_min, watr_tprt_max
      INTO v_setting
      FROM sensor_m_setting
     WHERE farm_id = NEW.farm_id
       AND hous_id = NEW.hous_id
     ORDER BY setn_dttm DESC
     LIMIT 1;

    -- 임계값 없으면 (설정 미입력) 스킵
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    v_tprt      := NEW.indr_tprt_valu;
    v_watr_tprt := NEW.watr_tprt_valu;
    v_tprt_min  := v_setting.tprt_min;
    v_tprt_max  := v_setting.tprt_max;
    v_watr_min  := v_setting.watr_tprt_min;
    v_watr_max  := v_setting.watr_tprt_max;

    -- ── 온도 임계 ±10% 버퍼 ──────────────────────────────────────────
    IF v_tprt IS NOT NULL AND v_tprt_min IS NOT NULL AND v_tprt_max IS NOT NULL THEN
        -- 범위폭의 10% 를 버퍼로 사용 (범위 기준 — 절대값 기준보다 현장 적합)
        -- 예: 15~30℃ → 폭 15 × 0.1 = 1.5℃ 버퍼
        v_buf_tprt_lo := v_tprt_min + (v_tprt_max - v_tprt_min) * 0.1;
        v_buf_tprt_hi := v_tprt_max - (v_tprt_max - v_tprt_min) * 0.1;

        -- 하한 버퍼 진입 (tprt_min ≤ 온도 < tprt_min+10%)
        IF v_tprt < v_buf_tprt_lo AND v_tprt >= v_tprt_min THEN
            v_payload := json_build_object(
                'event',     'sensor_threshold',
                'farm_id',   NEW.farm_id,
                'house_id',  NEW.hous_id,
                'sensor',    'tprt',
                'value',     v_tprt,
                'threshold', v_tprt_min,
                'direction', 'low',
                'ts',        extract(epoch from NOW())
            )::text;
            PERFORM pg_notify('agent_event', v_payload);

        -- 상한 버퍼 진입 (tprt_max-10% < 온도 ≤ tprt_max)
        ELSIF v_tprt > v_buf_tprt_hi AND v_tprt <= v_tprt_max THEN
            v_payload := json_build_object(
                'event',     'sensor_threshold',
                'farm_id',   NEW.farm_id,
                'house_id',  NEW.hous_id,
                'sensor',    'tprt',
                'value',     v_tprt,
                'threshold', v_tprt_max,
                'direction', 'high',
                'ts',        extract(epoch from NOW())
            )::text;
            PERFORM pg_notify('agent_event', v_payload);
        END IF;
    END IF;

    -- ── 수온 임계 ±10% 버퍼 ──────────────────────────────────────────
    IF v_watr_tprt IS NOT NULL AND v_watr_min IS NOT NULL AND v_watr_max IS NOT NULL THEN
        v_buf_watr_lo := v_watr_min + (v_watr_max - v_watr_min) * 0.1;
        v_buf_watr_hi := v_watr_max - (v_watr_max - v_watr_min) * 0.1;

        IF v_watr_tprt < v_buf_watr_lo AND v_watr_tprt >= v_watr_min THEN
            v_payload := json_build_object(
                'event',     'sensor_threshold',
                'farm_id',   NEW.farm_id,
                'house_id',  NEW.hous_id,
                'sensor',    'watr_tprt',
                'value',     v_watr_tprt,
                'threshold', v_watr_min,
                'direction', 'low',
                'ts',        extract(epoch from NOW())
            )::text;
            PERFORM pg_notify('agent_event', v_payload);

        ELSIF v_watr_tprt > v_buf_watr_hi AND v_watr_tprt <= v_watr_max THEN
            v_payload := json_build_object(
                'event',     'sensor_threshold',
                'farm_id',   NEW.farm_id,
                'house_id',  NEW.hous_id,
                'sensor',    'watr_tprt',
                'value',     v_watr_tprt,
                'threshold', v_watr_max,
                'direction', 'high',
                'ts',        extract(epoch from NOW())
            )::text;
            PERFORM pg_notify('agent_event', v_payload);
        END IF;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


-- ─────────────────────────────────────────────────────────────────────────
-- 2) ai_decision_log INSERT → LLM keep 5회 연속 체크 함수
--    동일 farm_id/house_id 최근 5건이 전부 action='keep' 이면 NOTIFY.
-- ─────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_llm_keep_streak_event()
RETURNS TRIGGER AS $$
DECLARE
    v_streak_count INT;
    v_payload      TEXT;
BEGIN
    -- 현재 삽입된 row 포함 최근 5건의 action 조회
    SELECT COUNT(*)
      INTO v_streak_count
      FROM (
          SELECT action
            FROM ai_decision_log
           WHERE farm_id  = NEW.farm_id
             AND house_id = NEW.house_id
           ORDER BY decided_at DESC
           LIMIT 5
      ) sub
     WHERE sub.action = 'keep';

    -- 5건 모두 'keep' 이면 이벤트 발화
    IF v_streak_count = 5 THEN
        v_payload := json_build_object(
            'event',    'llm_keep_streak',
            'farm_id',  NEW.farm_id,
            'house_id', NEW.house_id,
            'streak',   5,
            'ts',       extract(epoch from NOW())
        )::text;
        PERFORM pg_notify('agent_event', v_payload);
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


-- ─────────────────────────────────────────────────────────────────────────
-- 3) 트리거 부착 (DROP IF EXISTS → CREATE 멱등 패턴)
-- ─────────────────────────────────────────────────────────────────────────

-- sensor_l_recording — AFTER INSERT, ROW 레벨 (각 행 삽입 시 체크)
DROP TRIGGER IF EXISTS trg_sensor_threshold_event ON sensor_l_recording;
CREATE TRIGGER trg_sensor_threshold_event
    AFTER INSERT ON sensor_l_recording
    FOR EACH ROW EXECUTE FUNCTION fn_sensor_threshold_event();

-- ai_decision_log — AFTER INSERT, ROW 레벨
DROP TRIGGER IF EXISTS trg_llm_keep_streak_event ON ai_decision_log;
CREATE TRIGGER trg_llm_keep_streak_event
    AFTER INSERT ON ai_decision_log
    FOR EACH ROW EXECUTE FUNCTION fn_llm_keep_streak_event();


COMMIT;

-- 확인:
-- SELECT trigger_name, event_object_table, action_timing, action_orientation
--   FROM information_schema.triggers
--  WHERE trigger_name IN (
--        'trg_sensor_threshold_event',
--        'trg_llm_keep_streak_event')
--  ORDER BY event_object_table;
