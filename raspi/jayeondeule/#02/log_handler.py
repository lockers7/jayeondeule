import os
import sys
import glob
import time
import logging

from datetime import datetime, timedelta
from dotenv   import load_dotenv

_loggers_initialized = {}

# --------------------------------------------------------------------------------
# 날짜가 바뀌면 새로운 로그 파일을 자동으로 생성하는 핸들러
# filename_pattern: 로그 파일 이름 패턴 (예: 'Units_%Y_%m_%d.log')
# --------------------------------------------------------------------------------
class DailyRotatingFileHandler(logging.FileHandler):
    def __init__(self, filename_pattern, encoding=None):
        self.filename_pattern = filename_pattern
        self.current_date = datetime.now().date()
        self.baseFilename = self._get_log_filename()
        logging.FileHandler.__init__(self, self.baseFilename, 'a', encoding)
    
    def _get_log_filename(self):
        return datetime.now().strftime(self.filename_pattern)
    
    def emit(self, record):
        now = datetime.now()
        current_date = now.date()
        
        if current_date != self.current_date:
            self.current_date = current_date
            self.close()
            self.baseFilename = self._get_log_filename()
            self.stream = self._open()
        
        super().emit(record)

# --------------------------------------------------------------
# 지정된 로그 디렉토리에서 일정 기간(days) 이전의 로그 파일을 삭제
# --------------------------------------------------------------
def delete_old_logs(log_dir, pattern="Units_*.log", days=30):
    cutoff = datetime.now() - timedelta(days=days)
    for log_file in glob.glob(os.path.join(log_dir, pattern)):
        try:
            basename = os.path.basename(log_file)
            date_str = basename.replace("Units_", "").replace(".log", "") 
            log_date = datetime.strptime(date_str, "%Y_%m_%d")
            if log_date < cutoff:
                os.remove(log_file)
                print(f"[log_handler] 삭제된 오래된 로그: {basename}")
        except Exception as e:
            print(f"[log_handler] 로그 삭제 오류: {log_file} - {e}")

# --------------------------------------------------------------------------------
# 로그 처리
# 프로젝트 내 모든 바일 별 로그 생성 됨
# --------------------------------------------------------------------------------
def setup_logger(name=None):
    if name in _loggers_initialized:
        return logging.getLogger(name)

    if not _loggers_initialized.get('dotenv_loaded'):
        try:
            load_dotenv(override=True)
            _loggers_initialized['dotenv_loaded'] = True
        except Exception as e:
            print(f"환경 변수 로드 중 오류: {e}", file=sys.stderr)

    log_level_str = os.getenv("LOG_LEVEL", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    log_path = os.getenv("LOG_PATH", "logs")

    # 상대 경로인 경우 절대 경로로 변환
    if not os.path.isabs(log_path):
        # 스크립트 실행 위치 기준으로 절대 경로 생성
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(script_dir, log_path)
    else:
        log_dir = log_path

    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"로그 디렉토리 '{log_dir}' 생성 중 오류: {e}", file=sys.stderr)
        # 로그 디렉토리 생성 실패 시 /tmp 사용
        log_dir = "/tmp/jayeondeule_logs"
        try:
            os.makedirs(log_dir, exist_ok=True)
            print(f"대체 로그 디렉토리 사용: {log_dir}", file=sys.stderr)
        except OSError as e2:
            print(f"대체 로그 디렉토리 생성도 실패: {e2}", file=sys.stderr)

    log_filename_pattern = os.path.join(log_dir, "Units_%Y_%m_%d.log")

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

        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] -> %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    except Exception as e:
        print(f"로그 핸들러 설정 중 오류: {e}", file=sys.stderr)
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] -> %(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if name:
        logger.propagate = False

    _loggers_initialized[name] = True
    
    delete_old_logs(log_dir, days=60)    
    return logger

# --------------------------------------------------------------------------------
# 로그생성 테스트
# 생성은 날짜가 바뀌어야 함.
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    logger = setup_logger("test_logger")
    logger.info("첫 번째 로그 메시지")
    
    print("로그를 계속 출력합니다. 날짜가 바뀌면 새로운 파일로 로깅됩니다.")
    for i in range(10):
        logger.info(f"로그 메시지 #{i}")
        time.sleep(5)