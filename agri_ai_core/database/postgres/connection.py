# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PostgreSQL 데이터베이스 연결 관리 모듈
# 데이터베이스 연결 풀 관리, 세션 생성, 트랜잭션 처리 등
# 안전한 DB 연결을 위한 컨텍스트 매니저를 제공합니다.
# --->
# [클래스] DatabaseHandler: PostgreSQL 데이터베이스 핸들러
# db_session: 기능 설명 필요
# __new__: 기능 설명 필요
# __init__: 기능 설명 필요
# connect: Database 연결
# close: DB 접속 종료
# get_connection: 기능 설명 필요
# execute_query: CUD 명령어 실행
# fetch_all: SELECT 결과 복수 Record 리턴
# fetch_one: SELECT 결과 단건 Record 리턴
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import psycopg2

from typing import Optional, Tuple, Any
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

from agri_ai_core.log_utils.log_handlers import setup_logger
from agri_ai_core.shared_modules.config.settings import settings

logger = setup_logger(__name__)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# PostgreSQL 데이터베이스 핸들러
# PostgreSQL 데이터베이스 핸들러 (싱글톤 패턴)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class DatabaseHandler:

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseHandler, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.HOST = settings.database.host
        self.PORT = settings.database.port
        self.DATABASE = settings.database.database
        self.USER = settings.database.user
        self.PASSWORD = settings.database.password

        self.connection = None
        self.cursor = None
        self._initialized = True

        self.logger = setup_logger(__name__)

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # Database 연결
    # 데이터베이스 연결
    #
    # Returns:
    #     bool: 연결 성공 여부
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def connect(self):
        try:
            if self.connection:
                self.logger.debug(f" 커넥션 상태: closed={self.connection.closed}")

            if self.connection is not None:
                try:
                    with self.connection.cursor() as test_cursor:
                        test_cursor.execute("SELECT 1")
                except Exception:
                    self.logger.warning("기존 커넥션이 죽어있음. 재연결 시도.")
                    self.close()

            if self.connection is None or self.connection.closed:
                self.connection = psycopg2.connect(
                    host=self.HOST,
                    port=self.PORT,
                    database=self.DATABASE,
                    user=self.USER,
                    password=self.PASSWORD,
                    cursor_factory=RealDictCursor
                )
                self.cursor = self.connection.cursor()
                self.logger.info(" DB 재연결 성공")
            return True

        except Exception as e:
            self.logger.error(f"DatabaseHandler.connect -> DB Connection ERR Desc: [{e}]")
            return False

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # DB 접속 종료
    # 데이터베이스 연결 종료
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def close(self):
        try:
            if hasattr(self, 'cursor') and self.cursor:
                self.cursor.close()
                self.cursor = None
            if hasattr(self, 'connection') and self.connection:
                self.connection.close()
                self.connection = None
        except Exception as e:
            self.logger.error(f"DatabaseHandler.close -> DB Close ERR Desc: [{e}]")

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # Context manager for database connections
    # 데이터베이스 연결 컨텍스트 매니저
    #
    # Yields:
    #     DatabaseHandler: 자기 자신
    #
    # Raises:
    #     Exception: 연결 실패시
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    @contextmanager
    def get_connection(self):
        connected = self.connect()
        if not connected:
            raise Exception("Failed to connect to database")
        try:
            yield self
        finally:
            pass

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # CUD 명령어 실행
    # 쿼리 실행 (INSERT, UPDATE, DELETE)
    #
    # Args:
    #     query: 실행할 SQL 쿼리
    #     vals: 쿼리 파라미터
    #
    # Returns:
    #     bool: 실행 성공 여부
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def execute_query(self, query, vals=None):
        if not self.connect():
            return False

        try:
            self.logger.debug(f"[SQL-EXECUTE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

            if vals:
                self.cursor.execute(query, vals)
            else:
                self.cursor.execute(query)
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"DatabaseHandler.execute_query -> Query Execute ERR: query: [{query}], values: [{vals}], Desc: [{e}]")
            return False

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # SELECT 결과 복수 Record 리턴
    # 쿼리 실행 후 모든 결과 반환
    #
    # Args:
    #     query: 실행할 SQL 쿼리
    #     vals: 쿼리 파라미터
    #     as_dict: True면 딕셔너리로 반환
    #
    # Returns:
    #     list: 조회 결과 목록
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def fetch_all(self, query: str, vals: Optional[Tuple[Any, ...]] = None, as_dict: bool = False):
        if not self.connect():
            return []

        try:
            self.logger.debug(f"[SQL-FETCH_ALL] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

            cursor_factory = RealDictCursor if as_dict else None
            with self.connection.cursor(cursor_factory=cursor_factory) as cursor:
                if vals:
                    cursor.execute(query, vals)
                else:
                    cursor.execute(query)
                return cursor.fetchall()

        except Exception as e:
            self.logger.error(f"DatabaseHandler.fetch_all -> Fetch All ERR: query: [{query}], values: [{vals}], Desc: [{e}]")
            return []

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # SELECT 결과 단건 Record 리턴
    # 쿼리 실행 후 단일 결과 반환
    #
    # Args:
    #     query: 실행할 SQL 쿼리
    #     vals: 쿼리 파라미터
    #
    # Returns:
    #     dict or None: 조회 결과 또는 None
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def fetch_one(self, query, vals=None):
        if not self.connect():
            return None

        try:
            self.logger.debug(f"[SQL-FETCH_ONE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

            if vals:
                self.cursor.execute(query, vals)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchone()
        except Exception as e:
            self.logger.error(f"DatabaseHandler.fetch_one -> Fetch One ERR: query: [{query}], values: [{vals}], Desc: [{e}]")
            return None


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 전역 데이터베이스 핸들러 인스턴스
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
db = DatabaseHandler()


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 데이터베이스 세션 컨텍스트 매니저
# 데이터베이스 세션 컨텍스트 매니저
#
# Yields:
#     DatabaseHandler: 데이터베이스 핸들러
#
# Example:
#     with db_session() as database:
#         result = database.fetch_one(query, values)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@contextmanager
def db_session():
    with db.get_connection() as connection:
        try:
            yield connection
        except Exception as e:
            import traceback
            error_msg = str(e) if e else "Unknown database error"
            stack_trace = traceback.format_exc()
            db.logger.error(f"Database session error: {error_msg}")
            db.logger.error(f"Stack trace: {stack_trace}")
            raise
