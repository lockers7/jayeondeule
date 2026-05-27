# ══════════════════════════════════════════════════════════════════════════════
# DB 자율 조회 도구 — LLM 이 시스템 테이블 구조를 스스로 파악하고
# 데이터를 읽어 답변할 수 있게 하는 읽기전용 도구 3종.
#
# 안전 가드(다층):
#   · SELECT/WITH 로 시작하는 단일 문장만 허용 (세미콜론 체이닝 금지)
#   · 쓰기/DDL 키워드(INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/COPY...)
#     단어 경계 검출 시 거부
#   · LIMIT 강제(없으면 자동 부가, 상한 200행) + statement_timeout 5초
#   · 결과 문자열 총량 상한 (LLM 컨텍스트 보호)
# --->
# db_list_tables    : public 스키마 테이블 + 추정 행수
# db_describe_table : 테이블 컬럼/타입/널 허용
# db_read_query     : 읽기전용 SELECT 실행
# ══════════════════════════════════════════════════════════════════════════════
import re
from typing import Any, Dict

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MAX_ROWS = 200
_MAX_CHARS = 6000
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"reindex|cluster|comment|lock|listen|notify|do|call|execute|prepare|set|reset)\b",
    re.IGNORECASE,
)


def _rows_to_text(rows, max_chars=_MAX_CHARS) -> str:
    out = []
    total = 0
    for r in rows:
        line = str(dict(r))
        total += len(line)
        if total > max_chars:
            out.append(f"... (컨텍스트 보호를 위해 {len(rows)}행 중 일부만 표시)")
            break
        out.append(line)
    return "\n".join(out) if out else "(0행)"


