# 릴레이 모듈과 관련된 라즈베리파이 핀 번호 설정 (2호 E타입)
# ══════════════════════════════════════════════════════════════════════════════
# [변경1 · 2026-04-19] 2호 전용 +1 shift — 웹 UI/DB 컬럼 번호와 장비 의미 일치화
# [변경3 · 2026-04-19] 모든 장비명을 웹 UI(RelayDashboard) 라벨 기준으로 통일
#   웹 라벨: 칠러Ⅰ(1) 포그생성(2) 라디에이터(3) 칠러Ⅱ(4) 조명(5) 관수(6)
#           흡입팬(7) 배출팬(8) 순환밸브(10)
#           흡입밸브(11) 배출밸브(12) 배수밸브(13)
#   원복: ./gpio_config.py.changeBak_1 / .changeBak_3 사용
# ══════════════════════════════════════════════════════════════════════════════
RELAY_GPIO = [0, 5, 6, 13, 19, 26, 23, 24, None, 25, 16, 20, 21, 17, 27, 22]
CHILLER_1_GPIO       = 0   # 칠러Ⅰ     (relay_1,  기존: 물가열기1)
CYCLE_MOTOR_GPIO     = 1   # 포그생성   (relay_2,  기존: 분사펌프)
RADIATOR_GPIO        = 2   # 라디에이터 (relay_3)
CHILLER_2_GPIO       = 3   # 칠러Ⅱ     (relay_4,  기존: 물가열기2)
LIGHT_GPIO           = 4   # 조명       (relay_5)
WATER_GPIO           = 5   # 관수       (relay_6,  기존: 관수밸브)
IN_FAN_GPIO          = 6   # 흡입팬     (relay_7,  기존: 흡기팬)
OUT_FAN_GPIO         = 7   # 배출팬     (relay_8,  기존: 배기팬)
DUMMY_RELAY_9        = 8   # 미사용     (relay_9,  [변경1] shift로 비워짐)
CYCLE_VALVE_ON_GPIO  = 9   # 순환밸브   (relay_10)
IN_VALVE_ON_GPIO     = 10  # 흡입밸브   (relay_11)
OUT_VALVE_ON_GPIO    = 11  # 배출밸브   (relay_12)
WATER_VALVE_GPIO     = 12  # 배수밸브   (relay_13, [변경1])
CYCLE_VALVE_OFF_GPIO = 13  #              (relay_14)
IN_VALVE_OFF_GPIO    = 14  #              (relay_15)
OUT_VALVE_OFF_GPIO   = 15  #              (relay_16)

RELAY_NAMES = {
    "relay_1st_flag":  "칠러Ⅰ",
    "relay_2st_flag":  "포그생성",
    "relay_3st_flag":  "라디에이터",
    "relay_4st_flag":  "칠러Ⅱ",
    "relay_5st_flag":  "조명",
    "relay_6st_flag":  "관수",
    "relay_7st_flag":  "흡입팬",
    "relay_8st_flag":  "배출팬",
    "relay_9st_flag":  "미사용",      # [변경1] +1 shift dummy
    "relay_10st_flag": "순환밸브",
    "relay_11st_flag": "흡입밸브",
    "relay_12st_flag": "배출밸브",
    "relay_13st_flag": "배수밸브",
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

#----------------------------------------------
# 빛과 수위 측정용 GPIO 번호
# 2호재배사는 해당 센서 미장착 → None으로 표시 (gpio_control에서 가드)
#----------------------------------------------
LIGHT_LEVEL_SENSOR_GPIO = None
WATER_LEVEL_SENSOR_GPIO = None
