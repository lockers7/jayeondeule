# ════════════════════════════════════════════════════════════════════
# agri_ai_core 패키지 — 공통 유틸리티 재공개 + lazy db_session 로더.
# --->
# __getattr__ : 모듈 속성 lazy 로딩 — db_session 만 지연 import
# ════════════════════════════════════════════════════════════════════
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


# ────────────────────────────────────────────────────────────────────
# 모듈 속성 lazy 로딩 — db_session 은 첫 접근 시점에만 import 하여
# 패키지 초기화 시 PostgreSQL 의존성을 강제 로드하지 않는다.
# ────────────────────────────────────────────────────────────────────
def __getattr__(name):
    if name == "db_session":
        from agri_ai_core.src.postgresql import db_session
        return db_session
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
