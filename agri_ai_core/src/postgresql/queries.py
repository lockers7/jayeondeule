# ════════════════════════════════════════════════════════════════════
# PostgreSQL SQL 쿼리 상수 모음 — 함수 없이 SQL 문자열만 정의.
# 호출처: postgresql/connection.py 의 fetch_*/execute_query 헬퍼.
# 섹션 구분 주석으로 농장/센서/릴레이/AI 학습/생육 RAG/AI 결정/M7~M17 등 분류.
# ════════════════════════════════════════════════════════════════════
# farm_id=0(시스템/가상 농장)을 제외한 실제 운영 농장을 기본값으로 사용
GET_ONE_FARM = "SELECT farm_id, farm_name FROM FARM_M_INFO WHERE farm_id != 0 ORDER BY farm_id LIMIT 1"
GET_ONE_HOUSE = "SELECT hous_id, hous_name FROM FARMHOUSE_M_INFO WHERE farm_id = %s AND hous_id != 0 ORDER BY hous_id LIMIT 1"
GET_ALL_HOUSES = "SELECT hous_id FROM FARMHOUSE_M_INFO WHERE farm_id = %s AND hous_id != 0 ORDER BY hous_id"
GET_LIST_FARM = "SELECT farm_id, farm_name FROM FARM_M_INFO"

# ═════════════════════
# 농장/재배사 정보 조회
# ═════════════════════
GET_FARM_NAME = """SELECT DISTINCT farm_id, farm_name
                   FROM FARM_M_INFO
                   WHERE farm_id != 0 AND (farm_id = %s OR %s IS NULL)
                   ORDER BY farm_name ASC;"""

GET_HOUSE_NAME = """SELECT DISTINCT farm_id, hous_id, hous_name, mnul_ctrl_flag, ctrl_type, crop_lvel, dlte_yn
                    FROM FARMHOUSE_M_INFO
                    WHERE (farm_id = %s OR %s IS NULL)
                      AND (hous_id = %s OR %s IS NULL)
                    ORDER BY hous_name ASC;"""

GET_HOUSE_ID = """SELECT DISTINCT farm_id, hous_id
                  FROM FARMHOUSE_M_INFO
                  WHERE (farm_id = %d OR %s IS NULL) AND hous_name LIKE %s;"""

GET_FARM_HOUSE_INFO = """SELECT DISTINCT FMI.farm_name, HMI.hous_name, HMI.mnul_ctrl_flag, HMI.ctrl_type, HMI.crop_lvel
                         FROM FARM_M_INFO FMI
                         JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
                         WHERE FMI.farm_id != 0 AND FMI.farm_id = %s AND HMI.hous_id = %s;"""

GET_FARM_HOUSE_LIST = """SELECT DISTINCT FMI.farm_id, FMI.farm_name, HMI.hous_id, HMI.hous_name, HMI.mnul_ctrl_flag, HMI.ctrl_type, HMI.crop_lvel
                         FROM FARM_M_INFO FMI
                         JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
                         WHERE 1 = 1 AND FMI.farm_id != 0 AND HMI.hous_id != 99
                         ORDER BY 1, 3;"""

# ═══════════════════
# 현재 센서 정보 조회
# ═══════════════════
GET_NOW_UNIT_INFO = """SELECT TO_CHAR(recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS record_datetime
                            , indr_tprt_valu AS indoor_temperature
                            , indr_hmdt_valu AS indoor_humidity
                            , oudr_tprt_valu AS outdoor_temperature
                            , oudr_hmdt_valu AS outdoor_humidity
                            , co2_valu       AS co2
                            , watr_tprt_valu AS water_temperature
                            , ligt_lvel_valu AS light_level
                            , watr_lvel_valu AS water_level
                         FROM SENSOR_L_RECORDING
                        WHERE farm_id = %s
                          AND hous_id = %s
                        ORDER BY recd_dttm DESC
                        LIMIT 1"""

# ══════════════════
# 센서 히스토리 조회
# ══════════════════
GET_SENSOR_HISTORY = """SELECT recd_dttm       AS record_datetime
                             , indr_tprt_valu  AS indoor_temperature
                             , watr_tprt_valu  AS water_temperature
                             , indr_hmdt_valu  AS indoor_humidity
                             , co2_valu        AS co2
                          FROM SENSOR_L_RECORDING
                         WHERE farm_id = %s
                           AND hous_id = %s
                           AND recd_dttm >= (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                         ORDER BY recd_dttm ASC
                         LIMIT %s"""

# ══════════════════
# 릴레이 정보 조회
# ══════════════════
GET_LATEST_RELAY_INFO = """SELECT relay_1st_flag,  relay_2st_flag,  relay_3st_flag,  relay_4st_flag
                                , relay_5st_flag,  relay_6st_flag,  relay_7st_flag,  relay_8st_flag
                                , relay_9st_flag,  relay_10st_flag, relay_11st_flag, relay_12st_flag
                                , relay_13st_flag, relay_14st_flag, relay_15st_flag, relay_16st_flag
                             FROM RELAY_L_RECORDING
                            WHERE farm_id = %s
                              AND hous_id = %s
                            ORDER BY recd_dttm DESC
                            LIMIT 1"""

# ═══════════════════
# 농장 상세 정보 조회
# ═══════════════════
GET_FARM_INFO_LIST = """SELECT FMI.farm_id                         AS 농장코드
                             , FMI.farm_name                       AS 농장명
                             , farm_domi                           AS 도메인
                             , open_date                           AS 영업시작일
                             , close_date                          AS 영업종료일
                             , tel_no                              AS 농장전화번호
                             , FMI.hp_no                           AS 비상연락번호
                             , fax_no                              AS 팩스번호
                             , mail                                AS 메일주소
                             , CM1.code_name                       AS 지역명
                             , addr                                AS 농장주소
                             , main_prdt                           AS 주요재배작물
                             , FMI.rmks                            AS 농장기타정보
                             , user_name                           AS 농장주명
                             , UMI.hp_no                           AS 농장주전화번호
                             , sum(tprt_min) / count(*)            AS 온도최저
                             , sum(tprt_max) / count(*)            AS 온도최고
                             , sum(hmdt_min) / count(*)            AS 습도최저
                             , sum(hmdt_max) / count(*)            AS 습도최고
                             , sum(co2_min) / count(*)             AS co2최저
                             , sum(co2_max) / count(*)             AS co2최고
                             , sum(watr_tprt_min) / count(*)       AS 수온최저
                             , sum(watr_tprt_max) / count(*)       AS 수온최고
                             , sum(heat_tprt_min) / count(*)       AS 히터최저
                             , sum(heat_tprt_max) / count(*)       AS 히터최고
                          FROM FARM_M_INFO      FMI
                          JOIN USER_M_INFO      UMI ON UMI.farm_id = FMI.farm_id AND user_id = 'admin'
                          JOIN CODE_M_INFO      CM1 ON code_id = 'regn' AND code_item = FMI.regn
                          JOIN SENSOR_M_SETTING SMS ON SMS.farm_id = FMI.farm_id
                         WHERE SMS.setn_dttm = (SELECT MAX(setn_dttm)
                                                  FROM SENSOR_M_SETTING
                                                 WHERE farm_id = SMS.farm_id
                                                   AND hous_id = SMS.hous_id)
                         GROUP BY FMI.farm_id, FMI.farm_name, farm_domi, open_date, close_date,
                                  tel_no, FMI.hp_no, fax_no, mail, CM1.code_name, addr,
                                  main_prdt, FMI.rmks, user_name, UMI.hp_no;"""

