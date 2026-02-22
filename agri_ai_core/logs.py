# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Unified Logging Module
# 로그 설정 및 핸들러 관리
# 원래 파일: log_utils/log_config.py + log_utils/log_handlers.py
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import sys
import glob
import logging
import tempfile
from datetime import datetime, timedelta

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
WEB_LOG_FILE_PATTERN = 'web_%Y_%m_%d.log'

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

# 로그 보관 기간 (일)
LOG_RETENTION_DAYS = 100

# 타임스탬프 없는 로그 파일 최대 줄 수
MAX_PLAIN_LOG_LINES = 50000


# ============================================================
# DAILY ROTATING FILE HANDLER
# 날짜가 바뀌면 새로운 로그 파일을 자동으로 생성하는 핸들러
# filename_pattern: 로그 파일 이름 패턴 (예: 'llm_%Y_%m_%d.log')
# ============================================================

class DailyRotatingFileHandler(logging.FileHandler):
    # ------------------------------------------------------------
    # filename_pattern: 로그 파일 이름 패턴 (strftime 형식)
    # encoding: 파일 인코딩
    # ------------------------------------------------------------
    def __init__(self, filename_pattern, encoding=None):
        self.filename_pattern = filename_pattern
        self.current_date = datetime.now().date()
        self.baseFilename = self._get_log_filename()
        logging.FileHandler.__init__(self, self.baseFilename, 'a', encoding)

    # 현재 날짜 기반 로그 파일명 반환
    def _get_log_filename(self):
        return datetime.now().strftime(self.filename_pattern)

    # 로그 레코드 출력 (날짜 변경시 새 파일로 전환)
    def emit(self, record):
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
# 로그 설정 함수
# 프로젝트 내 모든 파일별 로그 생성
# ============================================================

def setup_logger(name=None):
    # .env 또는 환경변수의 최신 LOG_LEVEL을 직접 읽음 (캐시된 settings 우회)
    log_level_str = (os.getenv("LOG_LEVEL") or settings.logging.level or "INFO").strip().upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    if name in _loggers_initialized:
        logger = logging.getLogger(name)
        # 환경변수 변경 시 기존 로거의 레벨도 동기화
        if logger.level != log_level:
            logger.setLevel(log_level)
            for h in logger.handlers:
                h.setLevel(log_level)
        return logger

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
# WEB LOGGER SETUP FUNCTION
# 웹 요청/응답 전용 로거 (web_YYYY_MM_DD.log에 기록)
# ============================================================

def setup_web_logger(name=None):
    log_level_str = (os.getenv("LOG_LEVEL") or settings.logging.level or "INFO").strip().upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    cache_key = f"_web_{name}"

    if cache_key in _loggers_initialized:
        logger = logging.getLogger(cache_key)
        if logger.level != log_level:
            logger.setLevel(log_level)
            for h in logger.handlers:
                h.setLevel(log_level)
        return logger

    log_path = settings.logging.path or "logs"
    log_dir = log_path

    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"로그 디렉토리 '{log_dir}' 생성 중 오류: {e}", file=sys.stderr)

    log_filename_pattern = os.path.join(log_dir, "web_%Y_%m_%d.log")

    logger = logging.getLogger(cache_key)
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
        print(f"웹 로그 핸들러 설정 중 오류: {e}", file=sys.stderr)
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.propagate = False
    _loggers_initialized[cache_key] = True

    return logger


# ============================================================
# LOG CLEANUP FUNCTIONS
# 로그 정리 함수 (보관 기간: 100일)
# ============================================================

def delete_old_daily_logs(log_dir, days=LOG_RETENTION_DAYS):
    """llm_*.log, web_*.log 중 지정일 이전 파일 삭제"""
    cutoff = datetime.now() - timedelta(days=days)
    deleted_count = 0

    for pattern in ("llm_*.log", "web_*.log"):
        for log_file in glob.glob(os.path.join(log_dir, pattern)):
            try:
                basename = os.path.basename(log_file)
                # llm_2026_02_14.log → 2026_02_14 또는 web_2026_02_14.log → 2026_02_14
                date_part = basename.split("_", 1)[1].replace(".log", "")
                log_date = datetime.strptime(date_part, "%Y_%m_%d")
                if log_date < cutoff:
                    os.remove(log_file)
                    deleted_count += 1
                    print(f"[로그정리] 삭제: {basename} ({days}일 초과)")
            except (ValueError, IndexError, OSError) as e:
                print(f"[로그정리] 삭제 오류: {log_file} - {e}", file=sys.stderr)

    return deleted_count


