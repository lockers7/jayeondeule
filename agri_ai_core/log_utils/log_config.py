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