# ══════════════════
# Units 데이터 조회
# ══════════════════
GET_UNITS_VALUE = """SELECT FMI.farm_id                       AS 농장코드
                          , FMI.farm_name                     AS 농장명
                          , HMI.hous_id                       AS 재배사코드
                          , HMI.hous_name                     AS 재배사명
                          , 'units'                           AS 장치데이터
                          , TO_CHAR(SLR.recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS 기록일시
                          , HMI.mnul_ctrl_flag                AS 동작모드
                          , indr_tprt_valu                    AS 내부온도
                          , indr_hmdt_valu                    AS 내부습도
                          , oudr_tprt_valu                    AS 외부온도
                          , oudr_hmdt_valu                    AS 외부습도
                          , co2_valu                          AS co2
                          , watr_tprt_valu                    AS 수온
                          , ligt_lvel_valu                    AS 광량
                          , watr_lvel_valu                    AS 수위
                          , relay_1st_flag                    AS 수온히터
                          , relay_2st_flag                    AS 포그생성
                          , relay_3st_flag                    AS 배수밸브
                          , relay_5st_flag                    AS 흡입팬
                          , relay_6st_flag                    AS 배출팬
                          , relay_7st_flag                    AS 조명
                          , relay_8st_flag                    AS 관수
                          , relay_9st_flag                    AS 실내히터
                          , relay_10st_flag                   AS 순환밸브
                          , relay_11st_flag                   AS 배출밸브
                          , relay_14st_flag                   AS 흡입밸브
                          , relay_15st_flag                   AS 히터밸브
                       FROM FARM_M_INFO         FMI
                       JOIN FARMHOUSE_M_INFO    HMI ON HMI.farm_id = FMI.farm_id
                       JOIN SENSOR_L_RECORDING  SLR ON SLR.farm_id = HMI.farm_id AND SLR.hous_id = HMI.hous_id
                       JOIN RELAY_L_RECORDING   RLR ON RLR.farm_id = SLR.farm_id AND RLR.hous_id = SLR.hous_id
                                                   AND RLR.recd_dttm = SLR.recd_dttm
                      WHERE FMI.farm_id = %s
                        AND HMI.hous_id = %s
                        AND SLR.recd_dttm >= HMI.last_get_dttm
                      ORDER BY FMI.farm_id ASC, HMI.hous_id ASC, SLR.recd_dttm ASC;"""

# ══════════════════
# Crops 데이터 조회
# ══════════════════
GET_CROPS_VALUE = """SELECT FMI.farm_id                      AS 농장코드
                          , FMI.farm_name                     AS 농장명
                          , HMI.hous_id                       AS 재배사코드
                          , HMI.hous_name                     AS 재배사명
                          , 'crops'                           AS 작물데이터
                          , TO_CHAR(recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS 기록일시
                          , HMI.mnul_ctrl_flag                AS 동작모드
                          , crop_strt_date                    AS 재배시작일
                          , crop_end_date                     AS 재배종료일
                          , code_name                         AS 생육상태
                          , HLC.crop_kind                     AS 작물종류
                          , HLC.ctrl_type                     AS 제어모드
                          , HLC.crop_lvel                     AS 생육단계
                          , crop_qtty                         AS 총수확량
                          , crop_grde_qtty_1                  AS 등급1
                          , crop_grde_qtty_2                  AS 등급2
                          , crop_grde_qtty_3                  AS 등급3
                          , crop_grde_qtty_4                  AS 등급4
                          , crop_grde_qtty_5                  AS 등급5
                          , crop_grde_amut_1                  AS 등급1판매가격
                          , crop_grde_amut_2                  AS 등급2판매가격
                          , crop_grde_amut_3                  AS 등급3판매가격
                          , crop_grde_amut_4                  AS 등급4판매가격
                          , crop_grde_amut_5                  AS 등급5판매가격
                          , HLC.rmks                          AS 생육시기타사항
                       FROM FARM_M_INFO       FMI
                       JOIN FARMHOUSE_M_INFO  HMI ON HMI.farm_id = FMI.farm_id
                       JOIN FARMHOUSE_L_CROPS HLC ON HLC.farm_id = HMI.farm_id AND HLC.hous_id = HMI.hous_id
                       JOIN CODE_M_INFO       CMI ON CMI.code_id = 'crop_stat' AND CMI.code_item = HLC.crop_stat
                      WHERE FMI.farm_id = %s
                        AND HMI.hous_id = %s
                        AND HLC.recd_dttm >= HMI.last_get_dttm
                      ORDER BY FMI.farm_id ASC, HMI.hous_id ASC, HLC.recd_dttm ASC;"""

# ════════════════════════════════════════════════════
# 최신 생육단계 조회 (FARMHOUSE_M_INFO.crop_lvel 기반)
# ════════════════════════════════════════════════════
GET_CURRENT_CROP_LVEL = """SELECT HMI.crop_lvel   AS crop_lvel
                                , CMI.code_name    AS 생육단계
                             FROM FARMHOUSE_M_INFO HMI
                             JOIN CODE_M_INFO      CMI ON CMI.code_id = 'crop_lvel' AND CMI.code_item = HMI.crop_lvel
                            WHERE HMI.farm_id = %s
                              AND HMI.hous_id = %s;"""

# ══════════════════
# 최적 조건 조회
# ══════════════════
GET_OPTIMAL_CONDITION = """SELECT setn_dttm           AS 저장일자
                                , tprt_min            AS 온도최저
                                , tprt_otml           AS 온도적정
                                , tprt_max            AS 온도최고
                                , tprt_crit_min       AS 온도비상최저
                                , tprt_crit_max       AS 온도비상최고
                                , hmdt_min            AS 습도최저
                                , hmdt_otml           AS 습도적정
                                , hmdt_max            AS 습도최고
                                , hmdt_crit_min       AS 습도비상최저
                                , hmdt_crit_max       AS 습도비상최고
                                , co2_min             AS co2최저
                                , co2_otml            AS co2적정
                                , co2_max             AS co2최고
                                , co2_crit_max        AS co2비상최고
                                , watr_tprt_min       AS 수온최저
                                , watr_tprt_otml      AS 수온적정
                                , watr_tprt_max       AS 수온최고
                                , watr_tprt_crit_min  AS 수온비상최저
                                , watr_tprt_crit_max  AS 수온비상최고
                                , bud_tprt_min        AS 발이기최저
                                , bud_tprt_max        AS 발이기최고
                              FROM SENSOR_M_SETTING O
                             WHERE farm_id = %s
                               AND hous_id = %s
                               AND setn_dttm = (SELECT MAX(setn_dttm)
                                                  FROM SENSOR_M_SETTING
                                                 WHERE farm_id = O.farm_id
                                                   AND hous_id = O.hous_id)
                             ORDER BY setn_dttm DESC
                             LIMIT 1"""

# ═══════════════════════
# 조명/관수 설정 조회
# ═══════════════════════
GET_LIGHT_IRRIGATION = """SELECT strt_time
                               , fnsh_time
                               , excs_type
                               , excs_itvl
                               , excs_strt_date
                               , excs_wkdy
                            FROM LIGHT_IRRIGATION_S_SETTING
                           WHERE farm_id          = %s
                             AND hous_id          = %s
                             AND LOWER(unit_type) = %s
                             AND dlte_yn          = FALSE
                           ORDER BY strt_time"""

# ═══════════════════════════════════════════════
# 통합 스케줄 설정 (SCHEDULE_M_SETTING)
# ═══════════════════════════════════════════════
GET_ALL_SCHEDULE_SETTINGS = """SELECT task_name
                                    , enabled
                                    , schedule_type
                                    , interval_seconds
                                    , cron_expr
                                    , target_farm_id
                                    , target_house_id
                                    , params_json
                                    , description
                                    , updt_dttm
                                 FROM SCHEDULE_M_SETTING
                                ORDER BY task_name"""

GET_SCHEDULE_MAX_UPDT = """SELECT MAX(updt_dttm) AS max_updt
                             FROM SCHEDULE_M_SETTING"""

# ═══════════════════════════════════════════════════════════
# 센서 임계값 변경 감지용 — SENSOR_M_SETTING
# ═══════════════════════════════════════════════════════════
GET_SENSOR_SETTING_MAX_UPDT = """SELECT MAX(updt_dttm) AS max_updt
                                   FROM SENSOR_M_SETTING
                                  WHERE farm_id = %s
                                    AND hous_id = %s"""

