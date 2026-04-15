# ════════════════════════════════════════════════════════════
# 예외 처리 유틸 — 공통 try/except 로깅 패턴 표준화
# DB/API/파일 작업 등 38곳 이상에서 반복되는 예외 처리 보일러플레이트를
# 데코레이터와 컨텍스트 매니저로 통합한다.
# --->
# log_and_return: 예외를 로그 기록 후 default 반환 (데코레이터)
# safe_call: 함수 단발 호출 + 예외 시 default 반환
# suppress_exception: with 블록 내 예외 무시 + 로그 기록 (컨텍스트)
# ════════════════════════════════════════════════════════════
import logging
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Optional, Type, Tuple


def log_and_return(default: Any = None,
                   exceptions: Tuple[Type[BaseException], ...] = (Exception,),
                   logger: Optional[logging.Logger] = None,
                   message: Optional[str] = None):
    """함수 전체를 try/except로 감싸 예외 발생 시 로그 기록 후 default 반환.

    사용 예:
        @log_and_return(default=[], logger=mod_logger, message="DB 조회 실패")
        def read_items():
            ...

    Args:
        default: 예외 발생 시 반환할 값
        exceptions: 잡을 예외 타입 (기본 Exception)
        logger: 사용할 logger (None이면 함수 모듈의 logger 자동 사용)
        message: 로그 메시지 접두사 (None이면 함수명 사용)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                log = logger or logging.getLogger(func.__module__)
                prefix = message or f"{func.__name__}"
                log.error(f"{prefix}: {e}")
                return default
        return wrapper
    return decorator


def safe_call(func: Callable, *args, default: Any = None,
              exceptions: Tuple[Type[BaseException], ...] = (Exception,),
              logger: Optional[logging.Logger] = None,
              **kwargs) -> Any:
    """함수 1회 호출 + 예외 시 default 반환. 인라인 try/except 대체용.

    사용 예:
        result = safe_call(json.loads, raw_text, default={}, logger=mod_logger)
    """
    try:
        return func(*args, **kwargs)
    except exceptions as e:
        if logger:
            logger.error(f"{func.__name__ if hasattr(func, '__name__') else 'call'}: {e}")
        return default


@contextmanager
def suppress_exception(exceptions: Tuple[Type[BaseException], ...] = (Exception,),
                       logger: Optional[logging.Logger] = None,
                       message: str = "예외 무시"):
    """with 블록 내부 예외를 로그 기록 후 무시.

    사용 예:
        with suppress_exception(logger=mod_logger, message="캐시 삭제"):
            cache.delete(key)
    """
    try:
        yield
    except exceptions as e:
        if logger:
            logger.warning(f"{message}: {e}")