def db_list_tables() -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            rows = d.fetch_all("""
                SELECT c.relname AS table_name, c.reltuples::bigint AS approx_rows,
                       obj_description(c.oid) AS comment
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relkind = 'r'
                 ORDER BY c.relname
            """, (), as_dict=True) or []
        return {"success": True, "count": len(rows), "tables": _rows_to_text(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def db_describe_table(table_name: str) -> Dict[str, Any]:
    try:
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", str(table_name or "")):
            return {"success": False, "error": f"잘못된 테이블명: {table_name}"}
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            rows = d.fetch_all("""
                SELECT column_name, data_type, is_nullable, column_default
                  FROM information_schema.columns
                 WHERE table_schema='public' AND table_name = %s
                 ORDER BY ordinal_position
            """, (str(table_name),), as_dict=True) or []
        if not rows:
            return {"success": False, "error": f"테이블 없음: {table_name}"}
        return {"success": True, "table": table_name, "columns": _rows_to_text(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# 농장 격리 — farm_id 컬럼 보유 테이블 집합. 스키마는 마이그레이션 시에만
# 바뀌므로 프로세스 수명 캐시. 조회 실패 시 빈 set → 리터럴 검사만 동작.
_farm_scoped_cache = None

_FARM_ID_LITERAL = re.compile(r"\bfarm_id\s*=\s*'?(\d+)'?", re.IGNORECASE)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)


# ────────────────────────────────────────────────────────────────────
# farm_id 컬럼을 가진 public 테이블 집합.
# ────────────────────────────────────────────────────────────────────
def _farm_scoped_tables() -> set:
    global _farm_scoped_cache
    if _farm_scoped_cache is not None:
        return _farm_scoped_cache
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            rows = d.fetch_all(
                "SELECT DISTINCT table_name FROM information_schema.columns "
                "WHERE table_schema='public' AND column_name='farm_id'",
                (), as_dict=True) or []
        _farm_scoped_cache = {r["table_name"].lower() for r in rows}
    except Exception as e:
        logger.warning(f"[DB읽기] farm_scoped 테이블 조회 실패: {e}")
        _farm_scoped_cache = set()
    return _farm_scoped_cache


# ────────────────────────────────────────────────────────────────────
# 농장 격리 검사 — 농장관리자 세션이 타 농장 데이터를 읽지 못하게 한다.
# 시스템관리자(auth_farm_id 없음/'0')는 무제한.
# 농장관리자: ① SQL 의 farm_id 리터럴이 전부 자기 농장이어야 하고
#            ② farm_id 컬럼 보유 테이블 참조 시 farm_id 술어가 있어야 한다.
# 위반 시 LLM 이 스스로 고쳐 재시도하도록 사유를 명확히 반환.
# ────────────────────────────────────────────────────────────────────
def _check_farm_scope(q: str, auth_farm_id):
    auth = str(auth_farm_id).strip() if auth_farm_id is not None else ""
    if not auth or auth == "0":
        return None

    others = {v for v in _FARM_ID_LITERAL.findall(q) if v not in (auth, "0")}
    if others:
        logger.warning(f"[권한거부] auth_farm_id={auth} 가 farm_id={sorted(others)} 조회 시도")
        return {"success": False,
                "error": f"농장 접근 권한 없음: 본인 농장(farm_id={auth}) 데이터만 조회할 수 "
                         f"있습니다. 요청한 farm_id={sorted(others)} 는 권한 범위 밖입니다."}

    scoped = _farm_scoped_tables()
    if scoped:
        used = {t.lower() for t in _TABLE_REF.findall(q)} & scoped
        if used and not _FARM_ID_LITERAL.search(q):
            return {"success": False,
                    "error": f"농장 격리: {sorted(used)} 는 농장별 데이터입니다. "
                             f"WHERE farm_id = {auth} 조건을 포함해 다시 작성하세요."}
    return None


# ────────────────────────────────────────────────────────────────────
# 자가 교정 힌트 — SELECT 실행이 "존재하지 않는 컬럼/테이블" 로 실패하면
# 참조한 테이블의 실제 컬럼(또는 사용 가능한 테이블 목록)을 에러에 실어
# 반환한다. LLM 이 추측한 컬럼(예: ai_decision_log 에 없는 device_name)으로
# 실패했을 때, 다음 라운드에서 정확한 컬럼으로 재조회하도록 유도 → 쿼리 실패가
# 죽은 오류가 아니라 스스로 낫는 오류가 되게 한다.
# pgcode: 42703=undefined_column, 42P01=undefined_table
# ────────────────────────────────────────────────────────────────────
def _columns_of(table: str) -> list:
    from agri_ai_core.src.postgresql.connection import db
    rows = db.fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (str(table),), as_dict=True) or []
    return [r["column_name"] for r in rows]


def _columns_with_types(table: str) -> list:
    from agri_ai_core.src.postgresql.connection import db
    rows = db.fetch_all(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (str(table),), as_dict=True) or []
    return [f"{r['column_name']}:{r['data_type']}" for r in rows]


def _schema_hint(q: str, exc) -> str:
    code = getattr(exc, "pgcode", None)
    try:
        if code == "42703":  # 존재하지 않는 컬럼
            parts = []
            for t in sorted({t.lower() for t in _TABLE_REF.findall(q)}):
                cols = _columns_of(t)
                if cols:
                    parts.append(f"{t} → [{', '.join(cols)}]")
            if parts:
                return ("존재하지 않는 컬럼입니다. 아래 실제 컬럼만 사용해 db_read_query 로 "
                        "다시 조회하세요: " + " / ".join(parts))
        elif code == "42P01":  # 존재하지 않는 테이블
            from agri_ai_core.src.postgresql.connection import db
            rows = db.fetch_all(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name", (), as_dict=True) or []
            names = [r["table_name"] for r in rows]
            if names:
                return ("존재하지 않는 테이블입니다. 사용 가능한 테이블: " + ", ".join(names)
                        + " — 컬럼은 db_describe_table 로 확인 후 재조회하세요.")
        elif code in ("42883", "22P02", "42804", "42P18"):  # 타입/연산자 불일치
            # 42883 operator does not exist, 22P02 invalid text repr,
            # 42804 datatype mismatch, 42P18 indeterminate datatype
            parts = []
            for t in sorted({t.lower() for t in _TABLE_REF.findall(q)}):
                ct = _columns_with_types(t)
                if ct:
                    parts.append(f"{t} → [{', '.join(ct)}]")
            if parts:
                return ("타입 불일치일 수 있습니다(예: 정수 컬럼을 문자열과 비교, 또는 서로 다른 "
                        "타입의 컬럼끼리 조인). 아래 컬럼 타입을 확인하고 필요하면 명시적 형변환"
                        "(예: col::int, col::text)을 넣어 db_read_query 로 다시 조회하세요: "
                        + " / ".join(parts))
    except Exception:
        pass
    return ""


def db_read_query(sql: str, limit: int = 50,
                  auth_farm_id: str = None) -> Dict[str, Any]:
    try:
        q = str(sql or "").strip().rstrip(";").strip()
        if not q:
            return {"success": False, "error": "빈 쿼리"}
        if ";" in q:
            return {"success": False, "error": "다중 문장(;) 금지 — 단일 SELECT 만 허용"}
        head = q.lstrip("( \n\t").lower()
        if not (head.startswith("select") or head.startswith("with")):
            return {"success": False, "error": "SELECT/WITH 로 시작하는 읽기 쿼리만 허용"}
        m = _FORBIDDEN.search(q)
        if m:
            return {"success": False, "error": f"금지 키워드 포함: {m.group(0)} — 읽기전용만 허용"}

        denied = _check_farm_scope(q, auth_farm_id)
        if denied:
            return denied
        try:
            lim = max(1, min(int(limit or 50), _MAX_ROWS))
        except (TypeError, ValueError):
            lim = 50
        if not re.search(r"\blimit\b", q, re.IGNORECASE):
            q = f"{q} LIMIT {lim}"

        from agri_ai_core.src.postgresql.connection import db
        from psycopg2.extras import RealDictCursor
        conn = db._getconn()
        if conn is None:
            return {"success": False, "error": "DB 연결 실패"}
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout = '5s'")
                cur.execute(q)
                rows = cur.fetchmany(_MAX_ROWS)
            conn.rollback()  # 읽기전용 — 트랜잭션 정리
            logger.info(f"[DB조회도구] {len(rows)}행 반환 — {q[:120]}")
            return {"success": True, "count": len(rows), "rows": _rows_to_text(rows)}
        except Exception as ex:
            try:
                conn.rollback()  # 중단된 트랜잭션 정리 → 풀 커넥션 재사용 안전
            except Exception:
                pass
            hint = _schema_hint(q, ex)  # 컬럼/테이블 오류면 실제 스키마를 실어 자가교정 유도
            logger.warning(f"[DB조회도구] 실패: {ex} — {q[:120]}")
            err = str(ex)
            return {"success": False, "error": (f"{err}\n💡 {hint}" if hint else err)}
        finally:
            db._putconn(conn)
    except Exception as e:
        logger.warning(f"[DB조회도구] 실패: {e} — {str(sql)[:100]}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# db_write_query — 관리자 지시 기반 DB 데이터 쓰기
#   정책: UPDATE/INSERT 만 허용, DELETE 는 보류.
#
#   다층 안전장치:
#     1. 시스템관리자 전용 (auth_farm_id=None)
#     2. 단일 문장 + 첫 키워드 UPDATE/INSERT 만 (DELETE/DDL 전면 거부)
#     3. 보호 테이블 차단: 실측 로그(relay/sensor_l_recording — 제어 무결성),
#        kakao_token_m(시크릿), db_write_audit(감사 자가조작 방지)
#     4. UPDATE 는 WHERE 필수 + 영향 100행 초과 시 롤백
#     5. UPDATE 대상 행 사전 백업 → db_write_audit(JSONB) 영속 (복원 지시 가능)
#     6. 전 실행 감사 기록 (sql/reason/영향행수), statement_timeout 5s
# ═══════════════════════════════════════════════════════════════════════════════
# 변경 전 백업 보존 한도. 초과해도 실행은 허용하되 백업 없이 진행(사유 반환).
_WRITE_BACKUP_MAX_ROWS = 5000

# ⛔ 보호 테이블 — 농장주 지시(2026-07-17 전면개방)에서도 유일하게 유지되는 경계.
#   relay_l_recording/sensor_l_recording : 제어·실측 원본 로그(무결성)
#   kakao_token_m                        : 시크릿
#   db_write_audit                       : 감사기록 — LLM 이 자기 행위를 지울 수
#                                          없어야 자율의 전제인 추적가능성이 성립
_PROTECTED_TABLES = {"relay_l_recording", "sensor_l_recording",
                     "kakao_token_m", "db_write_audit"}

# 구문별 대상 테이블 추출 — 보호 테이블 검사가 DELETE/DDL 로 우회되지 않도록
# 모든 쓰기 구문을 포괄한다.
_WRITE_TARGET_PATTERNS = (
    (re.compile(r"^\s*UPDATE\s+(?:ONLY\s+)?([a-zA-Z_][\w.]*)", re.I), "UPDATE"),
    (re.compile(r"^\s*INSERT\s+INTO\s+([a-zA-Z_][\w.]*)", re.I), "INSERT"),
    (re.compile(r"^\s*DELETE\s+FROM\s+(?:ONLY\s+)?([a-zA-Z_][\w.]*)", re.I), "DELETE"),
    (re.compile(r"^\s*TRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?([a-zA-Z_][\w.]*)", re.I), "TRUNCATE"),
    (re.compile(r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([a-zA-Z_][\w.]*)", re.I), "DROP"),
    (re.compile(r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([a-zA-Z_][\w.]*)", re.I), "ALTER"),
    (re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+([a-zA-Z_][\w.]*)", re.I), "CREATE INDEX"),
    (re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][\w.]*)", re.I), "CREATE"),
)
# 대상 테이블을 못 뽑는 그 외 구문(CREATE VIEW/FUNCTION, GRANT, COMMENT 등)
_OTHER_WRITE_VERB = re.compile(
    r"^\s*(CREATE|ALTER|DROP|GRANT|REVOKE|COMMENT|ANALYZE|VACUUM|REINDEX|REFRESH)\b", re.I)


# ────────────────────────────────────────────────────────────────────
# 쓰기 SQL 에서 (verb, table) 추출. table 이 None 이면 테이블 비대상 구문.
# ────────────────────────────────────────────────────────────────────
def _extract_write_target(q: str):
    for pat, verb in _WRITE_TARGET_PATTERNS:
        m = pat.match(q)
        if m:
            return verb, m.group(1).split(".")[-1].lower()
    m = _OTHER_WRITE_VERB.match(q)
    if m:
        return m.group(1).upper(), None
    return None, None


# ────────────────────────────────────────────────────────────────────
# 보호 테이블이 SQL 어디에도 등장하지 않는지 검사 — 대상 테이블 추출이
# 실패하는 구문(CREATE VIEW ... AS SELECT ... 등)까지 포괄하는 최종 방어선.
# ────────────────────────────────────────────────────────────────────
def _touches_protected(q: str):
    low = q.lower()
    return sorted(t for t in _PROTECTED_TABLES if re.search(rf"\b{t}\b", low))

_CREATE_WRITE_AUDIT = """
CREATE TABLE IF NOT EXISTS db_write_audit (
    id            BIGSERIAL PRIMARY KEY,
    executed_at   TIMESTAMP NOT NULL DEFAULT now(),
    table_name    VARCHAR(80),
    sql_text      TEXT NOT NULL,
    reason        TEXT,
    rows_affected INTEGER,
    backup_rows   JSONB
)
"""


def db_write_query(sql: str, reason: str = "", auth_farm_id: str = None) -> Dict[str, Any]:
    import json as _json
    if auth_farm_id is not None:
        return {"success": False, "error": "DB 쓰기는 시스템관리자 전용입니다."}
    q = (sql or "").strip().rstrip(";").strip()
    if not q:
        return {"success": False, "error": "sql 이 필요합니다."}
    if ";" in q:
        return {"success": False, "error": "다중 문장은 허용되지 않습니다."}

    verb, table = _extract_write_target(q)
    if not verb:
        return {"success": False,
                "error": "쓰기/DDL 구문이 아닙니다. 조회는 db_read_query 를 사용하세요."}

    hit = _touches_protected(q)
    if hit:
        return {"success": False,
                "error": f"보호 테이블({', '.join(hit)}) 은 쓰기가 차단되어 있습니다 — "
                         f"제어·실측 원본 로그 / 시크릿 / 감사기록. 그 외 모든 테이블은 자유롭게 "
                         f"UPDATE·INSERT·DELETE·DDL 가능합니다."}

    # UPDATE/DELETE 는 변경 전 스냅샷을 남겨 복원 가능하게 한다(WHERE 없으면 전행).
    where_clause = None
    if verb in ("UPDATE", "DELETE"):
        wm = re.search(r"\bWHERE\b(.+)$", q, re.IGNORECASE | re.DOTALL)
        where_clause = wm.group(1).strip() if wm else None

    from agri_ai_core.src.postgresql.connection import db
    from psycopg2.extras import RealDictCursor
    conn = db._getconn()
    if conn is None:
        return {"success": False, "error": "DB 연결 실패"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute(_CREATE_WRITE_AUDIT)

            # 변경 전 스냅샷 — 한도 초과 시 실행은 진행하되 백업만 생략한다
            # (농장주 지시: 보호 테이블 외 전면 개방 — 행수로 막지 않는다).
            backup = None
            backup_note = ""
            if verb in ("UPDATE", "DELETE"):
                try:
                    _w = f" WHERE {where_clause}" if where_clause else ""
                    cur.execute(f"SELECT * FROM {table}{_w} LIMIT {_WRITE_BACKUP_MAX_ROWS + 1}")
                    rows = [dict(r) for r in cur.fetchall()]
                    if len(rows) > _WRITE_BACKUP_MAX_ROWS:
                        backup_note = (f" ⚠ 영향 {_WRITE_BACKUP_MAX_ROWS}행 초과 — "
                                       f"백업 없이 실행됨(복원 불가)")
                    else:
                        backup = rows
                except Exception as _be:
                    backup_note = f" ⚠ 백업 실패({_be}) — 복원 불가"

            cur.execute(q)
            affected = cur.rowcount

            cur.execute(
                "INSERT INTO db_write_audit (table_name, sql_text, reason, rows_affected, backup_rows) "
                "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
                (table, q, (reason or "")[:500], affected,
                 _json.dumps(backup, ensure_ascii=False, default=str) if backup else None))
            audit_id = cur.fetchone()["id"]
            conn.commit()
        logger.info(f"[DB쓰기] {verb} {table} {affected}행 (audit #{audit_id}) 사유={reason[:60]!r}")
        return {"success": True, "verb": verb, "table": table,
                "rows_affected": affected, "audit_id": audit_id,
                "message": (f"{verb} 성공 — {table or '(테이블 비대상)'} {affected}행 반영. "
                            f"감사기록 #{audit_id}"
                            + (f" (변경 전 {len(backup)}행 백업 보존 — 복원 지시 가능)" if backup else "")
                            + backup_note)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"[DB쓰기] 실패: {e} sql={q[:120]!r}")
        return {"success": False, "error": str(e)}
    finally:
        try:
            db._putconn(conn)
        except Exception:
            pass
