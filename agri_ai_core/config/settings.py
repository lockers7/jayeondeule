# ════════════════════════════════════════════════════════════════════
# 설정 모듈 — 환경변수 기반 애플리케이션 설정 로드.
# dataclass(frozen) + lru_cache 싱글톤으로 불변성 + 1회 로드 보장.
# --->
# _get_int       : Optional[str] → Optional[int] 안전 변환
# _get_first_env : 다중 키 중 처음으로 발견된 환경변수 값 반환
# get_settings   : .env 로드 후 AppSettings 인스턴스 생성 (lru_cache)
# ════════════════════════════════════════════════════════════════════
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv

# 순환 참조 방지: logs.py가 settings를 참조하므로 여기서는 표준 logging 사용
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class VectorStoreSettings:
    client_type: str
    backend: Optional[str]
    db_path: Optional[str]
    http_host: Optional[str]
    http_port: Optional[int]


@dataclass(frozen=True)
class ModelSettings:
    name: str
    prefix: Optional[str]
    units_name: Optional[str]
    ollama_url: Optional[str]
    embedding_model: Optional[str]
    use_dummy_embedding: bool


@dataclass(frozen=True)
class CollectionSettings:
    farm_knowledge: Optional[str]
    document: Optional[str]
    conversation: Optional[str]
    web_knowledge: Optional[str]
    prompt_chunk: Optional[str]   # [프롬프트 자동화] 시스템/유저/분석/답변 프롬프트 chunk
    domain_rule: Optional[str]    # [프롬프트 자동화] 결합 규칙·안전 룰·사용자 학습 룰


@dataclass(frozen=True)
class LoggingSettings:
    path: Optional[str]
    level: Optional[str]


@dataclass(frozen=True)
class AppSettings:
    corps_name: Optional[str]
    embedding_dim: int
    database: DatabaseSettings
    vector: VectorStoreSettings
    model: ModelSettings
    collections: CollectionSettings
    logging: LoggingSettings


# ────────────────────────────────────────────────────────────────────
# Optional[str] → Optional[int] 안전 변환 — None/빈/비숫자 시 default 반환.
# ────────────────────────────────────────────────────────────────────
def _get_int(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ────────────────────────────────────────────────────────────────────
# 다중 환경변수 키 중 처음으로 발견된(non-empty) 값을 반환.
# 신·구 키 호환(PGDB_HOST/DB_HOST 등) 처리에 사용.
# ────────────────────────────────────────────────────────────────────
def _get_first_env(*keys: str, default: Optional[str] = None) -> Optional[str]:
    for key in keys:
        value = os.getenv(key)
        if value is not None and value != "":
            return value
    return default


# ────────────────────────────────────────────────────────────────────
# .env 로드 후 AppSettings 인스턴스 생성 — lru_cache 로 1회만 실행.
# DB/Vector/Model/Collection/Logging 5개 sub-settings 를 합성하여 반환.
# ────────────────────────────────────────────────────────────────────
@lru_cache()
def get_settings() -> AppSettings:
    load_dotenv(override=True)

    database = DatabaseSettings(
        host=_get_first_env("PGDB_HOST", "DB_HOST", default="127.0.0.1"),
        port=_get_int(_get_first_env("PGDB_PORT", "DB_PORT"), 5432),
        database=_get_first_env("PGDB_DATABASE", "DB_NAME", default=""),
        user=_get_first_env("PGDB_USER", "DB_USER", default=""),
        password=_get_first_env("PGDB_PASSWORD", "DB_PASSWORD", default=""),
    )

    vector = VectorStoreSettings(
        client_type=os.getenv("CLIENT_TYPE", ""),
        backend=_get_first_env("CHROMADB_BACKEND", "CHROMA_DB_IMPL"),
        db_path=os.getenv("CHROMA_DB_PATH"),
        http_host=_get_first_env("CHROMA_DB_HTTP_HOST", "CHROMA_HOST"),
        http_port=_get_int(_get_first_env("CHROMA_DB_HTTP_PORT", "CHROMA_PORT")),
    )

    model = ModelSettings(
        name=os.getenv("MODEL_NAME", ""),
        prefix=os.getenv("MODEL_PREFIX"),
        units_name=os.getenv("UNITS_NAME"),
        ollama_url=_get_first_env("OLLAMA_URL", "OLLAMA_HOST"),
        embedding_model=os.getenv("EMBEDDING_MODEL_NAME"),
        use_dummy_embedding=(
            str(_get_first_env("USE_DUMMY_EMBEDDING", default="false")).lower()
            in {"1", "true", "yes", "y"}
        ),
    )

    collections = CollectionSettings(
        farm_knowledge=os.getenv("COLLECTION_FARM_KNOWLEDGE"),
        document=os.getenv("COLLECTION_DOCUMENT"),
        conversation=os.getenv("COLLECTION_CONVERSATION"),
        web_knowledge=os.getenv("COLLECTION_WEB_KNOWLEDGE"),
        prompt_chunk=os.getenv("COLLECTION_PROMPT_CHUNK", "prompt_chunk"),
        domain_rule=os.getenv("COLLECTION_DOMAIN_RULE", "domain_rule"),
    )

    logging_settings = LoggingSettings(
        path=os.getenv("LOG_PATH"),
        level=os.getenv("LOG_LEVEL", "DEBUG"),
    )

    return AppSettings(
        corps_name=os.getenv("CORPS_NAME"),
        embedding_dim=_get_int(os.getenv("CHROMA_EMBEDDING_DIM"), 1024) or 1024,
        database=database,
        vector=vector,
        model=model,
        collections=collections,
        logging=logging_settings,
    )


# 전역 설정 인스턴스
settings = get_settings()
