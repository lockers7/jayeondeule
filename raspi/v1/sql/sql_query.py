# 자동 기록 삽입 SQL
# INSERT_AUTO_RECD_SQL               = "INSERT INTO farm_sensor_recd   (farm_id,          recd_date, temp_val,       humi_val,       co2val,   water_temp_val, outdoor_temp_val, outdoor_humi_val                              ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);"
INSERT_AUTO_RECD_SQL                 = "INSERT INTO SENSOR_L_RECORDING (farm_id, hous_id, recd_dttm, indr_tprt_valu, indr_hmdt_valu, co2_valu, watr_tprt_valu, oudr_tprt_valu,   oudr_hmdt_valu, ligt_lvel_valu, watr_lvel_valu) VALUES (%s, 2, %s, %s, %s, %s, %s, %s, %s, 0, 0);"
# 릴레이 상태 삽입 SQL
# INSERT_RELAY_STATUS_SQL            = "INSERT INTO farm_relay_status (relay1st,       relay2st,       relay3st,       relay4st,       relay5st,       relay6st,       relay7st,       relay8st,       relay9st,       relay10st,       relay11st,      relay12st,        relay13st,       relay14st,       relay15st                         farm_id,          recd_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);"
# 2호 재배사 전용 (hous_id=2 하드코딩, relay_16st_flag는 %s로 파라미터 받음)
INSERT_RELAY_STATUS_SQL              = "INSERT INTO RELAY_L_RECORDING (relay_1st_flag, relay_2st_flag, relay_3st_flag, relay_4st_flag, relay_5st_flag, relay_6st_flag, relay_7st_flag, relay_8st_flag, relay_9st_flag, relay_10st_flag, relay_11st_flag, relay_12st_flag, relay_13st_flag, relay_14st_flag, relay_15st_flag, relay_16st_flag, farm_id, hous_id, recd_dttm) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2, %s);"

# 갱신 플래그 업데이트 SQL
# UPDATE_REFRESH_FLAG_SQL            = "UPDATE farm_status      SET refresh_flag=%s WHERE farm_id=%s;"
UPDATE_REFRESH_FLAG_SQL              = "UPDATE farmhouse_m_info SET rfrs_flag=%s    WHERE farm_id=%s AND hous_id=%s;"

# 갱신 플래그 조회 SQL
# SELECT_REFRESH_FLAG_SQL            = "SELECT refresh_flag FROM farm_status   WHERE farm_id=%s               LIMIT 1;"
SELECT_REFRESH_FLAG_SQL              = "SELECT rfrs_flag FROM farmhouse_m_info WHERE farm_id=%s AND hous_id=%s LIMIT 1;"

# 기준 설정 조회 SQL
# SELECT_BASE_SET_VALUE_SQL          = "SELECT temp_min, temp_max, humi_min, humi_max, co2min,  co2max,  water_temp_min, water_temp_max FROM farm_generic_setting WHERE farm_id=%s                ORDER BY appl_date DESC LIMIT 1;"
SELECT_BASE_SET_VALUE_SQL            = "SELECT tprt_min, tprt_max, hmdt_min, hmdt_max, co2_min, co2_max, watr_tprt_min,  watr_tprt_max  FROM sensor_m_setting     WHERE farm_id=%s AND hous_id=%s ORDER BY setn_dttm DESC LIMIT 1;"

# 조명 설정 조회 SQL
# SELECT_LGHT_SET_VALUE_SQL          = "SELECT fr_time,   to_time   FROM farm_water_light_setting.  WHERE farm_id=%s               AND type=%s      AND deleted=false;"
SELECT_LGHT_SET_VALUE_SQL            = "SELECT strt_time, fnsh_time FROM light_irrigation_s_setting WHERE farm_id=%s AND hous_id=2 AND unit_type=%s AND dlte_yn=false;"

# 급수 설정 조회 SQL
# SELECT_WATR_SET_VALUE_SQL          = "SELECT fr_time,   to_time   FROM farm_water_light_setting   WHERE farm_id=%s AND type=%s AND deleted=false;"
SELECT_WATR_SET_VALUE_SQL            = "SELECT strt_time, fnsh_time FROM light_irrigation_s_setting WHERE farm_id=%s AND type=%s AND deleted=false;"

# 센서 갱신 주기 조회 SQL
# SELECT_SENSOR_REFRESH_INTERVAL_SQL = "SELECT sensor_refresh_interval FROM farm_status      WHERE farm_id=%s;"
SELECT_SENSOR_REFRESH_INTERVAL_SQL   = "SELECT snsr_rfrs_itvl          FROM farmhouse_m_info WHERE farm_id=%s AND hous_id=%s;"

