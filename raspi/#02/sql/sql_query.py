#------------------------------------
# 실시간 데이터 값 저장
#------------------------------------
# 센서 값
INSERT_AUTO_RECD_SQL   = "INSERT INTO SENSOR_L_RECORDING (farm_id, hous_id, recd_dttm, indr_tprt_valu, indr_hmdt_valu, oudr_tprt_valu, oudr_hmdt_valu, co2_valu, watr_tprt_valu, ligt_lvel_valu, watr_lvel_valu) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);"
# 릴레이 값
INSERT_RELAY_STATUS_SQL = "INSERT INTO RELAY_L_RECORDING (farm_id, hous_id, recd_dttm, relay_1st_flag, relay_2st_flag, relay_3st_flag, relay_4st_flag, relay_5st_flag, relay_6st_flag, relay_7st_flag, relay_8st_flag, relay_9st_flag, relay_10st_flag, relay_11st_flag, relay_12st_flag, relay_13st_flag, relay_14st_flag, relay_15st_flag, relay_16st_flag) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);"

#------------------------------------
# 홈페이지 리프레쉬 갱신값 업데이터
#------------------------------------
UPDATE_REFRESH_FLAG_SQL              = "UPDATE FARMHOUSE_M_INFO SET rfrs_flag=%s WHERE farm_id=%s AND hous_id=%s;"

#------------------------------------
# 이후는 설정값 등 단순 조회
#------------------------------------
# 갱신플래그
SELECT_REFRESH_FLAG_SQL              = "SELECT rfrs_flag FROM FARMHOUSE_M_INFO WHERE farm_id=%s AND hous_id=%s LIMIT 1;"
# 센서 설정 값
SELECT_BASE_SET_VALUE_SQL            = "SELECT tprt_min, tprt_max, hmdt_min, hmdt_max, co2_min, co2_max, watr_tprt_min, watr_tprt_max, heat_tprt_min, heat_tprt_max FROM SENSOR_M_SETTING WHERE farm_id=%s AND hous_id=%s ORDER BY setn_dttm DESC LIMIT 1;"
# 센서 갱신 주기
SELECT_SENSOR_REFRESH_INTERVAL_SQL   = "SELECT snsr_rfrs_itvl   FROM FARMHOUSE_M_INFO WHERE farm_id=%s AND hous_id=%s;"
# 현재 릴레이 상태값
SELECT_RELAY_STATUS_SQL              = "SELECT relay_1st_flag, relay_2st_flag, relay_3st_flag, relay_4st_flag, relay_5st_flag, relay_6st_flag, relay_7st_flag, relay_8st_flag, relay_9st_flag, relay_10st_flag, relay_11st_flag, relay_12st_flag, relay_13st_flag, relay_14st_flag, relay_15st_flag, relay_16st_flag FROM RELAY_L_RECORDING WHERE farm_id=%s AND hous_id=%s ORDER BY recd_dttm DESC LIMIT 1;"
