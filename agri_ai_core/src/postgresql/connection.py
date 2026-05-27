# ════════════════════════════════════════════════════════════════════
# PostgreSQL 연결 관리 — 커넥션 풀 싱글톤 + 세션 컨텍스트 매니저.
#
# MCP postgres 듀얼 경로는 2026-07-16 제거됐다. 사유(실측):
#   - MCP postgres 는 read-only 트랜잭션 전용이라 INSERT/UPDATE 가 원천 불가
#     ("cannot execute UPDATE in a read-only transaction") — 쓰기는 100% 실패 후
#     direct 로 폴백했다. 즉 얻는 것 없이 왕복만 낭비.
#   - 호출마다 npx 프로세스를 새로 띄워 쿼리당 10.67s (direct psycopg2 0.012s, 875배).
#     릴레이 유지 쓰기가 5초 주기이므로 켜는 순간 제어 루프가 붕괴한다.
#   - LLM 의 DB 관리는 MCP 가 아니라 전용 도구(db_read_query/db_write_query/
#     db_list_tables/db_describe_table)가 담당하며 그쪽이 기능·속도 모두 우월하다.
#   따라서 "켜면 시스템이 무너지는 스위치"를 남기지 않기 위해 경로째 제거한다.
# --->
# DatabaseHandler        : 싱글톤 DB 핸들러 (direct psycopg2)
#   __new__              : 싱글톤 인스턴스 보장
#   __init__             : 1회 한정 초기화 (호스트/포트/풀)
#   _safe_positive_int   : 환경변수 양의 정수 파싱 (실패 시 default)
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
    # 1회 한정 초기화 — 호스트/포트/풀 로드.
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
    # 현재 풀 사용 상태 스냅샷 (관측성).
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
    # 풀 초기화 트리거.
    # ────────────────────────────────────────────────────────────────
    def connect(self):
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
    # INSERT/UPDATE/DELETE 등 commit 쿼리 실행.
    # ────────────────────────────────────────────────────────────────
    def execute_query(self, query, vals=None):
        self.logger.debug(f"[SQL-EXECUTE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        return self._run_direct("execute_query", query, vals, False, commit=True)

    # ────────────────────────────────────────────────────────────────
    # SELECT 전체 행 조회. as_dict=True 면 RealDictCursor 로 dict list 반환.
    # direct psycopg2 실행.
    # ────────────────────────────────────────────────────────────────
    def fetch_all(self, query: str, vals: Optional[Tuple[Any, ...]] = None, as_dict: bool = False):
        self.logger.debug(f"[SQL-FETCH_ALL] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

        return self._run_direct("fetch_all", query, vals, [],
                                cursor_factory=RealDictCursor if as_dict else None, fetch_mode="all")

    # ────────────────────────────────────────────────────────────────
    # SELECT 단일 행 조회 (RealDictCursor). direct psycopg2 실행.
    # ────────────────────────────────────────────────────────────────
    def fetch_one(self, query, vals=None):
        self.logger.debug(f"[SQL-FETCH_ONE] 실행할 쿼리: \n{query} \n파라미터: \n{vals}\n")

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