# 릴레이 수동 제어 플래그 조회 SQL
# SELECT_RELAY_MANUAL_CONTROL_FLAG_SQL = "SELECT manual_control_flag FROM farm_status WHERE farm_id=%s;"
SELECT_RELAY_MANUAL_CONTROL_FLAG_SQL   = "SELECT mnul_ctrl_flag FROM farmhouse_m_info WHERE farm_id=%s AND hous_id=%s;"

# 릴레이 상태 조회 SQL
# SELECT_RELAY_STATUS_SQL            = "SELECT relay1st,       relay2st,       relay3st,       relay4st,       relay5st,       relay6st,       relay7st,       relay8st,       relay9st,       relay10st,       relay11st,       relay12st,       relay13st,       relay14st,       relay15st       FROM farm_relay_status WHERE farm_id=%s                ORDER BY recd_date DESC LIMIT 1;"
SELECT_RELAY_STATUS_SQL              = "SELECT relay_1st_flag, relay_2st_flag, relay_3st_flag, relay_4st_flag, relay_5st_flag, relay_6st_flag, relay_7st_flag, relay_8st_flag, relay_9st_flag, relay_10st_flag, relay_11st_flag, relay_12st_flag, relay_13st_flag, relay_14st_flag, relay_15st_flag FROM relay_l_recording WHERE farm_id=%s AND hous_id=%s ORDER BY recd_dttm DESC LIMIT 1;"

# 외부 온도, 습도
SELECT_OUTDOOR_SENSOR                = """
                                        SELECT 
                                        ((SELECT oudr_tprt_valu FROM SENSOR_L_RECORDING WHERE farm_id=1 AND hous_id=1 ORDER BY recd_dttm DESC LIMIT 1)+
                                        (SELECT oudr_tprt_valu FROM SENSOR_L_RECORDING WHERE farm_id=1 AND hous_id=3 ORDER BY recd_dttm DESC LIMIT 1))/2
                                        as outdoor_temp_val,
                                        ((SELECT oudr_hmdt_valu FROM SENSOR_L_RECORDING WHERE farm_id=1 AND hous_id=1 ORDER BY recd_dttm DESC LIMIT 1)+
                                        (SELECT oudr_hmdt_valu FROM SENSOR_L_RECORDING WHERE farm_id=1 AND hous_id=3 ORDER BY recd_dttm DESC LIMIT 1))/2
                                        as outdoor_humi_val
                                        ;
                                       """ 

# 온도 1도 올리는데 필요한 분(minute)
                                             #   SELECT a.recd_date                                       AS recd_date
                                             #        , a.water_temp_val                                  AS water_temp_val
                                             #        , LAG(a.recd_date)      OVER (ORDER BY a.recd_date) AS prev_recd_date
                                             #        , LAG(a.water_temp_val) OVER (ORDER BY a.recd_date) AS prev_water_temp_val
                                             #     FROM farm_sensor_recd  a
                                             #     JOIN farm_relay_status b ON b.farm_id = a.farm_id AND b.recd_date = a.recd_date
                                            	#    WHERE a.farm_id = %s AND b.relay1st = %s AND b.relay2st = %s
                                             #   ),
SELECT_GAP_WATER_1_UP_WITH_CHILLER   = """WITH TempValData AS (
                                               SELECT a.recd_dttm                                       AS recd_date
                                                    , a.watr_tprt_valu                                  AS water_temp_val
                                                    , LAG(a.recd_dttm)      OVER (ORDER BY a.recd_dttm) AS prev_recd_date
                                                    , LAG(a.watr_tprt_valu) OVER (ORDER BY a.recd_dttm) AS prev_water_temp_val
                                                 FROM sensor_l_recording a
                                                 JOIN relay_l_recording  b ON b.farm_id = a.farm_id AND b.hous_id=a.hous_id AND b.recd_dttm = a.recd_dttm
                                            	   WHERE a.farm_id = %s AND a.hous_id=2 AND b.relay_1st_flag = %s AND b.relay_2st_flag = %s
                                               ),
                                               TimeDiff AS (
                                                    SELECT recd_date
                                                         , water_temp_val
                                                         , prev_water_temp_val
                                                         , EXTRACT(EPOCH FROM (recd_date - prev_recd_date)) / 60 AS time_diff
                                                      FROM TempValData
                                                     WHERE prev_water_temp_val IS NOT NULL AND water_temp_val - prev_water_temp_val >= 1
                                               )
                                               SELECT time_diff AS diff_minutes
                                               FROM TimeDiff
                                               ORDER BY recd_date DESC
                                               LIMIT 1;"""

# 30초 단위 백업 위한 쿼리
BACKUP_AUTO_SENSE_DATA              = """--
                                         --"""