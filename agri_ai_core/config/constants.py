# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 상수 모듈
# 시스템 전역 상수, 임계값, 스케줄링 설정
# --->
# get_ollama_url: Ollama API URL 반환 (설정 > 환경변수 > 기본값 우선순위)
# get_model_name: LLM 모델명 반환 (설정 > 환경변수 > 기본값 우선순위)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

import os
from .settings import settings

CHROMA_EMBEDDING_DIM = 1024
EMBEDDING_MODEL_NAME = "bge-m3"

# 스케줄링 설정
STATS_INTERVAL_MINUTES = 10
AI_CONTROL_LOOP_DELAY_SEC = 30    # AI 순환 제어: 재배사 간 대기 시간(초)
TRAINING_SCHEDULE_TIME = ["09:00", "21:00"]
NUM_PREDICT = 3072
NUM_PREDICT_REWRITE = 1536

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

# 릴레이 키 목록
RELAY_KEYS = [
    'relay_1st_flag', 'relay_2st_flag', 'relay_3st_flag', 'relay_4st_flag',
    'relay_5st_flag', 'relay_6st_flag', 'relay_7st_flag', 'relay_8st_flag',
    'relay_9st_flag', 'relay_10st_flag', 'relay_11st_flag', 'relay_12st_flag',
    'relay_13st_flag', 'relay_14st_flag', 'relay_15st_flag', 'relay_16st_flag'
]


# ============================================================
# Ollama API URL 반환 (설정 > 환경변수 > 기본값 우선순위)
# ============================================================
def get_ollama_url() -> str:
    return (
        getattr(settings.model, "ollama_url", None)
        or os.getenv("OLLAMA_URL")
        or "http://localhost:11434"
    )


# ============================================================
# LLM 모델명 반환 (환경변수 > 설정 > 기본값 우선순위)
# 런타임 모델 변경을 즉시 반영하기 위해 os.environ을 최우선으로 읽는다.
# ============================================================
def get_model_name() -> str:
    return (
        os.getenv("MODEL_NAME")
        or os.getenv("LLM_MODEL_NAME")
        or getattr(settings.model, "name", None)
        or "qwen3:32b"
    )
