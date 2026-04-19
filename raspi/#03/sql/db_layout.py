#===============================================================================================================
# 테이블 키 정의
#---------------------------------------------------------------------------------------------------------------
primary_keys = {
    "FARM_M_INFO"         : ["farm_id", ],
    "USER_M_INFO"         : ["farm_id", "user_id", ],
    "FARMHOUSE_M_INFO"    : ["farm_id", "hous_id", ],
    "FARMHOUSE_L_PRODUCT" : ["farm_id", "hous_id", "recd_dttm", ],
    "SENSOR_M_SETTING"    : ["farm_id", "hous_id", "setn_dttm", ],
    "SENSOR_L_RECORDING"  : ["farm_id", "hous_id", "recd_dttm", ],
    "RELAY_L_RECORDING"   : ["farm_id", "hous_id", "recd_dttm", ],
}

#===============================================================================================================
# 개별 테이블 정의 
#---------------------------------------------------------------------------------------------------------------
# 각 컬럼 #옆 문자 범례 : +: 컬럼추가, =: 유지, C 컬럼명 변경
# 변경 공통 : id 삭제 
# farm_id를 Primary Key로 변경 - 농장 고유번호
# farm에 user_id 복수 관리
# farm에 farmhouse 복수 관리
#===============================================================================================================

#---------------------------------------------------------------------------------------------------------------
# 농장 기본 정보
#---------------
# farm -> FARM_M_INFO
#---------------------------------------------------------------------------------------------------------------
FARM_M_INFO = {
    "farm_id"            : 0,                #=    
    "farm_name"          : 0,                #C   name
    "farm_domi"          : '',               #+   농장 도메인(ID)
    "open_date"          : '',               #+   개시일자 (YYYY/MM/DD)
    "clse_date"          : '',               #+   폐쇄일자 (YYYY/MM/DD)
    "tel_no"             : '',               #+  
    "hp_no"              : '',               #+
    "fax_no"             : '',               #+
    "mail"               : '',               #+
    "ip_addr"            : '',               #C   ip
    "port"               : '',               #+
    "region"             : '',               #+   지역(코드)
    "addr"               : '',               #C   address
    "main_prdt"          : '',               #+   주요 재배배 작물(코드)
    "rmks"               : '',               #C   descr
    "rgst_dttm"          : '',               #+   등록일시 (YYYY/MM/DD HH:MM:SS)
}

#---------------------------------------------------------------------------------------------------------------
# 농장사용자 정보 
#---------------
# user_info -> USER_M_INFO
# call2 삭제
#---------------------------------------------------------------------------------------------------------------
USER_M_INFO ={
    "farm_id"            : 0,                #=      
    "user_id"            : '',               #=
    "passwd"             : '',               #C   password
    "user_name"          : '',               #C   name
    "auth_levl"          : '',               #C   authority(코드)
    "hp_no"              : '',               #C   call1
    "pstn"               : '',               #+   직위(주로 농장 주 1명) (코드)
    "rgst_dttm"          : '',               #+   등록일시 (YYYY/MM/DD HH:MM:SS)
}

#---------------------------------------------------------------------------------------------------------------
# 재배사 정보 
#------------
# farm_status -> FARMHOUSE_M_INFO
#---------------------------------------------------------------------------------------------------------------
FARMHOUSE_M_INFO = {
    "farm_id"            : 0,                #=
    "hous_id"            : 0,                #+   재배사 ID
    "mnul_ctrl_flag"     : True,             #C   manual_control_flag
    "page_rfrs_itvl"     : 0,                #C   page_refresh_interval
    "rfrs_flag"          : True,             #C   refresh_flag  
    "snsr_rfrs_itvl"     : 0,                #C   sensor_refresh_interval
    "prdt_kind"          : '',               #+   재배 작물(코드드)
    "rgst_dttm"          : '',               #+   등록일시 (YYYY/MM/DD HH:MM:SS)
} 

#---------------------------------------------------------------------------------------------------------------
# 재배사 재배 기록 관리 
#---------------------
# farm_memo -> FARMHOUSE_L_PRODUCT
#---------------------------------------------------------------------------------------------------------------
FARMHOUSE_L_PRODUCT = {
    "farm_id"            : 0,                #=
    "hous_id"            : 0,                #+
    "recd_dttm"          : '',               #C   recd_date
    "prdt_strt_date"     : '',               #+   생산시작일(YYYY/MM/DD)
    "prdt_end_date"      : '',               #+   생산종일(YYYY/MM/DD)
    "prdt_status"        : '',               #+   재배상태태
    "prdt_qtty"          : 0.0,              #+   총생산량
    "prdt_gred_qtty_0"   : 0.0,              #+   0등급생산량
    "prdt_gred_qtty_1"   : 0.0,              #+   1등급생산량
    "prdt_gred_qtty_2"   : 0.0,              #+   2등급생산량
    "prdt_gred_qtty_3"   : 0.0,              #+   3등급생산량
    "prdt_gred_qtty_4"   : 0.0,              #+   4등급생산량
    "prdt_gred_qtty_5"   : 0.0,              #+   5등급생산량
    "prdt_gred_qtty_6"   : 0.0,              #+   6등급생산량
    "prdt_gred_qtty_7"   : 0.0,              #+   7등급생산량
    "prdt_gred_qtty_8"   : 0.0,              #+   8등급생산량
    "prdt_gred_qtty_9"   : 0.0,              #+   9등급생산량
    "rmks"               : '',               #C   memo
    "file_name"          : '',               #+   파일명
    "file_size"          : 0,                #+   파일사이즈
    "file_imge"          :''                 #+   파일이미지
}

