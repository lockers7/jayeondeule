# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 기본 조회 쿼리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
GET_ONE_FARM = "SELECT farm_id, farm_name FROM FARM_M_INFO ORDER BY farm_id LIMIT 1"
GET_ONE_HOUSE = "SELECT hous_id, hous_name FROM FARMHOUSE_M_INFO WHERE farm_id = %s ORDER BY hous_id LIMIT 1"
GET_LIST_FARM = "SELECT farm_id, farm_name FROM FARM_M_INFO"

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장/재배사 정보 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
GET_FARM_NAME = """SELECT DISTINCT farm_id, farm_name
                   FROM FARM_M_INFO
                   WHERE farm_id != 0 AND (farm_id = %s OR %s IS NULL)
                   ORDER BY farm_name ASC;"""

GET_HOUSE_NAME = """SELECT DISTINCT hous_id, hous_name
                    FROM FARMHOUSE_M_INFO
                    WHERE farm_id = %s AND hous_id = %s
                    ORDER BY hous_name ASC;"""

GET_HOUSE_ID = """SELECT DISTINCT farm_id, hous_id
                  FROM FARMHOUSE_M_INFO
                  WHERE (farm_id = %d OR %s IS NULL) AND hous_name LIKE %s;"""

GET_FARM_HOUSE_INFO = """SELECT DISTINCT FMI.farm_name, HMI.hous_name, HMI.mnul_ctrl_flag
                         FROM FARM_M_INFO FMI
                         JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
                         WHERE FMI.farm_id != 0 AND FMI.farm_id = %s AND HMI.hous_id = %s;"""

GET_FARM_HOUSE_LIST = """SELECT DISTINCT FMI.farm_id, FMI.farm_name, HMI.hous_id, HMI.hous_name, HMI.mnul_ctrl_flag
                         FROM FARM_M_INFO FMI
                         JOIN FARMHOUSE_M_INFO HMI ON HMI.farm_id = FMI.farm_id
                         WHERE 1 = 1 AND FMI.farm_id != 0 AND HMI.hous_id != 99
                         ORDER BY 1, 3;"""

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 현재 센서 정보 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 센서 히스토리 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 정보 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
GET_LATEST_RELAY_INFO = """SELECT relay_1st_flag,  relay_2st_flag,  relay_3st_flag,  relay_4st_flag
                                , relay_5st_flag,  relay_6st_flag,  relay_7st_flag,  relay_8st_flag
                                , relay_9st_flag,  relay_10st_flag, relay_11st_flag, relay_12st_flag
                                , relay_13st_flag, relay_14st_flag, relay_15st_flag, relay_16st_flag
                             FROM RELAY_L_RECORDING
                            WHERE farm_id = %s
                              AND hous_id = %s
                            ORDER BY recd_dttm DESC
                            LIMIT 1"""

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 상세 정보 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
GET_FARM_INFO_LIST = """SELECT FMI.farm_id                         AS 농장코드
                             , FMI.farm_name                       AS 농장명
                             , farm_domi                           AS 도메인
                             , open_date                           AS 영업시작일
                             , clse_date                           AS 영업종료일
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
                         GROUP BY FMI.farm_id, FMI.farm_name, farm_domi, open_date, clse_date,
                                  tel_no, FMI.hp_no, fax_no, mail, CM1.code_name, addr,
                                  main_prdt, FMI.rmks, user_name, UMI.hp_no;"""

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Units 데이터 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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
                          , relay_2st_flag                    AS 습도모터
                          , relay_3st_flag                    AS 배수밸브
                          , relay_5st_flag                    AS 흡입모터
                          , relay_6st_flag                    AS 배출모터
                          , relay_7st_flag                    AS 조명토글
                          , relay_8st_flag                    AS 관수토글
                          , relay_9st_flag                    AS 내부히터
                          , relay_10st_flag                   AS 순환밸브
                          , relay_11st_flag                   AS 흡입밸브
                          , relay_14st_flag                   AS 배출밸브
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

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Crops 데이터 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최적 조건 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
GET_OPTIMAL_CONDITION = """SELECT setn_dttm      AS 저장일자
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
                                , heat_tprt_min  AS 히터최저
                                , heat_tprt_otml AS 히터적정
                                , heat_tprt_max  AS 히터최고
                              FROM SENSOR_M_SETTING O
                             WHERE farm_id = %s
                               AND hous_id = %s
                               AND setn_dttm = (SELECT MAX(setn_dttm)
                                                  FROM SENSOR_M_SETTING
                                                 WHERE farm_id = O.farm_id
                                                   AND hous_id = O.hous_id)
                             ORDER BY setn_dttm DESC
                             LIMIT 1"""

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 조명/관수 설정 조회
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 릴레이 설정 저장
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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

SET_RELAY_VALUE_E = """INSERT INTO farm_relay_status (farm_id,  recd_date
                                                    , relay1st,   relay2st,  relay3st,  relay4st
                                                    , relay5st,   relay6st,  relay7st,  relay8st
                                                    , relay9st,   relay10st, relay11st, relay12st
                                                    , relay13st,  relay14st, relay15st)
                                               VALUES (2, %s
                                                    , %s, %s, %s, %s
                                                    , %s, %s, %s, %s
                                                    , %s, %s, %s, %s
                                                    , %s, %s, %s);"""

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 재배사 정보 업데이트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
SET_FARMHOUSE_INFO = "UPDATE FARMHOUSE_M_INFO SET last_get_dttm=%s WHERE farm_id=%s AND hous_id=%s;"

SET_MANAGE_METHOD = "UPDATE FARMHOUSE_M_INFO SET mnul_ctrl_flag=%s WHERE farm_id=%s AND hous_id=%s;"
