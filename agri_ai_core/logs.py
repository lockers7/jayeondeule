# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Unified Logging Module
# 로그 설정 및 핸들러 관리
# 원래 파일: log_utils/log_config.py + log_utils/log_handlers.py
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import sys
import logging
from datetime import datetime

from agri_ai_core.config import settings

# 초기화된 로거 캐시
_loggers_initialized = {}


# ============================================================
# LOG CONFIGURATION CONSTANTS
# ============================================================

# 로그 포맷
DEFAULT_LOG_FORMAT = '[%(asctime)s] [%(levelname)s] [%(name)s] -> %(message)s'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 로그 파일 패턴
DEFAULT_LOG_FILE_PATTERN = 'llm_%Y_%m_%d.log'

# 로그 레벨
LOG_LEVELS = {
    'DEBUG': 10,
    'INFO': 20,
    'WARNING': 30,
    'ERROR': 40,
    'CRITICAL': 50
}

# 기본 로그 디렉토리
DEFAULT_LOG_DIR = 'logs'


# ============================================================
# DAILY ROTATING FILE HANDLER
# ============================================================

class DailyRotatingFileHandler(logging.FileHandler):
    """
    날짜가 바뀌면 새로운 로그 파일을 자동으로 생성하는 핸들러
    filename_pattern: 로그 파일 이름 패턴 (예: 'llm_%Y_%m_%d.log')
    """

    def __init__(self, filename_pattern, encoding=None):
        """
        Args:
            filename_pattern: 로그 파일 이름 패턴 (strftime 형식)
            encoding: 파일 인코딩
        """
        self.filename_pattern = filename_pattern
        self.current_date = datetime.now().date()
        self.baseFilename = self._get_log_filename()
        logging.FileHandler.__init__(self, self.baseFilename, 'a', encoding)

    def _get_log_filename(self):
        """현재 날짜 기반 로그 파일명 반환"""
        return datetime.now().strftime(self.filename_pattern)

    def emit(self, record):
        """로그 레코드 출력 (날짜 변경시 새 파일로 전환)"""
        now = datetime.now()
        current_date = now.date()

        if current_date != self.current_date:
            self.current_date = current_date
            self.close()
            self.baseFilename = self._get_log_filename()
            self.stream = self._open()

        super().emit(record)


# ============================================================
# LOGGER SETUP FUNCTION
# ============================================================

def setup_logger(name=None):
    """
    로그 설정 함수
    프로젝트 내 모든 파일별 로그 생성

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        logging.Logger: 설정된 로거 인스턴스
    """
    if name in _loggers_initialized:
        return logging.getLogger(name)

    log_level_str = settings.logging.level or "INFO"
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    log_path = settings.logging.path or "logs"
    log_dir = log_path

    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"로그 디렉토리 '{log_dir}' 생성 중 오류: {e}", file=sys.stderr)

    log_filename_pattern = os.path.join(log_dir, "llm_%Y_%m_%d.log")

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    if logger.handlers:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    try:
        file_handler = DailyRotatingFileHandler(
            log_filename_pattern,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)

        formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    except Exception as e:
        print(f"로그 핸들러 설정 중 오류: {e}", file=sys.stderr)
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if name:
        logger.propagate = False

    _loggers_initialized[name] = True

    return logger


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "setup_logger",
    "DailyRotatingFileHandler",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_DATE_FORMAT",
    "DEFAULT_LOG_FILE_PATTERN",
    "LOG_LEVELS",
    "DEFAULT_LOG_DIR",
]
