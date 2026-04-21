# ════════════════════════════════════════════════════════════════════
# PostgreSQL 연결 관리 — 커넥션 풀 싱글톤, MCP/direct 듀얼 경로,
# 세션 컨텍스트 매니저. 환경변수 USE_MCP_POSTGRES 로 MCP 우선 사용 토글.
# --->
# set_mcp_query_fn       : 상위 계층의 MCP postgres 실행기 주입 (의존성 역전)
# DatabaseHandler        : 싱글톤 DB 핸들러 (MCP/direct 듀얼 경로)
#   __new__              : 싱글톤 인스턴스 보장
#   __init__             : 1회 한정 초기화 (호스트/포트/풀/MCP 옵션)
#   _safe_positive_int   : 환경변수 양의 정수 파싱 (실패 시 default)
#   _to_sql_literal      : 파라미터 값을 SQL 리터럴로 변환 (MCP 경로용)
#   _bind_sql            : %s 자리표시자 → SQL 리터럴 치환
#   _execute_mcp_query   : MCP 실행기로 쿼리 실행 + 복구 감지
#   _log_mcp_fallback    : MCP 실패 시 direct fallback 로그 (1회 경고)
#   _ensure_pool         : ThreadedConnectionPool 지연 초기화
#   get_pool_stats       : 현재 풀 사용 상태 스냅샷 (관측성)
#   _getconn / _putconn  : 풀에서 커넥션 획득/반환
#   connect / close      : 풀 초기화/종료
#   get_connection       : 컨텍스트 매니저로 self 노출
#   _run_direct          : direct DB 쿼리 실행 공통 래퍼
#   execute_query        : INSERT/UPDATE/DELETE 등 commit 쿼리
#   fetch_all / fetch_one: SELECT 쿼리 (전체/단일 행)
# db_session             : db.get_connection() 의 모듈 레벨 컨텍스트 매니저
# ════════════════════════════════════════════════════════════════════
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
from agri_ai_core.src.utils.validators import is_true

logger = setup_logger(__name__)

# MCP postgres 실행기(옵션). 상위 계층(startup.py 등)에서 주입한다.
# None이면 USE_MCP_POSTGRES=true여도 MCP 경로가 비활성화되고 direct DB만 사용.
# 시그니처: (sql: str, timeout: int) -> dict({"success": bool, "rows": list, "error": str})
_mcp_query_fn = None


# ────────────────────────────────────────────────────────────────────
# 상위 계층이 MCP postgres 실행기를 주입 (의존성 역전).
# 이 훅이 없으면 MCP 경로는 비활성 — postgresql 패키지가 AI 계층을 역참조
# 하지 않도록 함.
# ────────────────────────────────────────────────────────────────────
def set_mcp_query_fn(fn) -> None:
    global _mcp_query_fn
    _mcp_query_fn = fn


