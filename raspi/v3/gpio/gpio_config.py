#-----------------------------------------------------------------------
# 릴레이 모듈과 관련된 라즈베리파이 핀 번호 설정
#-----------------------------------------------------------------------
# RELAY_GPIO = [22, 23, 9, 25, 11, 8, 5, 7, 6, 12, 13, 16, 19, 20, 26, 21]
#              0,  1, 2,  3,  4, 5, 6, 7, 8, 9,  10, 11, 12, 13, 14, 15
RELAY_GPIO = [22, 23, 9, 25, 11, 8, 5, 7, 6, 12, 20, 16, 19, 13, 26, 21]
CHILLER_GPIO         = 0 
CYCLE_MOTOR_GPIO     = 1 
RELEASE_WATER_GPIO_1 = 2
RELEASE_WATER_GPIO_2 = 3
IN_FAN_MOTOR_GPIO    = 4 
OUT_FAN_MOTOR_GPIO   = 5 
LIGHT_GPIO           = 6 
WATER_GPIO           = 7 
HEATER_GPIO          = 8 
CYCLE_VALVE_ON_GPIO  = 9 
IN_VALVE_ON_GPIO     = 10 # OUT_VALVE_ON_GPIO
DUMMY1               = 11 
DUMMY2               = 12
OUT_VALVE_ON_GPIO    = 13 # IN_VALVE_ON_GPIO 위치를 서로 바꿈
HEATER_VALVE_ON_GPIO = 14
DUMMY3               = 15

RELAY_NAMES = {
    "relay_1st_flag": "수온히터",
    "relay_2st_flag": "물순환모터",
    "relay_3st_flag": "배수모터1",
    "relay_4st_flag": "미사용",
    "relay_5st_flag": "흡입환풍모터",
    "relay_6st_flag": "배출환풍모터",
    "relay_7st_flag": "조명",
    "relay_8st_flag": "관수",
    "relay_9st_flag": "실내히터",
    "relay_10st_flag": "공기순환밸브",
    "relay_11st_flag": "공기흡입밸브",
    "relay_12st_flag": "미사용",
    "relay_13st_flag": "미사용",
    "relay_14st_flag": "공기배출밸브",
    "relay_15st_flag": "실내히터밸브",
    "relay_16st_flag": "미사용",
}

#-----------------------
# 제어를 위한 릴레이 갯수
#-----------------------
USING_RELAY_CNT = len(RELAY_GPIO)

#----------------------------------------------
# 빛과 수위 측정용 GPIO 번호
#----------------------------------------------
LIGHT_LEVEL_SENSOR_GPIO = 17 
WATER_LEVEL_SENSOR_GPIO = 27
