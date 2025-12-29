# 릴레이 모듈과 관련된 라즈베리파이 핀 번호 설정
RELAY_GPIO = [0, 5, 6, 13, 19, 26, 23, 24, 25, 16, 20, 21, 17, 27, 22]
CHILLER_1_GPIO       = 0 # 수온히터1
CYCLE_MOTOR_GPIO     = 1 # 물순환모터
RADIATOR_GPIO        = 2 # 라디에이터 
CHILLER_2_GPIO       = 3 # 수온히터2
LIGHT_GPIO           = 4 # 조명
WATER_GPIO           = 5 # 관수
IN_FAN_GPIO          = 6 # 흡입환풍모터 
OUT_FAN_GPIO         = 7 # 배출환풍모터
CYCLE_VALVE_ON_GPIO  = 8 # 공기순환밸브
IN_VALVE_ON_GPIO     = 9 # 공기흡입밸브 
OUT_VALVE_ON_GPIO    = 10 # 공기배출밸브
WATER_VALVE_GPIO     = 11 # 배수모터
CYCLE_VALVE_OFF_GPIO = 12 
IN_VALVE_OFF_GPIO    = 13
OUT_VALVE_OFF_GPIO   = 14

RELAY_NAMES = {
    "relay_1st_flag": "수온히터1",  
    "relay_2st_flag": "물순환모터",
    "relay_3st_flag": "라디에이터",
    "relay_4st_flag": "수온히터2",
    "relay_5st_flag": "조명",
    "relay_6st_flag": "관수",
    "relay_7st_flag": "흡입환풍모터",
    "relay_8st_flag": "배출환풍모터",
    "relay_9st_flag": "공기순환밸브",
    "relay_10st_flag": "공기흡입밸브",
    "relay_11st_flag": "공기배출밸브",
    "relay_12st_flag": "배수모터",   
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