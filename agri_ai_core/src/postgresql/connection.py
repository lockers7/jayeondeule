# ════════════════════════════════════════════════════════════
# PostgreSQL 연결 관리: 커넥션 풀 싱글톤 및 세션 컨텍스트 매니저.
# ════════════════════════════════════════════════════════════
import os
import re
import threading
from datetime import date, datetime
from typing import Any, Optional, Tuple
from contextlib import contextmanager

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from psycopg2.pool import ThreadedConnectionPool
except Exception:
    psycopg2 = None
    RealDictCursor = None
    ThreadedConnectionPool = None

from agri_ai_core.config import settings
from agri_ai_core.logs import setup_logger
# postgres_query는 함수 내부에서 지연 import (계층 역전 방지)
from agri_ai_core.src.utils.validators import is_true

logger = setup_logger(__name__)


class DatabaseHandler:

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
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

        self._pool = None
        self._pool_lock = threading.Lock()
        self._initialized = True
        self.logger = setup_logger(__name__)

        # MCP postgres는 명시적으로 켠 경우에만 사용한다.
        self.use_mcp_postgres = is_true(os.getenv("USE_MCP_POSTGRES", "false"))
        self.mcp_timeout_seconds = self._safe_positive_int(
            os.getenv("MCP_POSTGRES_TIMEOUT_SECONDS", "8"),
            default=8,
        )
        self._mcp_fallback_logged = False

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
        from agri_ai_core.src.ai.mcp_client import postgres_query  # 지연 import (계층 역전 방지)
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

    # ------------------------------------------------------------------
    # 커넥션 풀 관리
    # ThreadedConnectionPool을 지연 초기화 (스레드 안전)
    # ------------------------------------------------------------------
    def _ensure_pool(self):
        if self._pool is not None:
            return True

        if psycopg2 is None or ThreadedConnectionPool is None:
            self.logger.error("psycopg2 미설치로 커넥션 풀을 생성할 수 없습니다")
            return False

        with self._pool_lock:
            if self._pool is not None:
                return True
            try:
                self._pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    host=self.HOST,
                    port=self.PORT,
                    database=self.DATABASE,
                    user=self.USER,
                    password=self.PASSWORD,
                )
                self.logger.info("DB 커넥션 풀 초기화 완료 (minconn=1, maxconn=5)")
                return True
            except Exception as e:
                self.logger.error(f"DB 커넥션 풀 초기화 실패: {e}")
                return False

    # ============================================================
    # 풀에서 커넥션 획득
    # ============================================================
    def _getconn(self):
        if not self._ensure_pool():
            return None
        try:
            return self._pool.getconn()
        except Exception as e:
            self.logger.error(f"풀에서 커넥션 획득 실패: {e}")
            return None

    # ============================================================
    # 풀에 커넥션 반환
    # ============================================================
    def _putconn(self, conn):
        if self._pool is not None and conn is not None:
            try:
                self._pool.putconn(conn)
            except Exception as e:
                self.logger.debug(f"풀에 커넥션 반환 중 오류: {e}")
                try:
                    conn.close()
                except Exception:
                    pass

    def connect(self):
        # MCP 우선 모드에서는 소켓 연결을 선행하지 않는다.
        if self.use_mcp_postgres:
            return True
        return self._ensure_pool()

    def close(self):
        try:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None
                self.logger.info("DB 커넥션 풀 종료 완료")
        except Exception as e:
            self.logger.error(f"DatabaseHandler.close -> Pool Close ERR Desc: [{e}]")

    @contextmanager
    def get_connection(self):
        connected = self.connect()
        if not connected:
            raise Exception("Failed to connect to database")
        yield self

    # ============================================================
    # 직접 DB 연결로 쿼리 실행 공통 래퍼.
    # ============================================================
    def _run_direct(self, op_name, query, vals, error_default, cursor_factory=None, fetch_mode=None, commit=False):
        conn = self._getconn()
        if conn is None:
            self.logger.error(f"DatabaseHandler.{op_name} -> direct DB fallback unavailable: query: [{query}], values: [{vals}]")
            return error_default

        try:
            with conn.cursor(cursor_factory=cursor_factory) as cursor:
                cursor.execute(query, vals) if vals else cursor.execute(query)
                if commit:
                    conn.commit()
                    return True
                if fetch_mode == "all":
                    return cursor.fetchall()
                if fetch_mode == "one":
                    return cursor.fetchone()
                return True
        except Exception as e:
            if commit:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.logger.error(f"DatabaseHandler.{op_name} -> ERR: query: [{query}], values: [{vals}], Desc: [{e}]")
            return error_default
        finally:
            self._putconn(conn)

    def execute_query(self, query, vals=None):
        self.logger.debug(f"[SQL-EXECUTE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        if self.use_mcp_postgres:
            try:
                self._execute_mcp_query(query, vals)
                return True
            except Exception as mcp_err:
                self._log_mcp_fallback(mcp_err)

        return self._run_direct("execute_query", query, vals, False, commit=True)

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

        return self._run_direct("fetch_all", query, vals, [],
                                cursor_factory=RealDictCursor if as_dict else None, fetch_mode="all")

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

        return self._run_direct("fetch_one", query, vals, None,
                                cursor_factory=RealDictCursor, fetch_mode="one")


# ════════════════════════════════════════════════════════════
# 전역 데이터베이스 핸들러 인스턴스
# ════════════════════════════════════════════════════════════
db = DatabaseHandler()


# ════════════════════════════════════════════════════════════
# 데이터베이스 세션 컨텍스트 매니저
# ════════════════════════════════════════════════════════════
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