# ═══════════════════════════════════════════════════════
# 프롬프트/도구 변경 감지
# ═══════════════════════════════════════════════════════
GET_PROMPT_BLOCK_UPDT = """SELECT updt_dttm
                             FROM prompt_block_m
                            WHERE block_id = %s"""

GET_TOOL_DEFINITION_MAX_UPDT = """SELECT MAX(updt_dttm) AS max_updt
                                    FROM tool_definition_m
                                   WHERE active_yn = 'Y'"""

# ══════════════════
# 릴레이 설정 저장
# ══════════════════
SET_RELAY_VALUE = """INSERT INTO RELAY_L_RECORDING (farm_id,          hous_id,         recd_dttm
                                                  , relay_1st_flag,   relay_2st_flag,  relay_3st_flag,  relay_4st_flag
                                                  , relay_5st_flag,   relay_6st_flag,  relay_7st_flag,  relay_8st_flag
                                                  , relay_9st_flag,   relay_10st_flag, relay_11st_flag, relay_12st_flag
                                                  , relay_13st_flag,  relay_14st_flag, relay_15st_flag, relay_16st_flag)
                                             VALUES (%s, %s, %s
                                                  , %s, %s, %s, %s
                                                  , %s, %s, %s, %s
                                                  , %s, %s, %s, %s
                                                  , %s, %s, %s, %s)
                                          ON CONFLICT (farm_id, hous_id, recd_dttm)
                                          DO UPDATE SET
                                                relay_1st_flag  = EXCLUDED.relay_1st_flag,
                                                relay_2st_flag  = EXCLUDED.relay_2st_flag,
                                                relay_3st_flag  = EXCLUDED.relay_3st_flag,
                                                relay_4st_flag  = EXCLUDED.relay_4st_flag,
                                                relay_5st_flag  = EXCLUDED.relay_5st_flag,
                                                relay_6st_flag  = EXCLUDED.relay_6st_flag,
                                                relay_7st_flag  = EXCLUDED.relay_7st_flag,
                                                relay_8st_flag  = EXCLUDED.relay_8st_flag,
                                                relay_9st_flag  = EXCLUDED.relay_9st_flag,
                                                relay_10st_flag = EXCLUDED.relay_10st_flag,
                                                relay_11st_flag = EXCLUDED.relay_11st_flag,
                                                relay_12st_flag = EXCLUDED.relay_12st_flag,
                                                relay_13st_flag = EXCLUDED.relay_13st_flag,
                                                relay_14st_flag = EXCLUDED.relay_14st_flag,
                                                relay_15st_flag = EXCLUDED.relay_15st_flag,
                                                relay_16st_flag = EXCLUDED.relay_16st_flag;"""

# ════════════════════
# 재배사 정보 업데이트
# ════════════════════
SET_FARMHOUSE_INFO = "UPDATE FARMHOUSE_M_INFO SET last_get_dttm=%s WHERE farm_id=%s AND hous_id=%s;"

SET_MANAGE_METHOD = "UPDATE FARMHOUSE_M_INFO SET mnul_ctrl_flag=%s, ctrl_type=%s WHERE farm_id=%s AND hous_id=%s;"

# ══════════════════
# AI 대화 히스토리
# ══════════════════
CREATE_AI_CONVERSATION_TABLE = """
CREATE TABLE IF NOT EXISTS ai_conversation (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(64) NOT NULL,
    role        VARCHAR(16) NOT NULL,
    content     TEXT NOT NULL,
    farm_id     VARCHAR(32),
    created_at  TIMESTAMP DEFAULT NOW()
);
"""

CREATE_AI_CONVERSATION_INDEX_SESSION = "CREATE INDEX IF NOT EXISTS idx_ai_conv_session ON ai_conversation(session_id);"
CREATE_AI_CONVERSATION_INDEX_CREATED = "CREATE INDEX IF NOT EXISTS idx_ai_conv_created ON ai_conversation(created_at);"

INSERT_AI_CONVERSATION_TURN = "INSERT INTO ai_conversation (session_id, role, content, farm_id) VALUES (%s, %s, %s, %s)"

GET_AI_CONVERSATION_HISTORY = """
SELECT role, content FROM ai_conversation
WHERE session_id = %s
ORDER BY created_at ASC
"""

DELETE_AI_CONVERSATION_SESSION = "DELETE FROM ai_conversation WHERE session_id = %s"

DELETE_AI_CONVERSATION_EXPIRED = "DELETE FROM ai_conversation WHERE created_at < NOW() - (%s || ' days')::INTERVAL"

# 오래된 턴 삭제: MAX_TURNS 초과 시 가장 오래된 N개 턴 삭제 (요약 실패 시에도 무한 누적 방지)
DELETE_AI_CONVERSATION_OLD_TURNS = """
DELETE FROM ai_conversation WHERE id IN (
    SELECT id FROM ai_conversation
    WHERE session_id = %s
    ORDER BY created_at ASC
    LIMIT %s
)
"""

COUNT_AI_CONVERSATION_SESSIONS = """
SELECT COUNT(DISTINCT session_id) as cnt FROM ai_conversation
WHERE created_at > NOW() - (%s || ' days')::INTERVAL
"""

# 최근 N개 메시지만 조회 (하이브리드 컨텍스트용)
GET_AI_CONVERSATION_RECENT_TURNS = """
SELECT role, content FROM (
    SELECT role, content, created_at FROM ai_conversation
    WHERE session_id = %s ORDER BY created_at DESC LIMIT %s
) sub ORDER BY created_at ASC
"""

# ══════════════════
# AI 학습 상태 관리
# ══════════════════
CREATE_AI_LEARNING_STATUS_TABLE = """
CREATE TABLE IF NOT EXISTS ai_learning_status (
    id              SERIAL PRIMARY KEY,
    status_key      VARCHAR(64) NOT NULL UNIQUE,
    status_value    TEXT,
    updated_at      TIMESTAMP DEFAULT NOW()
);
"""

UPSERT_AI_LEARNING_STATUS = """
INSERT INTO ai_learning_status (status_key, status_value, updated_at)
VALUES (%s, %s, NOW())
ON CONFLICT (status_key) DO UPDATE SET status_value = EXCLUDED.status_value, updated_at = NOW()
"""

GET_AI_LEARNING_STATUS = """
SELECT status_value, updated_at FROM ai_learning_status WHERE status_key = %s
"""

# ══════════════════
# AI 학습 패턴 관리
# ══════════════════
CREATE_AI_LEARNING_PATTERN_TABLE = """
CREATE TABLE IF NOT EXISTS ai_learning_pattern (
    id              SERIAL PRIMARY KEY,
    pattern_type    VARCHAR(32) NOT NULL,
    farm_id         VARCHAR(32),
    pattern_data    JSONB,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
"""

CREATE_AI_LEARNING_PATTERN_INDEX = "CREATE INDEX IF NOT EXISTS idx_ai_lp_farm ON ai_learning_pattern(farm_id);"

