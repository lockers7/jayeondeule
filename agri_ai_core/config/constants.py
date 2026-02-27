# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 상수 모듈
# 시스템 전역 상수, 임계값, 스케줄링 설정
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

import os
from .settings import settings

CHROMA_EMBEDDING_DIM = 1024
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL_NAME = "bge-m3"

# 데이터 제한 및 쿼리 설정
QUERY_SOURCE_CNT = 30
PROMPT_SOURCE_LIMIT = 10
PROMPT_LEARNED_LIMIT = 5
PROMPT_STATS_LIMIT = 5
PROMPT_OPTIMAL_LIMIT = 5
PROMPT_DOC_LIMIT = 5

# 제어 임계값
CONTROL_DEEP_LINE_THRESHOLD = 2000
CONTROL_CO2_THRESHOLD = 1300

# 스케줄링 설정
DATA_TRANSFER_MINUTES = 3
STATS_INTERVAL_MINUTES = 10
RELAY_SETTING_MINUTES = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
TRAINING_SCHEDULE_TIME = ["09:00", "21:00"]
DATA_TRAINING_HOURS = "4, 16"
NUM_PREDICT = 5120
NUM_PREDICT_REWRITE = 2048

# 생육 RAG 설정
GROWTH_RAG_HOURS = "0,12"
GROWTH_RAG_TTL_DAYS = 90
GROWTH_RAG_MOVING_AVG_WINDOW = 72

try:
    _default_learning_time = TRAINING_SCHEDULE_TIME[0]
    _learn_hour, _learn_minute = _default_learning_time.split(":")
    SCHEDULE_LEARNING_HOUR = int(_learn_hour)
    SCHEDULE_LEARNING_MINUTE = int(_learn_minute)
except (IndexError, ValueError, AttributeError, TypeError):
    SCHEDULE_LEARNING_HOUR = 4
    SCHEDULE_LEARNING_MINUTE = 0

# 모델 관련 설정
CORPS_NAME = settings.corps_name
MODEL_NAME = settings.model.name
MODEL_PREFIX = settings.model.prefix

# 릴레이 가동 조합
RELAY_COMBINATIONS = {
    "내부순환": {
        "air_circulation_valve_flag": True,
        "air_intake_valve_flag": False,
        "air_exhaust_valve_flag": False
    },
    "외부순환": {
        "air_circulation_valve_flag": False,
        "air_intake_valve_flag": True,
        "air_exhaust_valve_flag": True
    },
    "공기흡입": {
        "air_circulation_valve_flag": False,
        "air_intake_valve_flag": True,
        "air_exhaust_valve_flag": False
    },
    "공기배출": {
        "air_circulation_valve_flag": False,
        "air_intake_valve_flag": False,
        "air_exhaust_valve_flag": True
    }
}

# 생육환경 조정 추천
ENVIRONMENT_RECOMMENDATIONS = {
    "낮은온도": [
        {"relay": "water_heater_flag", "state": True, "reason": "물가열기를 가동하여 습도 조절용 물의 온도를 높여 내부온도 상승"},
        {"relay": "indoor_heater_flag", "state": True, "reason": "열풍기를 가동하여 직접적으로 내부온도 상승"}
    ],
    "높은온도_외부온도낮음": [
        {"relay": "air_circulation_valve_flag", "state": False, "reason": "내부 공기 순환 중지"},
        {"relay": "air_intake_valve_flag", "state": True, "reason": "외부의 차가운 공기 흡입"},
        {"relay": "air_exhaust_valve_flag", "state": True, "reason": "내부의 더운 공기 배출"}
    ],
    "높은온도_수온낮음": [
        {"relay": "fog_occurs_flag", "state": True, "reason": "차가운 물을 순환시켜 내부 온도 하강"},
        {"relay": "air_circulation_valve_flag", "state": False, "reason": "내부 공기 순환 중지"},
        {"relay": "air_intake_valve_flag", "state": True, "reason": "외부 공기 흡입"},
        {"relay": "air_exhaust_valve_flag", "state": True, "reason": "내부 공기 배출"}
    ],
    "낮은습도": [
        {"relay": "fog_occurs_flag", "state": True, "reason": "분사펌프 가동으로 포그 분사하여 습도 상승"},
        {"relay": "air_circulation_valve_flag", "state": True, "reason": "내부 공기 순환으로 습도 균일화"},
        {"relay": "air_intake_valve_flag", "state": False, "reason": "외부 공기 흡입 차단"},
        {"relay": "air_exhaust_valve_flag", "state": False, "reason": "내부 습도 유지를 위해 배출 차단"}
    ],
    "높은co2": [
        {"relay": "air_circulation_valve_flag", "state": False, "reason": "내부 공기 순환 중지"},
        {"relay": "air_intake_valve_flag", "state": True, "reason": "신선한 외부 공기 흡입"},
        {"relay": "air_exhaust_valve_flag", "state": True, "reason": "co2 농도가 높은 내부 공기 배출"}
    ],
    "낮은광량": [
        {"relay": "lighting_flag", "state": True, "reason": "조명토글 가동으로 내부 밝기 증가"}
    ],
    "높은수위": [
        {"relay": "drainage_motor_flag", "state": True, "reason": "배수밸브 가동으로 내부 물 배출"},
    ]
}

# 릴레이 키 목록
RELAY_KEYS = [
    'relay_1st_flag', 'relay_2st_flag', 'relay_3st_flag', 'relay_4st_flag',
    'relay_5st_flag', 'relay_6st_flag', 'relay_7st_flag', 'relay_8st_flag',
    'relay_9st_flag', 'relay_10st_flag', 'relay_11st_flag', 'relay_12st_flag',
    'relay_13st_flag', 'relay_14st_flag', 'relay_15st_flag', 'relay_16st_flag'
]


def get_ollama_url() -> str:
    """Ollama API URL 반환 (설정 > 환경변수 > 기본값 우선순위)"""
    return (
        getattr(settings.model, "ollama_url", None)
        or os.getenv("OLLAMA_URL")
        or "http://localhost:11434"
    )
