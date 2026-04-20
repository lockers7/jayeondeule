# ════════════════════════════════════════════════════════════════
# 로그 모듈 — 공용 로거 생성 + 일별 로테이션 + 오래된 로그 자동 정리
# 모든 설정값(레벨/포맷/보관기간)은 settings.logging 에서 로드한다.
# --->
# _setup_logger_impl: 실제 로거 설정 구현 (일반/web/api 공통)
# setup_logger: 일반 모듈용 로거 (ai_YYYY-MM-DD.log)
# setup_web_logger: 웹 요청 로거 (web_YYYY-MM-DD.log)
# setup_api_logger: API 호출 로거 (api.log, 별도 로테이션)
# _write_temp_and_replace: 파일 트리밍 시 원자적 교체 (임시파일 → rename)
# delete_old_daily_logs: N일 이전 일별 로그 파일 삭제
# trim_old_log_entries: 큰 로그의 오래된 entry 제거 (날짜 기준)
# trim_large_plain_logs: 크기 초과 평범 로그 파일 앞부분 제거
# cleanup_all_logs: 모든 로그 정리 (스케줄러에서 매일 호출)
# DailyRotatingFileHandler.__init__: 핸들러 초기화
# DailyRotatingFileHandler._get_log_filename: 현재 날짜 기준 파일명
# DailyRotatingFileHandler._open: 파일 오픈 (권한 설정 포함)
# DailyRotatingFileHandler.emit: 로그 기록 (날짜 변경 시 파일 전환)
# ════════════════════════════════════════════════════════════════
import os
import re
import sys
import glob
import grp
import logging
import tempfile
from datetime import datetime, timedelta

from agri_ai_core.config import settings

# 초기화된 로거 캐시
_loggers_initialized = {}

# [Wave 6] 로그 파일 공유 그룹 — 서비스는 root, 운영자는 jayeondeule 로
# 접근 가능하도록 로그 파일을 그룹 쓰기 가능(664)으로 설정한다. 환경변수로 덮어쓰기 가능.
_LOG_FILE_GROUP = os.getenv("LOG_FILE_GROUP", "jayeondeule")
_LOG_FILE_MODE  = 0o664


def _normalize_log_file_permissions(path):
    """로그 파일 생성/오픈 시 공유 권한(0o664) + 지정 그룹 으로 정규화.
    실패(권한 부족·그룹 없음)는 조용히 무시 — 기존 동작과 하위 호환 유지."""
    try:
        os.chmod(path, _LOG_FILE_MODE)
    except OSError:
        pass
    try:
        gid = grp.getgrnam(_LOG_FILE_GROUP).gr_gid
        os.chown(path, -1, gid)   # uid=-1 → 소유자 유지, 그룹만 변경
    except (KeyError, OSError, PermissionError):
        pass


# ═══════════════════════════
# LOG CONFIGURATION CONSTANTS
# ═══════════════════════════

# 로그 포맷
DEFAULT_LOG_FORMAT = '[%(asctime)s] [%(levelname)s] [%(name)-39s] -> %(message)s'
# 로그 보관 기간 (일)
LOG_RETENTION_DAYS = 100

# 타임스탬프 없는 로그 파일 최대 줄 수
MAX_PLAIN_LOG_LINES = 50000


# ═════════════════════════════════════════════════════════
# DAILY ROTATING FILE HANDLER
# 날짜가 바뀌면 새로운 로그 파일을 자동으로 생성하는 핸들러
# ═════════════════════════════════════════════════════════
class DailyRotatingFileHandler(logging.FileHandler):
    def __init__(self, filename_pattern, encoding=None):
        self.filename_pattern = filename_pattern
        self.current_date = datetime.now().date()
        self.baseFilename = self._get_log_filename()
        logging.FileHandler.__init__(self, self.baseFilename, 'a', encoding)

    # 현재 날짜 기반 로그 파일명 반환
    def _get_log_filename(self):
        return datetime.now().strftime(self.filename_pattern)

    # 파일 열기 (root/일반 유저 혼재 환경에서 권한 충돌 방지)
    def _open(self):
        stream = super()._open()
        _normalize_log_file_permissions(self.baseFilename)
        return stream

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


# ═════════════════════
# LOGGER SETUP FUNCTION
# ═════════════════════
def _setup_logger_impl(cache_key, logger_name, file_pattern, error_label, use_plain_file=False):
    log_level_str = (os.getenv("LOG_LEVEL") or settings.logging.level or "INFO").strip().upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    log_console_enabled = str(os.getenv("LOG_CONSOLE_ENABLED", "false")).strip().lower() in {
        "1", "true", "yes", "on"
    }

    if cache_key in _loggers_initialized:
        logger = logging.getLogger(logger_name)
        if logger.level != log_level:
            logger.setLevel(log_level)
            for h in logger.handlers:
                h.setLevel(log_level)
        return logger

    log_dir = settings.logging.path or "logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"로그 디렉토리 '{log_dir}' 생성 중 오류: {e}", file=sys.stderr)

    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    try:
        if use_plain_file:
            log_path = os.path.join(log_dir, file_pattern)
            file_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
            _normalize_log_file_permissions(log_path)
        else:
            file_handler = DailyRotatingFileHandler(os.path.join(log_dir, file_pattern), encoding='utf-8')
        file_handler.setLevel(log_level)
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        if log_console_enabled:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
    except Exception as e:
        print(f"{error_label} 핸들러 설정 중 오류: {e}", file=sys.stderr)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
        logger.addHandler(console_handler)

    logger.propagate = False
    _loggers_initialized[cache_key] = True
    return logger


