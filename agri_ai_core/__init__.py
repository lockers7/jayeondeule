__version__ = "1.0.0"
__author__ = "AgriAI Team"

# 공통 모듈 exports (기본 유틸리티만)
from agri_ai_core.config import settings, get_settings
from agri_ai_core.logs import setup_logger

__all__ = [
    "settings",
    "get_settings",
    "setup_logger",
    "db_session",
]


def __getattr__(name):
    if name == "db_session":
        from agri_ai_core.src.postgresql import db_session
        return db_session
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
