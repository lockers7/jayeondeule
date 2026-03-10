# 릴레이 모듈과 관련된 라즈베리파이 핀 번호 설정
RELAY_GPIO = [0, 5, 6, 13, 19, 26, 23, 24, 25, 16, 20, 21, 17, 27, 22, 12]
CHILLER_1_GPIO       = 0 # 물가열기
CYCLE_MOTOR_GPIO     = 1 # 분사펌프
RADIATOR_GPIO        = 2 # 라디에이터 
CHILLER_2_GPIO       = 3 # 미사용
LIGHT_GPIO           = 4 # 조명
WATER_GPIO           = 5 # 관수밸브
IN_FAN_GPIO          = 6 # 흡기팬 
OUT_FAN_GPIO         = 7 # 배기팬
CYCLE_VALVE_ON_GPIO  = 8 # 순환댐퍼
IN_VALVE_ON_GPIO     = 9 # 흡기댐퍼 
OUT_VALVE_ON_GPIO    = 10 # 배기댐퍼
WATER_VALVE_GPIO     = 11 # 배수밸브
CYCLE_VALVE_OFF_GPIO = 12 # 미사용
IN_VALVE_OFF_GPIO    = 13 # 미사용
OUT_VALVE_OFF_GPIO   = 14 # 미사용
OUT_VALVE_OFF_GPIO   = 15 # 미사용

RELAY_NAMES = {
    "relay_1st_flag": "물가열기",  
    "relay_2st_flag": "분사펌프",
    "relay_3st_flag": "라디에이터",
    "relay_4st_flag": "미사용",
    "relay_5st_flag": "조명",
    "relay_6st_flag": "관수밸브",
    "relay_7st_flag": "흡기팬",
    "relay_8st_flag": "배기팬",
    "relay_9st_flag": "순환댐퍼",
    "relay_10st_flag": "흡기댐퍼",
    "relay_11st_flag": "배기댐퍼",
    "relay_12st_flag": "배수밸브",   
    "relay_13st_flag": "미사용",
    "relay_14st_flag": "미사용",
    "relay_15st_flag": "미사용",
    "relay_16st_flag": "미사용",
}

# 제어를 위한 릴레이 갯수
USING_RELAY_CNT = len(RELAY_GPIO)

# 밸브 릴레이 상대편 제어 인터벌
RELAY_DELAY_INTERVAL = 0.5

# 밸브 릴레이 상대편 릴에이 갭
RELAY_OTHER_SIDE_GAP = 4