def setup_logger(name=None):
    return _setup_logger_impl(name, name, "ai_%Y-%m-%d.log", "로그")


def setup_web_logger(name=None):
    cache_key = f"_web_{name}"
    return _setup_logger_impl(cache_key, cache_key, "web_%Y-%m-%d.log", "웹 로그")


def setup_api_logger(name=None):
    cache_key = f"_api_{name}"
    return _setup_logger_impl(cache_key, cache_key, "api.log", "API 로그", use_plain_file=True)


# ═════════════════════
# LOG CLEANUP FUNCTIONS
# ═════════════════════
def _write_temp_and_replace(filepath, lines):
    dir_name = os.path.dirname(filepath)
    filename = os.path.basename(filepath)
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', dir=dir_name,
        prefix=f".{filename}.", suffix='.tmp', delete=False
    ) as tmp:
        tmp.writelines(lines)
        tmp_path = tmp.name
    os.replace(tmp_path, filepath)


# ════════════════════════════════════════════════════════
# ai_*.log, web_*.log, shop_*.log 중 지정일 이전 파일 삭제
# ════════════════════════════════════════════════════════
def delete_old_daily_logs(log_dir, days=LOG_RETENTION_DAYS):
    cutoff = datetime.now() - timedelta(days=days)
    deleted_count = 0

    for pattern in ("ai_*.log", "web_*.log", "shop_*.log"):
        for log_file in glob.glob(os.path.join(log_dir, pattern)):
            try:
                basename = os.path.basename(log_file)
                # ai_2026-02-14.log → 2026-02-14 또는 web_2026-02-14.log → 2026-02-14
                date_part = basename.split("_", 1)[1].replace(".log", "")
                log_date = datetime.strptime(date_part, "%Y-%m-%d")
                if log_date < cutoff:
                    os.remove(log_file)
                    deleted_count += 1
                    print(f"[로그정리] 삭제: {basename} ({days}일 초과)")
            except (ValueError, IndexError, OSError) as e:
                print(f"[로그정리] 삭제 오류: {log_file} - {e}", file=sys.stderr)

    return deleted_count


# ═══════════════════════════════════════════════════════
# 타임스탬프 기반으로 단일 로그 파일에서 오래된 항목 제거
# ═══════════════════════════════════════════════════════
def trim_old_log_entries(log_dir, days=LOG_RETENTION_DAYS):
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
                _write_temp_and_replace(filepath, kept_lines)
                removed = keep_from
                trimmed_count += removed
                print(f"[로그정리] {filename}: {removed}줄 삭제 ({days}일 이전)")
        except (OSError, IOError) as e:
            print(f"[로그정리] {filename} 트리밍 오류: {e}", file=sys.stderr)

    return trimmed_count


# ════════════════════════════════════════════════════════
# 타임스탬프 없는 로그 파일의 크기를 제한 (최근 줄만 유지)
# ════════════════════════════════════════════════════════
def trim_large_plain_logs(log_dir, max_lines=MAX_PLAIN_LOG_LINES):
    target_files = ["ollama.log", "react_build.log"]
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
            _write_temp_and_replace(filepath, kept_lines)
            removed = len(lines) - max_lines
            trimmed_count += removed
            print(f"[로그정리] {filename}: {removed}줄 삭제 (최대 {max_lines}줄 유지)")
        except (OSError, IOError) as e:
            print(f"[로그정리] {filename} 트리밍 오류: {e}", file=sys.stderr)

    return trimmed_count


# ════════════════════════════════════
# 전체 로그 정리 (앱 시작 시 1회 호출)
# ════════════════════════════════════
def cleanup_all_logs():
    log_dir = settings.logging.path or "logs"
    if not os.path.isdir(log_dir):
        return

    print(f"[로그정리] 시작 (보관기간: {LOG_RETENTION_DAYS}일, 경로: {log_dir})")

    daily_deleted = delete_old_daily_logs(log_dir)
    entry_trimmed = trim_old_log_entries(log_dir)
    plain_trimmed = trim_large_plain_logs(log_dir)

    # 쇼핑몰 로그 정리 (60일 보관)
    shop_deleted = delete_old_daily_logs(log_dir, days=60)

    total = daily_deleted + shop_deleted + (1 if entry_trimmed > 0 else 0) + (1 if plain_trimmed > 0 else 0)
    if total > 0:
        print(f"[로그정리] 완료 (일별파일 {daily_deleted}개 삭제, "
              f"쇼핑몰 {shop_deleted}개 삭제, "
              f"단일파일 {entry_trimmed}줄 트리밍, "
              f"대용량파일 {plain_trimmed}줄 트리밍)")
    else:
        print("[로그정리] 완료 (정리할 항목 없음)")


# ══════════════════
# EXPORTS
# ══════════════════

__all__ = [
    "setup_logger",
    "setup_web_logger",
    "setup_api_logger",
    "DailyRotatingFileHandler",
    "cleanup_all_logs",
    "delete_old_daily_logs",
    "trim_old_log_entries",
    "trim_large_plain_logs",
    "DEFAULT_LOG_FORMAT",
    "LOG_RETENTION_DAYS",
]
