import os
import re
from datetime import date, datetime
from typing import Any, Optional, Tuple
from contextlib import contextmanager

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    RealDictCursor = None

from agri_ai_core.config import settings
from agri_ai_core.logs import setup_logger
from agri_ai_core.src.ai.mcp_client import postgres_query

logger = setup_logger(__name__)


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
        self._initialized = True
        self.logger = setup_logger(__name__)

        # MCP postgres는 명시적으로 켠 경우에만 사용한다.
        self.use_mcp_postgres = self._is_true(os.getenv("USE_MCP_POSTGRES", "false"))
        self.mcp_timeout_seconds = self._safe_positive_int(
            os.getenv("MCP_POSTGRES_TIMEOUT_SECONDS", "8"),
            default=8,
        )
        self._mcp_fallback_logged = False

    @staticmethod
    def _is_true(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _safe_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except Exception:
            return default

    _PLACEHOLDER_PATTERN = re.compile(r"%[sd]")

    @staticmethod
    def _to_sql_literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (datetime, date)):
            return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
        text = str(value).replace("'", "''")
        return f"'{text}'"

    def _bind_sql(self, query: str, vals: Optional[Tuple[Any, ...]] = None) -> str:
        if not vals:
            return query

        values = list(vals)
        idx = 0

        def _replace(_: re.Match) -> str:
            nonlocal idx
            if idx >= len(values):
                return _.group(0)
            literal = self._to_sql_literal(values[idx])
            idx += 1
            return literal

        return self._PLACEHOLDER_PATTERN.sub(_replace, query)

    def _execute_mcp_query(self, query: str, vals: Optional[Tuple[Any, ...]] = None) -> list:
        sql = self._bind_sql(query, vals)
        result = postgres_query(sql, timeout=self.mcp_timeout_seconds)
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "MCP postgres query failed"))

        if self._mcp_fallback_logged:
            self.logger.info("MCP postgres 복구 감지 - direct DB fallback 해제")
            self._mcp_fallback_logged = False

        rows = result.get("rows", [])
        if isinstance(rows, list):
            return rows
        return []

    def _log_mcp_fallback(self, err: Exception) -> None:
        if not self._mcp_fallback_logged:
            self.logger.warning(f"MCP postgres 실행 실패 -> direct DB fallback: {err}")
            self._mcp_fallback_logged = True
        else:
            self.logger.debug(f"MCP postgres 실패 지속 -> direct DB fallback 유지: {err}")

    def _ensure_direct_connection(self) -> bool:
        if psycopg2 is None:
            self.logger.error("psycopg2 미설치로 direct DB fallback을 사용할 수 없습니다")
            return False

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
                    cursor_factory=RealDictCursor,
                )
                self.logger.info(" DB 재연결 성공")
            return True

        except Exception as e:
            self.logger.error(f"DatabaseHandler.connect -> DB Connection ERR Desc: [{e}]")
            return False

    def connect(self):
        # MCP 우선 모드에서는 소켓 연결을 선행하지 않는다.
        if self.use_mcp_postgres:
            return True
        return self._ensure_direct_connection()

    def close(self):
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
        except Exception as e:
            self.logger.error(f"DatabaseHandler.close -> DB Close ERR Desc: [{e}]")

    @contextmanager
    def get_connection(self):
        connected = self.connect()
        if not connected:
            raise Exception("Failed to connect to database")
        try:
            yield self
        finally:
            pass

    def execute_query(self, query, vals=None):
        self.logger.debug(f"[SQL-EXECUTE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        if self.use_mcp_postgres:
            try:
                self._execute_mcp_query(query, vals)
                return True
            except Exception as mcp_err:
                self._log_mcp_fallback(mcp_err)

        if not self._ensure_direct_connection():
            self.logger.error(
                "DatabaseHandler.execute_query -> direct DB fallback unavailable: "
                f"query: [{query}], values: [{vals}]"
            )
            return False

        try:
            with self.connection.cursor() as cursor:
                if vals:
                    cursor.execute(query, vals)
                else:
                    cursor.execute(query)
            self.connection.commit()
            return True
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            self.logger.error(
                "DatabaseHandler.execute_query -> Query Execute ERR: "
                f"query: [{query}], values: [{vals}], Desc: [{e}]"
            )
            return False

    def fetch_all(self, query: str, vals: Optional[Tuple[Any, ...]] = None, as_dict: bool = False):
        self.logger.debug(f"[SQL-FETCH_ALL] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        if self.use_mcp_postgres:
            try:
                rows = self._execute_mcp_query(query, vals)
                if as_dict:
                    if rows and not isinstance(rows[0], dict):
                        return [{"value": row} for row in rows]
                    return rows
                if rows and isinstance(rows[0], dict):
                    return [tuple(row.values()) for row in rows]
                return rows
            except Exception as mcp_err:
                self._log_mcp_fallback(mcp_err)

        if not self._ensure_direct_connection():
            self.logger.error(
                "DatabaseHandler.fetch_all -> direct DB fallback unavailable: "
                f"query: [{query}], values: [{vals}]"
            )
            return []

        try:
            cursor_factory = RealDictCursor if as_dict else None
            with self.connection.cursor(cursor_factory=cursor_factory) as cursor:
                if vals:
                    cursor.execute(query, vals)
                else:
                    cursor.execute(query)
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(
                "DatabaseHandler.fetch_all -> Fetch All ERR: "
                f"query: [{query}], values: [{vals}], Desc: [{e}]"
            )
            return []

    def fetch_one(self, query, vals=None):
        self.logger.debug(f"[SQL-FETCH_ONE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        if self.use_mcp_postgres:
            try:
                rows = self._execute_mcp_query(query, vals)
                if not rows:
                    return None
                first_row = rows[0]
                if isinstance(first_row, dict):
                    return first_row
                return {"value": first_row}
            except Exception as mcp_err:
                self._log_mcp_fallback(mcp_err)

        if not self._ensure_direct_connection():
            self.logger.error(
                "DatabaseHandler.fetch_one -> direct DB fallback unavailable: "
                f"query: [{query}], values: [{vals}]"
            )
            return None

        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if vals:
                    cursor.execute(query, vals)
                else:
                    cursor.execute(query)
                return cursor.fetchone()
        except Exception as e:
            self.logger.error(
                "DatabaseHandler.fetch_one -> Fetch One ERR: "
                f"query: [{query}], values: [{vals}], Desc: [{e}]"
            )
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