# ═════════════════════════════════════════════════════════════
# 미학습 센서/릴레이 데이터 조회 (학습용)
# 모든 농장-재배사의 센서+릴레이 데이터를 특정 일시 이후로 조회
# 영문 키 반환 (model_trainer 호환)
# ═════════════════════════════════════════════════════════════
GET_UNLEARNED_UNITS_DATA = """SELECT FMI.farm_id                                               AS farm_id
                                  , FMI.farm_name                                              AS farm_name
                                  , HMI.hous_id                                                AS house_id
                                  , HMI.hous_name                                              AS house_name
                                  , 'units'                                                    AS data_kind
                                  , TO_CHAR(SLR.recd_dttm, 'YYYY-MM-DD HH24:MI:SS')           AS record_datetime
                                  , HMI.mnul_ctrl_flag                                         AS is_manual
                                  , indr_tprt_valu                                             AS indoor_temperature_value
                                  , indr_hmdt_valu                                             AS indoor_humidity_value
                                  , oudr_tprt_valu                                             AS outdoor_temperature_value
                                  , oudr_hmdt_valu                                             AS outdoor_humidity_value
                                  , co2_valu                                                   AS co2_concentration_value
                                  , watr_tprt_valu                                             AS water_temperature_value
                                  , ligt_lvel_valu                                             AS light_level_value
                                  , watr_lvel_valu                                             AS water_level_value
                                  , relay_1st_flag
                                  , relay_2st_flag
                                  , relay_3st_flag
                                  , relay_5st_flag
                                  , relay_6st_flag
                                  , relay_7st_flag
                                  , relay_8st_flag
                                  , relay_9st_flag
                                  , relay_10st_flag
                                  , relay_11st_flag
                                  , relay_14st_flag
                                  , relay_15st_flag
                               FROM FARM_M_INFO         FMI
                               JOIN FARMHOUSE_M_INFO    HMI ON HMI.farm_id = FMI.farm_id
                               JOIN SENSOR_L_RECORDING  SLR ON SLR.farm_id = HMI.farm_id AND SLR.hous_id = HMI.hous_id
                               JOIN RELAY_L_RECORDING   RLR ON RLR.farm_id = SLR.farm_id AND RLR.hous_id = SLR.hous_id
                                                           AND RLR.recd_dttm = SLR.recd_dttm
                              WHERE FMI.farm_id != 0
                                AND HMI.hous_id != 99
                                AND SLR.recd_dttm > %s
                              ORDER BY SLR.recd_dttm ASC
                              LIMIT %s;"""

# ══════════════════════════════════════════════════════
# 미학습 작물 데이터 조회 (학습용)
# 모든 농장-재배사의 작물 데이터를 특정 일시 이후로 조회
# 영문 키 반환 (model_trainer 호환)
# ══════════════════════════════════════════════════════
GET_UNLEARNED_CROPS_DATA = """SELECT FMI.farm_id                                               AS farm_id
                                  , FMI.farm_name                                              AS farm_name
                                  , HMI.hous_id                                                AS house_id
                                  , HMI.hous_name                                              AS house_name
                                  , 'crops'                                                    AS data_kind
                                  , TO_CHAR(HLC.recd_dttm, 'YYYY-MM-DD HH24:MI:SS')           AS record_datetime
                                  , HMI.mnul_ctrl_flag                                         AS is_manual
                                  , crop_strt_date
                                  , crop_end_date
                                  , code_name                                                  AS growth_status
                                  , HLC.crop_kind
                                  , HLC.ctrl_type
                                  , HLC.crop_lvel
                                  , crop_qtty                                                  AS total_yield
                                  , crop_grde_qtty_1                                           AS grade_1_yield
                                  , crop_grde_qtty_2                                           AS grade_2_yield
                                  , crop_grde_qtty_3                                           AS grade_3_yield
                                  , crop_grde_qtty_4                                           AS grade_4_yield
                                  , crop_grde_qtty_5                                           AS grade_5_yield
                                  , crop_grde_amut_1                                           AS grade_1_price
                                  , crop_grde_amut_2                                           AS grade_2_price
                                  , crop_grde_amut_3                                           AS grade_3_price
                                  , crop_grde_amut_4                                           AS grade_4_price
                                  , crop_grde_amut_5                                           AS grade_5_price
                                  , HLC.rmks                                                   AS alert
                                  , HLC.obsv_date                                               AS observation_date
                                  , HLC.leaf_count
                                  , HLC.leaf_size
                                  , HLC.leaf_color
                                  , HLC.stem_height
                                  , HLC.stem_diameter
                                  , HLC.pest_type
                                  , HLC.pest_severity
                                  , HLC.fruit_count
                                  , HLC.fruit_size
                                  , HLC.watering_memo
                                  , HLC.growth_memo
                               FROM FARM_M_INFO       FMI
                               JOIN FARMHOUSE_M_INFO  HMI ON HMI.farm_id = FMI.farm_id
                               JOIN FARMHOUSE_L_CROPS HLC ON HLC.farm_id = HMI.farm_id AND HLC.hous_id = HMI.hous_id
                               JOIN CODE_M_INFO       CMI ON CMI.code_id = 'crop_stat' AND CMI.code_item = HLC.crop_stat
                              WHERE FMI.farm_id != 0
                                AND HMI.hous_id != 99
                                AND HLC.recd_dttm > %s
                              ORDER BY HLC.recd_dttm ASC
                              LIMIT %s;"""

# ══════════════════════════════════════════════
# 생육 RAG용 쿼리 — 생육 기반 인과 관계 RAG
# ══════════════════════════════════════════════

# FARMHOUSE_L_CROPS 테이블에 생육 세분화 컬럼 추가 (IF NOT EXISTS이므로 중복 실행 안전)
ALTER_CROPS_ADD_GROWTH_DETAIL_COLUMNS = """
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS obsv_date DATE;
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS leaf_count INTEGER;
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS leaf_size VARCHAR(20);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS leaf_color VARCHAR(20);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS stem_height NUMERIC(6,1);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS stem_diameter NUMERIC(6,1);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS pest_type VARCHAR(50);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS pest_severity VARCHAR(10);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS fruit_count INTEGER;
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS fruit_size VARCHAR(20);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS watering_memo VARCHAR(200);
ALTER TABLE FARMHOUSE_L_CROPS ADD COLUMN IF NOT EXISTS growth_memo VARCHAR(500);
"""

# 마지막 생육 RAG 처리 시점 조회
GET_LAST_GROWTH_RAG_DATETIME = """
SELECT status_value FROM ai_learning_status WHERE status_key = 'last_growth_rag_datetime'
"""

# 특정 시간 구간의 생육 데이터 조회
GET_CROPS_IN_RANGE = """SELECT HLC.farm_id
                             , HMI.hous_id
                             , TO_CHAR(HLC.recd_dttm, 'YYYY-MM-DD HH24:MI:SS')  AS record_datetime
                             , HMI.mnul_ctrl_flag                                AS is_manual
                             , crop_strt_date
                             , crop_end_date
                             , CMI.code_name                                     AS growth_status
                             , HLC.crop_kind
                             , HLC.ctrl_type
                             , HLC.crop_lvel
                             , HLC.crop_stat
                             , crop_qtty                                         AS total_yield
                             , crop_grde_qtty_1                                  AS grade_1_yield
                             , crop_grde_qtty_2                                  AS grade_2_yield
                             , crop_grde_qtty_3                                  AS grade_3_yield
                             , crop_grde_qtty_4                                  AS grade_4_yield
                             , crop_grde_qtty_5                                  AS grade_5_yield
                             , crop_grde_amut_1                                  AS grade_1_price
                             , crop_grde_amut_2                                  AS grade_2_price
                             , crop_grde_amut_3                                  AS grade_3_price
                             , crop_grde_amut_4                                  AS grade_4_price
                             , crop_grde_amut_5                                  AS grade_5_price
                             , HLC.rmks                                          AS alert
                             , HLC.obsv_date                                     AS observation_date
                             , HLC.leaf_count
                             , HLC.leaf_size
                             , HLC.leaf_color
                             , HLC.stem_height
                             , HLC.stem_diameter
                             , HLC.pest_type
                             , HLC.pest_severity
                             , HLC.fruit_count
                             , HLC.fruit_size
                             , HLC.watering_memo
                             , HLC.growth_memo
                          FROM FARMHOUSE_L_CROPS HLC
                          JOIN FARMHOUSE_M_INFO  HMI ON HMI.farm_id = HLC.farm_id AND HMI.hous_id = HLC.hous_id
                          JOIN CODE_M_INFO       CMI ON CMI.code_id = 'crop_stat' AND CMI.code_item = HLC.crop_stat
                         WHERE HLC.farm_id   = %s AND HLC.hous_id    = %s
                           AND HLC.recd_dttm > %s AND HLC.recd_dttm <= %s
                         ORDER BY HLC.recd_dttm ASC;"""

