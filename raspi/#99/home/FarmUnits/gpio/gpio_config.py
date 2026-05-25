#-----------------------------------------------------------------------
#              0,  1, 2,  3,  4, 5, 6, 7, 8, 9,  10, 11, 12, 13, 14, 15
RELAY_GPIO = [22, 23, 9, 25, 11, 8, 7, 5, 6, 12, 13, 19, 16, 26, 20, 21]
CHILLER_GPIO         = 0   # 수온히터
CYCLE_MOTOR_GPIO     = 1   # 포그생성
RELEASE_WATER_GPIO_1 = 2   # 배수밸브
RELEASE_WATER_GPIO_2 = 3   # 미사용
IN_FAN_MOTOR_GPIO    = 4   # 흡입팬
OUT_FAN_MOTOR_GPIO   = 5   # 배출팬
LIGHT_GPIO           = 6   # 조명
WATER_GPIO           = 7   # 관수
HEATER_GPIO          = 8   # 실내히터
CYCLE_VALVE_ON_GPIO  = 9   # 순환밸브
IN_VALVE_ON_GPIO     = 10  # 배출밸브
DUMMY1               = 11  # 미사용
DUMMY2               = 12  # 미사용
OUT_VALVE_ON_GPIO    = 13  # 흡입밸브
HEATER_VALVE_ON_GPIO = 14  # 히터밸브
DUMMY3               = 15  # 미사용

RELAY_NAMES = {
    "relay_1st_flag":  "수온히터",
    "relay_2st_flag":  "포그생성",
    "relay_3st_flag":  "배수밸브",
    "relay_4st_flag":  "미사용",
    "relay_5st_flag":  "흡입팬",
    "relay_6st_flag":  "배출팬",
    "relay_7st_flag":  "조명",
    "relay_8st_flag":  "관수",
    "relay_9st_flag":  "실내히터",
    "relay_10st_flag": "순환밸브",
    "relay_11st_flag": "배출밸브",
    "relay_12st_flag": "미사용",
    "relay_13st_flag": "미사용",
    "relay_14st_flag": "흡입밸브",
    "relay_15st_flag": "히터밸브",
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
