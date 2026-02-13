# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 앱 엔트리 포인트
# rxconfig.py의 app_name과 일치하는 구조 제공
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import sys

# gunicorn/reflex 실행 시 cwd에 따라 프로젝트 루트가 sys.path에 없을 수 있으므로 보정
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from agri_ai_core.src.ui_reflex.main import app
except ModuleNotFoundError as import_error:
    # agri_ai_core 패키지 자체가 안 잡히는 실행 컨텍스트에서만 fallback
    if getattr(import_error, "name", "") != "agri_ai_core":
        raise
    from src.ui_reflex.main import app

__all__ = ["app"]