class DatabaseHandler:

    _instance = None
    _instance_lock = threading.Lock()

    # ────────────────────────────────────────────────────────────────
    # 싱글톤 인스턴스 보장 — 첫 호출에서만 객체 생성.
    # ────────────────────────────────────────────────────────────────
    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseHandler, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    # ────────────────────────────────────────────────────────────────
    # 1회 한정 초기화 — 호스트/포트/풀/MCP 옵션 로드.
    # ────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # 환경변수 양의 정수 파싱 — 0 이하/비정수면 default.
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def _safe_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except Exception:
            return default

    _PLACEHOLDER_PATTERN = re.compile(r"%[sd]")

    # ────────────────────────────────────────────────────────────────
    # 파라미터 값을 SQL 리터럴 문자열로 변환 (MCP 경로 prepared 미지원 대응).
    # ────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # %s/%d 자리표시자를 _to_sql_literal 결과로 치환한 SQL 문자열 생성.
    # ────────────────────────────────────────────────────────────────
    def _bind_sql(self, query: str, vals: Optional[Tuple[Any, ...]] = None) -> str:
        if not vals:
            return query

        values = list(vals)
        idx = 0

        # ────────────────────────────────────────────────────────────
        # 정규식 매치 1건 → 다음 vals 항목의 SQL 리터럴로 치환.
        # ────────────────────────────────────────────────────────────
        def _replace(_: re.Match) -> str:
            nonlocal idx
            if idx >= len(values):
                return _.group(0)
            literal = self._to_sql_literal(values[idx])
            idx += 1
            return literal

        return self._PLACEHOLDER_PATTERN.sub(_replace, query)

    # ────────────────────────────────────────────────────────────────
    # MCP 실행기로 쿼리 전송. 성공 시 rows 반환, 실패 시 RuntimeError.
    # 복구 감지 시 fallback 플래그 해제 + 복구 로그.
    # ────────────────────────────────────────────────────────────────
    def _execute_mcp_query(self, query: str, vals: Optional[Tuple[Any, ...]] = None) -> list:
        if _mcp_query_fn is None:
            raise RuntimeError("MCP postgres 실행기가 주입되지 않음 (set_mcp_query_fn 미호출)")
        sql = self._bind_sql(query, vals)
        result = _mcp_query_fn(sql, timeout=self.mcp_timeout_seconds)
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "MCP postgres query failed"))

        if self._mcp_fallback_logged:
            self.logger.info("MCP postgres 복구 감지 - direct DB fallback 해제")
            self._mcp_fallback_logged = False

        rows = result.get("rows", [])
        if isinstance(rows, list):
            return rows
        return []

    # ────────────────────────────────────────────────────────────────
    # MCP 실패 시 direct DB fallback 로그 — 첫 실패는 warning, 이후 debug.
    # ────────────────────────────────────────────────────────────────
    def _log_mcp_fallback(self, err: Exception) -> None:
        if not self._mcp_fallback_logged:
            self.logger.warning(f"MCP postgres 실행 실패 -> direct DB fallback: {err}")
            self._mcp_fallback_logged = True
        else:
            self.logger.debug(f"MCP postgres 실패 지속 -> direct DB fallback 유지: {err}")

    # ────────────────────────────────────────────────────────────────
    # ThreadedConnectionPool 지연 초기화 (스레드 안전, double-checked).
    # 환경변수 PGDB_POOL_MIN/MAX 로 풀 크기 튜닝 가능.
    # ────────────────────────────────────────────────────────────────
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
                # [Wave 11] min/max 커넥션 수를 환경변수로 노출 — 운영 환경 튜닝
                minconn = self._safe_positive_int(os.getenv("PGDB_POOL_MIN"), default=1)
                maxconn = self._safe_positive_int(os.getenv("PGDB_POOL_MAX"), default=5)
                if minconn > maxconn:
                    minconn = maxconn
                self._pool = ThreadedConnectionPool(
                    minconn=minconn,
                    maxconn=maxconn,
                    host=self.HOST,
                    port=self.PORT,
                    database=self.DATABASE,
                    user=self.USER,
                    password=self.PASSWORD,
                )
                self._pool_min = minconn
                self._pool_max = maxconn
                self.logger.info(f"DB 커넥션 풀 초기화 완료 (minconn={minconn}, maxconn={maxconn})")
                return True
            except Exception as e:
                self.logger.error(f"DB 커넥션 풀 초기화 실패: {e}")
                return False

    # ────────────────────────────────────────────────────────────────
    # [Wave 11] 현재 풀 사용 상태 스냅샷 (관측성).
    # ThreadedConnectionPool 내부 자료구조를 best-effort 로 추출 — 공식
    # API 가 없어 _used / _pool 속성을 직접 읽음. 실패해도 기본 metadata 반환.
    # ────────────────────────────────────────────────────────────────
    def get_pool_stats(self) -> dict:
        if self._pool is None:
            return {"initialized": False, "min": getattr(self, "_pool_min", 1),
                    "max": getattr(self, "_pool_max", 5),
                    "in_use": None, "idle": None}
        info = {
            "initialized": True,
            "min": getattr(self, "_pool_min", 1),
            "max": getattr(self, "_pool_max", 5),
            "in_use": None, "idle": None,
        }
        # psycopg2 ThreadedConnectionPool 내부 속성 (private, 안전하게 try)
        try:
            pool = self._pool
            used = getattr(pool, "_used", None)
            free = getattr(pool, "_pool", None)
            if used is not None:
                info["in_use"] = len(used)
            if free is not None:
                info["idle"] = len(free)
        except Exception:
            pass
        return info

    # ────────────────────────────────────────────────────────────────
    # 풀에서 커넥션 획득. 풀 초기화 실패 또는 획득 실패 시 None.
    # ────────────────────────────────────────────────────────────────
    def _getconn(self):
        if not self._ensure_pool():
            return None
        try:
            return self._pool.getconn()
        except Exception as e:
            self.logger.error(f"풀에서 커넥션 획득 실패: {e}")
            return None

    # ────────────────────────────────────────────────────────────────
    # 풀에 커넥션 반환. 반환 실패 시 close() 폴백.
    # ────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # 풀 초기화 트리거. MCP 우선 모드에서는 소켓 연결 선행하지 않음.
    # ────────────────────────────────────────────────────────────────
    def connect(self):
        if self.use_mcp_postgres:
            return True
        return self._ensure_pool()

    # ────────────────────────────────────────────────────────────────
    # 풀의 모든 커넥션 닫기 (시스템 종료 시 호출).
    # ────────────────────────────────────────────────────────────────
    def close(self):
        try:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None
                self.logger.info("DB 커넥션 풀 종료 완료")
        except Exception as e:
            self.logger.error(f"DatabaseHandler.close -> Pool Close ERR Desc: [{e}]")

    # ────────────────────────────────────────────────────────────────
    # 컨텍스트 매니저로 self(DatabaseHandler) 노출. db_session() 의 백엔드.
    # ────────────────────────────────────────────────────────────────
    @contextmanager
    def get_connection(self):
        connected = self.connect()
        if not connected:
            raise Exception("Failed to connect to database")
        yield self

    # ────────────────────────────────────────────────────────────────
    # direct DB 연결로 쿼리 실행 공통 래퍼.
    # commit=True: INSERT/UPDATE/DELETE, fetch_mode='all'/'one': SELECT.
    # ────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # INSERT/UPDATE/DELETE 등 commit 쿼리 실행. MCP 우선 → direct fallback.
    # ────────────────────────────────────────────────────────────────
    def execute_query(self, query, vals=None):
        self.logger.debug(f"[SQL-EXECUTE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        if self.use_mcp_postgres:
            try:
                self._execute_mcp_query(query, vals)
                return True
            except Exception as mcp_err:
                self._log_mcp_fallback(mcp_err)

        return self._run_direct("execute_query", query, vals, False, commit=True)

    # ────────────────────────────────────────────────────────────────
    # SELECT 전체 행 조회. as_dict=True 면 RealDictCursor 로 dict list 반환.
    # MCP 우선 → direct fallback.
    # ────────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────────
    # SELECT 단일 행 조회 (RealDictCursor). MCP 우선 → direct fallback.
    # ────────────────────────────────────────────────────────────────
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


# ═════════════════════════════════
# 전역 데이터베이스 핸들러 인스턴스
# ═════════════════════════════════
db = DatabaseHandler()


# ────────────────────────────────────────────────────────────────────
# DatabaseHandler 의 모듈 레벨 컨텍스트 매니저 — db_session() 으로 사용.
# 예외 발생 시 traceback 로깅 후 재발생.
# ────────────────────────────────────────────────────────────────────
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