def trim_old_log_entries(log_dir, days=LOG_RETENTION_DAYS):
    """타임스탬프 기반으로 단일 로그 파일에서 오래된 항목 제거"""
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    target_files = ["scheduler.log", "api.log", "service.log"]
    # [2026-02-14 또는 [2026-02-14, 형태의 타임스탬프 매칭
    ts_pattern = re.compile(r'^\[(\d{4}-\d{2}-\d{2})')
    trimmed_count = 0

    for filename in target_files:
        filepath = os.path.join(log_dir, filename)
        if not os.path.isfile(filepath):
            continue

        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            if not lines:
                continue

            # cutoff 이후 첫 라인의 인덱스 찾기
            # 타임스탬프가 없는 선행 라인(파일 앞부분)은 유지
            keep_from = 0
            first_ts_found = False
            first_old_ts_index = -1

            for i, line in enumerate(lines):
                match = ts_pattern.match(line)
                if match:
                    date_str = match.group(1)
                    if not first_ts_found:
                        first_ts_found = True
                        if date_str < cutoff_str:
                            first_old_ts_index = i
                    if date_str >= cutoff_str:
                        keep_from = i
                        break
                    first_old_ts_index = i
            else:
                # 모든 라인을 순회했지만 cutoff 이후 타임스탬프를 못 찾은 경우
                if first_ts_found and first_old_ts_index >= 0:
                    # 모든 타임스탬프가 cutoff 이전 → 전체 삭제
                    keep_from = len(lines)

            # 타임스탬프가 없는 선행 라인이 있고, 삭제 시작이 그 이전이면 보존
            if not first_ts_found:
                keep_from = 0

            if keep_from > 0:
                kept_lines = lines[keep_from:]
                # 안전한 쓰기: 임시 파일에 쓴 후 교체
                dir_name = os.path.dirname(filepath)
                with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=dir_name,
                    prefix=f".{filename}.", suffix='.tmp', delete=False
                ) as tmp:
                    tmp.writelines(kept_lines)
                    tmp_path = tmp.name
                os.replace(tmp_path, filepath)
                removed = keep_from
                trimmed_count += removed
                print(f"[로그정리] {filename}: {removed}줄 삭제 ({days}일 이전)")
        except (OSError, IOError) as e:
            print(f"[로그정리] {filename} 트리밍 오류: {e}", file=sys.stderr)

    return trimmed_count


def trim_large_plain_logs(log_dir, max_lines=MAX_PLAIN_LOG_LINES):
    """타임스탬프 없는 로그 파일의 크기를 제한 (최근 줄만 유지)"""
    target_files = ["ollama.log", "reflex.log", "react_build.log"]
    trimmed_count = 0

    for filename in target_files:
        filepath = os.path.join(log_dir, filename)
        if not os.path.isfile(filepath):
            continue

        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            if len(lines) <= max_lines:
                continue

            # 최근 max_lines 줄만 유지
            kept_lines = lines[-max_lines:]
            dir_name = os.path.dirname(filepath)
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=dir_name,
                prefix=f".{filename}.", suffix='.tmp', delete=False
            ) as tmp:
                tmp.writelines(kept_lines)
                tmp_path = tmp.name
            os.replace(tmp_path, filepath)
            removed = len(lines) - max_lines
            trimmed_count += removed
            print(f"[로그정리] {filename}: {removed}줄 삭제 (최대 {max_lines}줄 유지)")
        except (OSError, IOError) as e:
            print(f"[로그정리] {filename} 트리밍 오류: {e}", file=sys.stderr)

    return trimmed_count


def cleanup_all_logs():
    """전체 로그 정리 (앱 시작 시 1회 호출)"""
    log_dir = settings.logging.path or "logs"
    if not os.path.isdir(log_dir):
        return

    print(f"[로그정리] 시작 (보관기간: {LOG_RETENTION_DAYS}일, 경로: {log_dir})")

    daily_deleted = delete_old_daily_logs(log_dir)
    entry_trimmed = trim_old_log_entries(log_dir)
    plain_trimmed = trim_large_plain_logs(log_dir)

    total = daily_deleted + (1 if entry_trimmed > 0 else 0) + (1 if plain_trimmed > 0 else 0)
    if total > 0:
        print(f"[로그정리] 완료 (일별파일 {daily_deleted}개 삭제, "
              f"단일파일 {entry_trimmed}줄 트리밍, "
              f"대용량파일 {plain_trimmed}줄 트리밍)")
    else:
        print("[로그정리] 완료 (정리할 항목 없음)")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "setup_logger",
    "setup_web_logger",
    "DailyRotatingFileHandler",
    "cleanup_all_logs",
    "delete_old_daily_logs",
    "trim_old_log_entries",
    "trim_large_plain_logs",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_DATE_FORMAT",
    "DEFAULT_LOG_FILE_PATTERN",
    "WEB_LOG_FILE_PATTERN",
    "LOG_LEVELS",
    "DEFAULT_LOG_DIR",
    "LOG_RETENTION_DAYS",
]