# 특정 시간 구간의 센서 통계 조회 (평균, 표준편차, 최소, 최대)
GET_SENSOR_STATS_IN_RANGE = """SELECT COUNT(*)                                            AS sample_count
                                    , ROUND(AVG(indr_tprt_valu)::numeric, 2)              AS avg_indoor_temp
                                    , ROUND(STDDEV(indr_tprt_valu)::numeric, 2)           AS std_indoor_temp
                                    , ROUND(MIN(indr_tprt_valu)::numeric, 2)              AS min_indoor_temp
                                    , ROUND(MAX(indr_tprt_valu)::numeric, 2)              AS max_indoor_temp
                                    , ROUND(AVG(indr_hmdt_valu)::numeric, 2)              AS avg_indoor_humidity
                                    , ROUND(STDDEV(indr_hmdt_valu)::numeric, 2)           AS std_indoor_humidity
                                    , ROUND(MIN(indr_hmdt_valu)::numeric, 2)              AS min_indoor_humidity
                                    , ROUND(MAX(indr_hmdt_valu)::numeric, 2)              AS max_indoor_humidity
                                    , ROUND(AVG(oudr_tprt_valu)::numeric, 2)              AS avg_outdoor_temp
                                    , ROUND(MIN(oudr_tprt_valu)::numeric, 2)              AS min_outdoor_temp
                                    , ROUND(MAX(oudr_tprt_valu)::numeric, 2)              AS max_outdoor_temp
                                    , ROUND(AVG(oudr_hmdt_valu)::numeric, 2)              AS avg_outdoor_humidity
                                    , ROUND(AVG(co2_valu)::numeric, 2)                    AS avg_co2
                                    , ROUND(STDDEV(co2_valu)::numeric, 2)                 AS std_co2
                                    , ROUND(MIN(co2_valu)::numeric, 2)                    AS min_co2
                                    , ROUND(MAX(co2_valu)::numeric, 2)                    AS max_co2
                                    , ROUND(AVG(watr_tprt_valu)::numeric, 2)              AS avg_water_temp
                                    , ROUND(MIN(watr_tprt_valu)::numeric, 2)              AS min_water_temp
                                    , ROUND(MAX(watr_tprt_valu)::numeric, 2)              AS max_water_temp
                                    , ROUND(AVG(ligt_lvel_valu)::numeric, 2)              AS avg_light_level
                                    , ROUND(MIN(ligt_lvel_valu)::numeric, 2)              AS min_light_level
                                    , ROUND(MAX(ligt_lvel_valu)::numeric, 2)              AS max_light_level
                                    , ROUND(AVG(watr_lvel_valu)::numeric, 2)              AS avg_water_level
                                 FROM SENSOR_L_RECORDING
                                WHERE farm_id   = %s AND hous_id    = %s
                                  AND recd_dttm > %s AND recd_dttm <= %s;"""

# 특정 시간 구간의 릴레이 가동 비율 조회
GET_RELAY_STATS_IN_RANGE = """SELECT COUNT(*)                                                            AS sample_count
                                   , ROUND(AVG(CASE WHEN relay_1st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS heater_ratio
                                   , ROUND(AVG(CASE WHEN relay_2st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS misting_ratio
                                   , ROUND(AVG(CASE WHEN relay_3st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS drainage_ratio
                                   , ROUND(AVG(CASE WHEN relay_5st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS intake_fan_ratio
                                   , ROUND(AVG(CASE WHEN relay_6st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS exhaust_fan_ratio
                                   , ROUND(AVG(CASE WHEN relay_7st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS lighting_ratio
                                   , ROUND(AVG(CASE WHEN relay_8st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS irrigation_ratio
                                   , ROUND(AVG(CASE WHEN relay_9st_flag  THEN 1 ELSE 0 END)::numeric, 3) AS indoor_heater_ratio
                                   , ROUND(AVG(CASE WHEN relay_10st_flag THEN 1 ELSE 0 END)::numeric, 3) AS circulation_ratio
                                   , ROUND(AVG(CASE WHEN relay_11st_flag THEN 1 ELSE 0 END)::numeric, 3) AS intake_valve_ratio
                                   , ROUND(AVG(CASE WHEN relay_14st_flag THEN 1 ELSE 0 END)::numeric, 3) AS exhaust_valve_ratio
                                   , ROUND(AVG(CASE WHEN relay_15st_flag THEN 1 ELSE 0 END)::numeric, 3) AS heater_valve_ratio
                                FROM RELAY_L_RECORDING
                               WHERE farm_id   = %s AND hous_id    = %s
                                 AND recd_dttm > %s AND recd_dttm <= %s;"""

# 주야간 분리 센서 통계 (6시~17시 = 낮, 나머지 = 밤)
GET_SENSOR_STATS_DAY_NIGHT = """SELECT CASE WHEN EXTRACT(HOUR FROM recd_dttm) BETWEEN 6 AND 17 THEN 'day' ELSE 'night' END AS period
                                     , COUNT(*)                                   AS sample_count
                                     , ROUND(AVG(indr_tprt_valu)::numeric, 2)     AS avg_indoor_temp
                                     , ROUND(AVG(indr_hmdt_valu)::numeric, 2)     AS avg_indoor_humidity
                                     , ROUND(AVG(co2_valu)::numeric, 2)           AS avg_co2
                                     , ROUND(AVG(ligt_lvel_valu)::numeric, 2)     AS avg_light_level
                                  FROM SENSOR_L_RECORDING
                                 WHERE farm_id   = %s AND hous_id    = %s
                                   AND recd_dttm > %s AND recd_dttm <= %s
                                 GROUP BY period;"""

# 이동평균 조회 (6시간 윈도우 = 72건, 5분 간격 기준) — 시작/끝 샘플만 반환
GET_SENSOR_MOVING_AVG = """SELECT * FROM (
                             SELECT recd_dttm
                                  , ROUND(AVG(indr_tprt_valu) OVER w::numeric, 2) AS ma_indoor_temp
                                  , ROUND(AVG(indr_hmdt_valu) OVER w::numeric, 2) AS ma_indoor_humidity
                                  , ROW_NUMBER() OVER (ORDER BY recd_dttm ASC)    AS rn_asc
                                  , ROW_NUMBER() OVER (ORDER BY recd_dttm DESC)   AS rn_desc
                               FROM SENSOR_L_RECORDING
                              WHERE farm_id   = %s AND hous_id    = %s
                                AND recd_dttm > %s AND recd_dttm <= %s
                             WINDOW w AS (ORDER BY recd_dttm ROWS BETWEEN 72 PRECEDING AND CURRENT ROW)
                           ) sub
                           WHERE rn_asc = 1 OR rn_desc = 1
                           ORDER BY recd_dttm;"""

# 당일 생육 입력 존재 확인
CHECK_TODAY_CROPS_EXISTS = """SELECT COUNT(*) AS cnt
                               FROM FARMHOUSE_L_CROPS
                              WHERE farm_id = %s AND hous_id = %s
                                AND recd_dttm::date = CURRENT_DATE;"""

# 활성 농장-재배사 목록 + 현재 생육단계/작물종류
GET_ACTIVE_FARM_HOUSES_WITH_CROP = """SELECT DISTINCT FMI.farm_id
                                           , FMI.farm_name
                                           , HMI.hous_id
                                           , HMI.hous_name
                                           , HMI.crop_lvel
                                           , HMI.ctrl_type
                                           , CLV.code_name AS crop_level_name
                                        FROM FARM_M_INFO FMI
                                        JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
                                   LEFT JOIN CODE_M_INFO CLV ON CLV.code_id = 'crop_lvel' AND CLV.code_item = HMI.crop_lvel
                                       WHERE FMI.farm_id != 0 AND HMI.hous_id != 99
                                       ORDER BY FMI.farm_id, HMI.hous_id;"""


# ════════════════════════════════════════════════════════════════════════════
# AI 환경제어 LLM — 1년 전 시점 컨텍스트 조회용 SQL.
# 호출자: agri_ai_core.src.control.ai_history_context._fetch_year_ago_baseline.
# ════════════════════════════════════════════════════════════════════════════

