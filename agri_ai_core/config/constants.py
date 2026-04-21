# ════════════════════════════════════════════════════════════════════
# 상수 모듈 — 시스템 전역 상수, 임계값, 스케줄링 설정, Ollama/모델 헬퍼.
# --->
# get_ollama_url   : Ollama API URL 반환 (설정 > 환경변수 > 기본값 우선순위)
# get_model_name   : LLM 메인 모델명 반환 (.env 직접 read > 환경변수 > 설정 > 기본값)
# get_vision_model : 비전 LLM 모델명 — 메인이 비전 지원하면 메인과 동일 모델 반환
#                    (swap 회피·단일화), 미지원 시 VISION_MODEL fallback.
#                    "LLM 변경 시에도 동일 처리" 프레임워크의 핵심 헬퍼.
# ════════════════════════════════════════════════════════════════════
import os
from .settings import settings

CHROMA_EMBEDDING_DIM = 1024
EMBEDDING_MODEL_NAME = "bge-m3"

# 스케줄링 설정
STATS_INTERVAL_MINUTES = 10
AI_CONTROL_LOOP_DELAY_SEC = 60    # AI 순환 제어: 재배사 간 대기 시간(초). [변경12 · 2026-04-30] 10→60: ollama 큐 점유율 완화로 사용자 채팅이 끼어들 여유 확보. 환경 변화는 분 단위라 충분.
TRAINING_SCHEDULE_TIME = ["09:00", "21:00"]
NUM_PREDICT = 8192   # LLM 응답 최대 토큰 (A4 ~5장, RAG 요약/삭제/릴레이 제어 충분)
NUM_PREDICT_REWRITE = 2048
NUM_CTX = 16384      # 컨텍스트 윈도우 (고정: GPU 100% 유지, CPU 오프로딩 방지)
NUM_PREDICT_TOOL_CALL = 512  # 도구 호출 반복 시 출력 제한 (도구 JSON만 생성)

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


# ────────────────────────────────────────────────────────────────────
# Ollama API URL 반환 — settings.model.ollama_url > OLLAMA_URL > 기본값.
# ────────────────────────────────────────────────────────────────────
def get_ollama_url() -> str:
    return (
        getattr(settings.model, "ollama_url", None)
        or os.getenv("OLLAMA_URL")
        or "http://localhost:11434"
    )


# ────────────────────────────────────────────────────────────────────
# LLM 모델명 반환 — .env 파일 직접 read > 환경변수 > 설정 > 기본값.
# [변경9 · 2026-04-30] FastAPI change_model API 가 .env 만 수정하면 Scheduler
# 등 다른 프로세스도 다음 호출 시 자동으로 새 모델명을 반영하도록 .env 직접 read.
# mtime 기반 캐시로 IO 부담 최소화 — 파일 수정 시에만 재파싱.
# ────────────────────────────────────────────────────────────────────
_MODEL_NAME_CACHE = {'value': None, 'mtime': 0.0}


def get_model_name() -> str:
    env_path = os.path.join(
        os.environ.get('AGRI_PROJECT_ROOT', '/workspace/jayeondeule'), '.env'
    )
    try:
        mtime = os.path.getmtime(env_path)
        if _MODEL_NAME_CACHE['value'] is None or mtime > _MODEL_NAME_CACHE['mtime']:
            parsed = None
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    if s.startswith('MODEL_NAME='):
                        parsed = s.split('=', 1)[1].strip().strip('"').strip("'")
                        break
            if parsed:
                _MODEL_NAME_CACHE['mtime'] = mtime
                _MODEL_NAME_CACHE['value'] = parsed
                return parsed
    except OSError:
        pass

    if _MODEL_NAME_CACHE['value']:
        return _MODEL_NAME_CACHE['value']

    return (
        os.getenv("MODEL_NAME")
        or os.getenv("LLM_MODEL_NAME")
        or getattr(settings.model, "name", None)
        or "qwen3:32b"
    )


# ────────────────────────────────────────────────────────────────────
# 비전 LLM 모델명 반환.
# 동조 원칙: 메인 모델이 비전을 지원하면 메인과 동일 모델 사용 →
#   ① GPU 두 모델 동시 상주 시도 회피 (swap 비용 0)
#   ② 사용자가 웹에서 모델 선택 시 비전도 자동 동조 → 단일화 ✓
# 메인이 비전 미지원이면 VISION_MODEL 환경변수의 fallback 사용
# (미설정 시 빈 문자열 → 호출 측에서 비전 스킵).
# ────────────────────────────────────────────────────────────────────
def get_vision_model() -> str:
    from .model_capabilities import supports_vision
    main = get_model_name()
    if main and supports_vision(main):
        return main
    return os.getenv("VISION_MODEL", "").strip()