#---------------------------------------------------------------------------------------------------------------
# 재배사 각 기본 센서값 셋팅 
#--------------------------
# farm_generic_setting -> SENSOR_M_SETTING
#---------------------------------------------------------------------------------------------------------------
SENSOR_M_SETTING = {
    "farm_id"            : 0,                #=   
    "hous_id"            : 0,                #+   재배사 ID
    "setn_dttm"          : '',               #C   appl_date
    "tprt_min"           : 0.0,              #C   temp_min
    "tprt_max"           : 0.0,              #C   temp_max
    "hmdt_min"           : 0.0,              #C   humi_min
    "hmdt_max"           : 0.0,              #C   humi_max
    "co2_min"            : 0.0,              #C   co2min
    "co2_max"            : 0.0,              #C   co2max
    "watr_tprt_min"      : 0.0,              #C   water_temp_min
    "watr_tprt_max"      : 0.0,              #C   water_temp_max
    "heat_tprt_min"      : 0.0,              #+   열풍기 최저
    "heat_tprt_max"      : 0.0,              #+   열풍기 최고
}

#---------------------------------------------------------------------------------------------------------------
# 조명, 관수 시간 셋팅 
#--------------------
# farm_water_light_setting -> LIGHT_IRRIGATION_S_SETTING
#---------------------------------------------------------------------------------------------------------------
LIGHT_IRRIGATION_S_SETTING = {
    "farm_id"            : 0,                #=
    "hous_id"            : 0,                #+   재배사 ID
    "setn_dttm"          : '',               #C   appl_date
    "dlte_yn"            : True,             #C   deeleted
    "unit_type"          : '',               #C   type
    "strt_time"          : '',               #C   fr_time (HH:MM:SS)
    "fnsh_time"          : '',               #C   to_time (HH:MM:SS)
    "excs_type"          : 'daily',          #+   실행유형: daily, interval, weekdays
    "excs_itvl"          : None,             #+   N일마다 실행 간격
    "excs_strt_date"     : None,             #+   주기 시작일
    "excs_wkdy"          : None,             #+   실행 요일 (1,3,5 = 월/수/금)
}

#---------------------------------------------------------------------------------------------------------------
# 각센서 동작 기록 원장 
#---------------------
# farm_sensor_recd -> SENSOR_L_RECORDING
#---------------------------------------------------------------------------------------------------------------
SENSOR_L_RECORDING = {
    "farm_id"            : 0,                #=
    "hous_id"            : 0,                #+   재배사 ID
    "recd_dttm"          : '',               #C   recd_date 기록일시(YYYY/MM/DD HH:MM:SS)
    "indr_tprt_valu"     : 0.0,              #C   temp_val 
    "indr_hmdt_valu"     : 0.0,              #C   humi_val 
    "oudr_tprt_valu"     : 0.0,              #C   외부온도 
    "oudr_hmdt_valu"     : 0.0,              #+   외부습도 
    "co2_valu"           : 0.0,              #C   co2val 
    "watr_tprt_valu"     : 0.0,              #C   water_temp_val
    "ligt_level_valu"    : 0.0,              #+   조도
    "watr_level_valu"    : 0.0,              #+   수위
} 

#---------------------------------------------------------------------------------------------------------------
# 릴레이 동작 기록 원장 
#---------------------
# farm_relay_status -> RELAY_L_RECORDING
#---------------------------------------------------------------------------------------------------------------
RELAY_L_RECORDING = {
    "farm_id"            : 0,                #=
    "hous_id"            : 0,                #+   재배사 ID
    "recd_dttm"          : '',               #C   recd_date 기록일시(YYYY/MM/DD HH:MM:SS)
    "relay_1st_flag"     : True,             #C   <- relay_1st 
    "relay_2st_flag"     : True,             #C   <- relay_2st 
    "relay_3st_flag"     : True,             #C   <- relay_3st 
    "relay_4st_flag"     : True,             #C   <- relay_4st 
    "relay_5st_flag"     : True,             #C   <- relay_5st 
    "relay_6st_flag"     : True,             #C   <- relay_6st 
    "relay_7st_flag"     : True,             #C   <- relay_7st 
    "relay_8st_flag"     : True,             #C   <- relay_8st 
    "relay_9st_flag"     : True,             #C   <- relay_9st 
    "relay_10st_flag"    : True,             #C   <- relay_10st 
    "relay_11st_flag"    : True,             #C   <- relay_11st 
    "relay_12st_flag"    : True,             #C   <- relay_12st 
    "relay_13st_flag"    : True,             #C   <- relay_13st 
    "relay_14st_flag"    : True,             #C   <- relay_14st 
    "relay_15st_flag"    : True,             #C   <- relay_15st 
    "relay_16st_flag"    : True,             #+   <- relay_16st 
}

#---------------------------------------------------------------------------------------------------------------
# 모든 코드 정의
#---------------
# New :  CODE_M_MASTER
#---------------------------------------------------------------------------------------------------------------
CODE_M_MASTER = {
    "code_id"            : '',               #+   코드종류 : 코드적용 필드명
    "code_item"          : 0,                #+   종류코드 : 5
    "code_sqtl"          : 0,                #+   코드출력 순번
    "code_name"          : '',               #+   코드명 
    "rmks"               : '',               #+   코드설명 
} 