# 특정 시점 기준 ±N일 범위의 최적조건 셋팅값(SENSOR_M_SETTING) 1건 — 기준일에 가장
# 가까운 setn_dttm 의 단일 행. (vals: farm_id, house_id, target_dttm, target_dttm)
GET_OPTIMAL_AT_DATE = """SELECT TO_CHAR(setn_dttm, 'YYYY-MM-DD HH24:MI:SS') AS 저장일자
                              , tprt_min       AS 온도최저
                              , tprt_otml      AS 온도적정
                              , tprt_max       AS 온도최고
                              , hmdt_min       AS 습도최저
                              , hmdt_otml      AS 습도적정
                              , hmdt_max       AS 습도최고
                              , co2_min        AS co2최저
                              , co2_otml       AS co2적정
                              , co2_max        AS co2최고
                              , watr_tprt_min  AS 수온최저
                              , watr_tprt_otml AS 수온적정
                              , watr_tprt_max  AS 수온최고
                           FROM SENSOR_M_SETTING
                          WHERE farm_id = %s AND hous_id = %s
                            AND setn_dttm BETWEEN (%s::timestamp - INTERVAL '7 days')
                                              AND (%s::timestamp + INTERVAL '7 days')
                          ORDER BY ABS(EXTRACT(EPOCH FROM (setn_dttm - %s::timestamp)))
                          LIMIT 1;"""

# 특정 시점 기준 ±N일 범위의 생육 입력값(FARMHOUSE_L_CROPS) 1건 — 기준일에 가장
# 가까운 recd_dttm 의 단일 행. (vals: farm_id, house_id, target_dttm, target_dttm,
# target_dttm)
GET_GROWTH_INPUT_AT_DATE = """SELECT TO_CHAR(HLC.recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS record_datetime
                                   , HLC.crop_kind
                                   , HLC.crop_lvel
                                   , HLC.ctrl_type
                                   , CMI.code_name AS growth_status
                                   , HLC.leaf_count
                                   , HLC.leaf_size
                                   , HLC.leaf_color
                                   , HLC.stem_height
                                   , HLC.stem_diameter
                                   , HLC.fruit_count
                                   , HLC.fruit_size
                                   , HLC.pest_type
                                   , HLC.pest_severity
                                   , HLC.growth_memo
                                   , HLC.crop_qtty AS total_yield
                                   , HLC.crop_grde_qtty_1 AS grade_1_yield
                                FROM FARMHOUSE_L_CROPS HLC
                           LEFT JOIN CODE_M_INFO CMI ON CMI.code_id = 'crop_stat' AND CMI.code_item = HLC.crop_stat
                               WHERE HLC.farm_id = %s AND HLC.hous_id = %s
                                 AND HLC.recd_dttm BETWEEN (%s::timestamp - INTERVAL '7 days')
                                                       AND (%s::timestamp + INTERVAL '7 days')
                               ORDER BY ABS(EXTRACT(EPOCH FROM (HLC.recd_dttm - %s::timestamp)))
                               LIMIT 1;"""


# ════════════════════════════════════════════════════════════════════════════
# AI 자기결정 이력 — ai_decision_log 테이블
# 호출자: agri_ai_core.src.control.ai_decision_log
# 테이블 자동 생성 DDL 도 동봉 (없으면 모듈이 생성).
# ════════════════════════════════════════════════════════════════════════════

CREATE_AI_DECISION_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS ai_decision_log (
    id              BIGSERIAL PRIMARY KEY,
    decided_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    farm_id         INTEGER NOT NULL,
    house_id        INTEGER NOT NULL,
    growth_stage    VARCHAR(32),
    action          VARCHAR(16) NOT NULL,
    circulation     VARCHAR(16),
    water_heater    BOOLEAN,
    fog_occurs      BOOLEAN,
    drainage_motor  BOOLEAN,
    reason          VARCHAR(256),
    sensor_snapshot JSONB,
    feedback        VARCHAR(8),
    feedback_at     TIMESTAMP
);
ALTER TABLE ai_decision_log
    ADD COLUMN IF NOT EXISTS drainage_motor BOOLEAN;
CREATE INDEX IF NOT EXISTS idx_ai_decision_log_house_time
    ON ai_decision_log (farm_id, house_id, decided_at DESC);
"""

INSERT_AI_DECISION_LOG = """
INSERT INTO ai_decision_log
    (decided_at, farm_id, house_id, growth_stage, action, circulation,
     water_heater, fog_occurs, drainage_motor, reason, sensor_snapshot)
