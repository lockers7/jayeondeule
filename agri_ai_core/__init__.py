__version__ = "1.0.0"
__author__ = "AgriAI Team"

# 공통 모듈 exports (기본 유틸리티만)
from agri_ai_core.config import settings, get_settings
from agri_ai_core.src.logs import setup_logger

__all__ = [
    # 설정 및 유틸리티
    "settings",
    "get_settings",
    "setup_logger",
    # 엔트리포인트 (지연 로드)
    "db_session",
    "run_streamlit",
]


# 지연 로드 함수들 (순환 import 방지)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Lazy import for modules that may cause circular imports
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def __getattr__(name):
    if name == "db_session":
        from agri_ai_core.src.postgresql import db_session
        return db_session
    if name == "run_streamlit":
        from agri_ai_core.src.ui.main import main
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
