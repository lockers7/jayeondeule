#-----------------------------------------------------------------------
# 릴레이 모듈과 관련된 라즈베리파이 핀 번호 설정 (1호/3호 STANDARD)
#-----------------------------------------------------------------------
# [변경3 · 2026-04-19] 모든 장비명을 웹 UI(RelayDashboard) 라벨 기준으로 통일
#   웹 라벨: 수온히터(1) 포그생성(2) 배수밸브(3) 흡입팬(5) 배출팬(6)
#           조명(7) 관수(8) 실내히터(9) 순환밸브(10)
#           배출밸브(11) 흡입밸브(14) 히터밸브(15)
#   원복: ./gpio_config.py.changeBak_3 사용
#-----------------------------------------------------------------------
# RELAY_GPIO = [22, 23, 9, 25, 11, 8, 5, 7, 6, 12, 13, 16, 19, 20, 26, 21]
#              0,  1, 2,  3,  4, 5, 6, 7, 8, 9,  10, 11, 12, 13, 14, 15
RELAY_GPIO = [22, 23, 9, 25, 11, 8, 5, 7, 6, 12, 13, 16, 19, 20, 26, 21]
CHILLER_GPIO         = 0   # 수온히터   (relay_1, 기존: 물가열기)
CYCLE_MOTOR_GPIO     = 1   # 포그생성   (relay_2, 기존: 분사펌프/순환모터)
RELEASE_WATER_GPIO_1 = 2   # 배수밸브   (relay_3, 기존: 배수펌프)
RELEASE_WATER_GPIO_2 = 3   # 미사용     (relay_4)
IN_FAN_MOTOR_GPIO    = 4   # 흡입팬     (relay_5, 기존: 흡기팬)
OUT_FAN_MOTOR_GPIO   = 5   # 배출팬     (relay_6, 기존: 배기팬)
LIGHT_GPIO           = 6   # 조명       (relay_7, 기존: 조명토글)
WATER_GPIO           = 7   # 관수       (relay_8, 기존: 관수토글)
HEATER_GPIO          = 8   # 실내히터   (relay_9, 기존: 열풍기)
CYCLE_VALVE_ON_GPIO  = 9   # 순환밸브   (relay_10)
IN_VALVE_ON_GPIO     = 10  # 배출밸브   (relay_11, 변경2에서 14↔11 교환)
DUMMY1               = 11  # 미사용     (relay_12)
DUMMY2               = 12  # 미사용     (relay_13)
OUT_VALVE_ON_GPIO    = 13  # 흡입밸브   (relay_14, 변경2에서 14↔11 교환)
HEATER_VALVE_ON_GPIO = 14  # 히터밸브   (relay_15)
DUMMY3               = 15  # 미사용     (relay_16)

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
    "relay_11st_flag": "배출밸브",   # [변경2] 웹/현장 배선 기준 14와 교환
    "relay_12st_flag": "미사용",
    "relay_13st_flag": "미사용",
    "relay_14st_flag": "흡입밸브",   # [변경2] 웹/현장 배선 기준 11과 교환
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