VALUES
    (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
RETURNING id;
"""

GET_RECENT_AI_DECISIONS = """
SELECT TO_CHAR(decided_at, 'YYYY-MM-DD HH24:MI:SS') AS decided_at,
       action, circulation, water_heater, fog_occurs, drainage_motor, reason, feedback
  FROM ai_decision_log
 WHERE farm_id = %s AND house_id = %s
 ORDER BY decided_at DESC
 LIMIT %s
"""  # 사용 안함 — 아래 호환 SQL(GET_RECENT_AI_DECISIONS_SQL) 사용

GET_RECENT_AI_DECISIONS_SQL = """
SELECT TO_CHAR(decided_at, 'YYYY-MM-DD HH24:MI:SS') AS decided_at,
       action, circulation, water_heater, fog_occurs, drainage_motor, reason, feedback
  FROM ai_decision_log
 WHERE farm_id = %s AND house_id = %s
 ORDER BY decided_at DESC
 LIMIT %s;
"""

UPDATE_AI_DECISION_FEEDBACK = """
UPDATE ai_decision_log
   SET feedback = %s, feedback_at = NOW()
 WHERE id = %s;
"""

# ════════════════════════════════════════════════════════════════════════════
# 관리자 강제 지시(admin directive) — 사용자(농장주/관리자)가 명시
#   지시한 장치 상태를 해제 시까지 강제 유지. 우선순위: 인터록(물리보호) >
#   관리자지시 > 비상가드 > LLM. 채팅 "OFF 유지" 류 지속 요청의 공식 이행 수단.
# ════════════════════════════════════════════════════════════════════════════
CREATE_ADMIN_DIRECTIVE_TABLE = """
CREATE TABLE IF NOT EXISTS admin_device_directive (
    farm_id      INTEGER      NOT NULL,
    house_id     INTEGER      NOT NULL,
    semantic     VARCHAR(40)  NOT NULL,
    forced_value BOOLEAN      NOT NULL,
    note         VARCHAR(200),
    created_by   VARCHAR(40),
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    released_at  TIMESTAMP,
    PRIMARY KEY (farm_id, house_id, semantic)
);
"""

GET_ACTIVE_ADMIN_DIRECTIVES = """
SELECT semantic, forced_value, note, created_by,
       to_char(created_at, 'MM-DD HH24:MI') AS created_at
  FROM admin_device_directive
 WHERE farm_id = %s AND house_id = %s AND released_at IS NULL;
"""

UPSERT_ADMIN_DIRECTIVE = """
INSERT INTO admin_device_directive
    (farm_id, house_id, semantic, forced_value, note, created_by, created_at, released_at)
VALUES (%s, %s, %s, %s, %s, %s, NOW(), NULL)
ON CONFLICT (farm_id, house_id, semantic) DO UPDATE SET
    forced_value = EXCLUDED.forced_value,
    note = EXCLUDED.note,
    created_by = EXCLUDED.created_by,
    created_at = NOW(),
    released_at = NULL;
"""

RELEASE_ADMIN_DIRECTIVE = """
UPDATE admin_device_directive
   SET released_at = NOW()
 WHERE farm_id = %s AND house_id = %s AND semantic = %s AND released_at IS NULL;
"""

# ════════════════════════════════════════════════════════════════════════════
# 농장별 지역정보 — 기상 격자좌표(kma_nx/ny)·생활기상지수 지점코드(kma_area_no)
#   지역정보는 농장 속성이므로 env 전역값이 아닌 farm_m_info 에서 실시간 read.
#   농장 추가 시 코드 변경 없이 등록 데이터만으로 확장.
# ════════════════════════════════════════════════════════════════════════════
GET_FARM_GEO = """SELECT farm_name, kma_area_no, kma_nx, kma_ny
                    FROM farm_m_info
                   WHERE farm_id = %s AND dlte_yn = 'N'"""

# ════════════════════════════════════════════════════════════════════════════
# 제어 중재(arbitration) — agent 우선 · 스케줄 30분 failover
#   control_arbitration_state : 재배사별 agent/스케줄 제어 시작·종료 시각 저장
#   control_arbitration_config: 30분(유예)·10분(스케줄 주기) 실시간 조정 파라미터
# ════════════════════════════════════════════════════════════════════════════
CREATE_CONTROL_ARBITRATION_TABLE = """
CREATE TABLE IF NOT EXISTS control_arbitration_state (
    farm_id                     INTEGER NOT NULL,
    house_id                    INTEGER NOT NULL,
    last_agent_ctrl_stt_dttm    TIMESTAMP,
    last_agent_ctrl_end_dttm    TIMESTAMP,
    last_sched_ctrl_stt_dttm    TIMESTAMP,
    last_sched_ctrl_end_dttm    TIMESTAMP,
    active_controller           VARCHAR(16) NOT NULL DEFAULT 'none',
    updt_dttm                   TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (farm_id, house_id)
);
CREATE TABLE IF NOT EXISTS control_arbitration_config (
    id                          INTEGER PRIMARY KEY DEFAULT 1,
    agent_idle_failover_min     INTEGER NOT NULL DEFAULT 30,
    sched_failover_interval_min INTEGER NOT NULL DEFAULT 10,
    updt_dttm                   TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_arb_config_singleton CHECK (id = 1)
);
INSERT INTO control_arbitration_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
"""

# agent 제어 시작 stamp (set_relay 큐 적재 시)
UPSERT_ARB_AGENT_START = """
INSERT INTO control_arbitration_state
    (farm_id, house_id, last_agent_ctrl_stt_dttm, updt_dttm)
VALUES (%s, %s, NOW(), NOW())
ON CONFLICT (farm_id, house_id) DO UPDATE SET
    last_agent_ctrl_stt_dttm = NOW(),
    updt_dttm = NOW();
"""

# agent 제어 종료 stamp (set_relay 실제 실행 완료 시) — idle 판정 기준
UPSERT_ARB_AGENT_END = """
INSERT INTO control_arbitration_state
    (farm_id, house_id, last_agent_ctrl_end_dttm, active_controller, updt_dttm)
VALUES (%s, %s, NOW(), 'agent', NOW())
ON CONFLICT (farm_id, house_id) DO UPDATE SET
    last_agent_ctrl_end_dttm = NOW(),
    active_controller = 'agent',
    updt_dttm = NOW();
"""

# 스케줄 제어 시작 stamp (게이트 통과 시) — 10분 throttle 기준
UPSERT_ARB_SCHED_START = """
INSERT INTO control_arbitration_state
    (farm_id, house_id, last_sched_ctrl_stt_dttm, active_controller, updt_dttm)
VALUES (%s, %s, NOW(), 'schedule', NOW())
ON CONFLICT (farm_id, house_id) DO UPDATE SET
    last_sched_ctrl_stt_dttm = NOW(),
    active_controller = 'schedule',
    updt_dttm = NOW();
"""

# 스케줄 제어 종료 stamp (사이클 완료 시)
UPSERT_ARB_SCHED_END = """
INSERT INTO control_arbitration_state
    (farm_id, house_id, last_sched_ctrl_end_dttm, updt_dttm)
VALUES (%s, %s, NOW(), NOW())
ON CONFLICT (farm_id, house_id) DO UPDATE SET
    last_sched_ctrl_end_dttm = NOW(),
    updt_dttm = NOW();
"""

# 중재 상태 조회 — 서버시각 기준 경과초를 함께 계산(클라이언트 시계 편차 회피)
GET_ARBITRATION_STATE = """
SELECT farm_id, house_id,
       last_agent_ctrl_stt_dttm, last_agent_ctrl_end_dttm,
       last_sched_ctrl_stt_dttm, last_sched_ctrl_end_dttm,
       active_controller,
       EXTRACT(EPOCH FROM (NOW() - last_agent_ctrl_end_dttm)) AS agent_idle_sec,
       EXTRACT(EPOCH FROM (NOW() - last_sched_ctrl_stt_dttm)) AS sched_since_stt_sec
  FROM control_arbitration_state
 WHERE farm_id = %s AND house_id = %s;
"""

GET_ARBITRATION_CONFIG = """
SELECT agent_idle_failover_min, sched_failover_interval_min
  FROM control_arbitration_config
 WHERE id = 1;
"""

# ════════════════════════════════════════════════════════════════════════════
# M7 재배사간 시점 비교 — 동일 농장 다른 재배사의 최신 센서/릴레이
# ════════════════════════════════════════════════════════════════════════════
GET_PEER_HOUSES_LATEST_SENSOR = """
SELECT s.farm_id, s.hous_id,
       TO_CHAR(s.recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS record_datetime,
       s.indr_tprt_valu AS indoor_temp,
       s.indr_hmdt_valu AS indoor_humidity,
       s.co2_valu       AS co2,
       s.watr_tprt_valu AS water_temp
  FROM SENSOR_L_RECORDING s
  JOIN (SELECT farm_id, hous_id, MAX(recd_dttm) AS max_dttm
          FROM SENSOR_L_RECORDING
         WHERE farm_id = %s AND hous_id <> %s
           AND recd_dttm >= NOW() - INTERVAL '10 minutes'
         GROUP BY farm_id, hous_id) t
    ON t.farm_id = s.farm_id AND t.hous_id = s.hous_id AND t.max_dttm = s.recd_dttm
 ORDER BY s.hous_id;
"""

GET_PEER_HOUSES_LATEST_RELAY = """
SELECT r.farm_id, r.hous_id,
       r.relay_1st_flag, r.relay_2st_flag,
       r.relay_5st_flag, r.relay_6st_flag, r.relay_7st_flag,
       r.relay_10st_flag, r.relay_11st_flag, r.relay_14st_flag
  FROM RELAY_L_RECORDING r
  JOIN (SELECT farm_id, hous_id, MAX(recd_dttm) AS max_dttm
          FROM RELAY_L_RECORDING
         WHERE farm_id = %s AND hous_id <> %s
           AND recd_dttm >= NOW() - INTERVAL '10 minutes'
         GROUP BY farm_id, hous_id) t
    ON t.farm_id = r.farm_id AND t.hous_id = r.hous_id AND t.max_dttm = r.recd_dttm
 ORDER BY r.hous_id;
"""

# ════════════════════════════════════════════════════════════════════════════
# M9 이상사건 직전 환경 — 병해 발생 직전 24h 센서 평균
# 입력: farm_id, house_id, lookback_days(기본 60)
# ════════════════════════════════════════════════════════════════════════════
GET_RECENT_ANOMALY_EVENTS = """
SELECT TO_CHAR(recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS event_time,
       pest_type, pest_severity, growth_memo, crop_lvel
  FROM FARMHOUSE_L_CROPS
 WHERE farm_id = %s AND hous_id = %s
   AND recd_dttm >= NOW() - %s::interval
   AND pest_type IS NOT NULL AND pest_type <> '없음' AND pest_type <> ''
 ORDER BY recd_dttm DESC
 LIMIT 5;
"""

GET_SENSOR_AVG_BEFORE = """
SELECT ROUND(AVG(indr_tprt_valu)::numeric, 2) AS avg_indoor_temp,
       ROUND(AVG(indr_hmdt_valu)::numeric, 2) AS avg_indoor_humidity,
       ROUND(AVG(co2_valu)::numeric, 2)       AS avg_co2,
       ROUND(AVG(watr_tprt_valu)::numeric, 2) AS avg_water_temp,
       COUNT(*)                                AS sample_count
  FROM SENSOR_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
   AND recd_dttm BETWEEN (%s::timestamp - INTERVAL '24 hours') AND %s::timestamp;
"""

# ════════════════════════════════════════════════════════════════════════════
# M13 수확 결과 상관 — 1등급률 ≥ 0.6 시기의 환경 평균
# 같은 재배사·생육단계 기준
# ════════════════════════════════════════════════════════════════════════════
GET_HIGH_QUALITY_PERIODS = """
SELECT TO_CHAR(HLC.recd_dttm, 'YYYY-MM-DD') AS period_date,
       HLC.crop_lvel,
       HLC.crop_qtty AS total_yield,
       HLC.crop_grde_qtty_1 AS grade_1_yield,
       CASE WHEN HLC.crop_qtty > 0
            THEN ROUND((HLC.crop_grde_qtty_1::numeric / HLC.crop_qtty)::numeric, 3)
            ELSE 0 END AS grade_1_ratio
  FROM FARMHOUSE_L_CROPS HLC
 WHERE HLC.farm_id = %s AND HLC.hous_id = %s
   AND HLC.crop_qtty > 0
   AND (HLC.crop_grde_qtty_1::numeric / NULLIF(HLC.crop_qtty, 0)) >= 0.6
 ORDER BY HLC.recd_dttm DESC
 LIMIT 5;
"""

# ════════════════════════════════════════════════════════════════════════════
# M16 다년치 동월 평균 — 같은 월(현재 월) 의 연도별 환경 평균
# ════════════════════════════════════════════════════════════════════════════
GET_MONTHLY_SEASONALITY = """
SELECT EXTRACT(YEAR FROM recd_dttm)::int           AS yr,
       ROUND(AVG(indr_tprt_valu)::numeric, 2)       AS avg_indoor_temp,
       ROUND(AVG(indr_hmdt_valu)::numeric, 2)       AS avg_indoor_humidity,
       ROUND(AVG(co2_valu)::numeric, 2)             AS avg_co2,
       ROUND(AVG(watr_tprt_valu)::numeric, 2)       AS avg_water_temp,
       COUNT(*)                                      AS sample_count
  FROM SENSOR_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
   AND EXTRACT(MONTH FROM recd_dttm)::int = %s
 GROUP BY yr
 ORDER BY yr DESC
 LIMIT 5;
"""

# ════════════════════════════════════════════════════════════════════════════
# M17 전력 사용량 — 릴레이 가동시간 추정 (실측 인프라 미장착)
# 최근 24h 동안 각 릴레이의 ON 비율을 기반으로 추정 사용 시간(시간 단위)
# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# 최근 시계열 N분 간격 K건 — LLM raw 시계열 컨텍스트
# vals: farm_id, house_id, bucket_seconds, lookback_minutes, sample_count
# ════════════════════════════════════════════════════════════════════════════
GET_RECENT_TIMESERIES_SAMPLES = """
WITH ranked AS (
    SELECT recd_dttm,
           indr_tprt_valu  AS indoor_temp,
           indr_hmdt_valu  AS indoor_humidity,
           co2_valu        AS co2,
           watr_tprt_valu  AS water_temp,
           oudr_tprt_valu  AS outdoor_temp,
           oudr_hmdt_valu  AS outdoor_humidity,
           ROW_NUMBER() OVER (
               PARTITION BY (FLOOR(EXTRACT(EPOCH FROM recd_dttm) / %s)::bigint)
               ORDER BY recd_dttm DESC
           ) AS rn
      FROM SENSOR_L_RECORDING
     WHERE farm_id = %s AND hous_id = %s
       AND recd_dttm >= NOW() - (%s * INTERVAL '1 minute')
)
SELECT TO_CHAR(recd_dttm, 'YYYY-MM-DD HH24:MI:SS') AS t,
       indoor_temp, indoor_humidity, co2, water_temp,
       outdoor_temp, outdoor_humidity
  FROM ranked
 WHERE rn = 1
 ORDER BY recd_dttm DESC
 LIMIT %s;
"""


GET_POWER_USAGE_24H = """
SELECT COUNT(*)                                                                  AS sample_count,
       ROUND(SUM(CASE WHEN relay_1st_flag  THEN 1 ELSE 0 END)::numeric * 24
             / NULLIF(COUNT(*), 0), 2)                                            AS heater_hours,
       ROUND(SUM(CASE WHEN relay_2st_flag  THEN 1 ELSE 0 END)::numeric * 24
             / NULLIF(COUNT(*), 0), 2)                                            AS misting_hours,
       ROUND(SUM(CASE WHEN relay_5st_flag  THEN 1 ELSE 0 END)::numeric * 24
             / NULLIF(COUNT(*), 0), 2)                                            AS intake_fan_hours,
       ROUND(SUM(CASE WHEN relay_6st_flag  THEN 1 ELSE 0 END)::numeric * 24
             / NULLIF(COUNT(*), 0), 2)                                            AS exhaust_fan_hours,
       ROUND(SUM(CASE WHEN relay_7st_flag  THEN 1 ELSE 0 END)::numeric * 24
             / NULLIF(COUNT(*), 0), 2)                                            AS lighting_hours,
       ROUND(SUM(CASE WHEN relay_8st_flag  THEN 1 ELSE 0 END)::numeric * 24
             / NULLIF(COUNT(*), 0), 2)                                            AS irrigation_hours
  FROM RELAY_L_RECORDING
 WHERE farm_id = %s AND hous_id = %s
   AND recd_dttm >= NOW() - INTERVAL '24 hours';
"""


# ════════════════════════════════════════════════════════════════════
# [프롬프트 자동화] context 외부화용 테이블 DDL
#
# 분리 원칙:
#   · 가능한 ChromaDB(벡터 학습 데이터) 로 관리 → 학습 누적·자체 고도화
#   · 사용자가 직접 관리해야 할 정확 데이터만 PostgreSQL
#
# 테이블 (PostgreSQL — 사용자 관리):
#   tool_definition_m  : query_handler 도구 schema (정확 JSON, 활성/비활성 토글)
#   prompt_block_m     : 시스템 프롬프트 정형 블록 (순환모드표 등 사용자 편집 단위)
#
# (ChromaDB 컬렉션 — 학습 진화):
#   prompt_chunk_v     : 시스템/유저/분석/답변 프롬프트 chunk
#   domain_rule_v      : 결합 규칙·안전 룰·사용자 학습 룰
# ════════════════════════════════════════════════════════════════════

CREATE_TOOL_DEFINITION_M_TABLE = """
CREATE TABLE IF NOT EXISTS tool_definition_m (
    tool_id         VARCHAR(64) PRIMARY KEY,
    schema_json     JSONB NOT NULL,
    description     TEXT NOT NULL,
    category        VARCHAR(32),
    priority        INTEGER NOT NULL DEFAULT 100,
    active_yn       CHAR(1) NOT NULL DEFAULT 'Y',
    rgst_dttm       TIMESTAMP NOT NULL DEFAULT NOW(),
    updt_dttm       TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tool_def_category
    ON tool_definition_m (category, active_yn, priority);
"""

CREATE_PROMPT_BLOCK_M_TABLE = """
CREATE TABLE IF NOT EXISTS prompt_block_m (
    block_id        VARCHAR(64) PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    body_text       TEXT NOT NULL,
    placeholders    JSONB,
    description     VARCHAR(512),
    active_yn       CHAR(1) NOT NULL DEFAULT 'Y',
    rgst_dttm       TIMESTAMP NOT NULL DEFAULT NOW(),
    updt_dttm       TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

CREATE_CONTROL_PROMPT_M_TABLE = """
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
"""

GET_CONTROL_PROMPT_UPDT = """SELECT updt_dttm FROM control_prompt_m WHERE block_id = %s"""

GET_ALL_CONTROL_PROMPTS = """
SELECT block_id, section_key, growth_stage, sort_order, category, name,
       body_text, placeholders, active_yn, description, updt_dttm
FROM control_prompt_m
ORDER BY category, sort_order, block_id
"""
