# ══════════════════════════════════════════════════════════════════════════════
# 운영 소스 변경 도구 — 로컬 AI 가 agri_ai_core 소스를 스스로 수정한다 (4단계).
#
# 설계(농장주 지시 2026-07-17): LLM 이 개선을 코드로 직접 반영하게 한다.
#   핵심은 "LLM 을 믿는 것"이 아니라 "되돌릴 수 있게 만드는 것" 이다.
#
# 실행 순서 (하나라도 실패하면 원상복구):
#   1. deny-list 검사 — 자기 안전장치·시크릿은 건드릴 수 없다
#   2. git 스냅샷 (변경 전 파일 내용 보존)      ← 롤백 지점
#   3. ast.parse 구문 검증                      ← 실패 시 파일을 쓰지 않음
#   4. write
#   5. pytest 실행 (기본 전체)                  ← 실패 시 자동 원복
#   6. 감사기록 (llm_source_audit — 변경 전/후 전문 보존)
#   ※ 서비스 반영은 restart_service(3단계)로 별도 — 여기서 자동 재기동하지 않는다
#     (여러 파일을 고친 뒤 한 번에 반영하는 게 정상 흐름이므로).
#
# ⛔ DENY 목록은 LLM 이 자기 제약을 스스로 제거하는 것을 막는 최후 방어선이다.
#   자율의 전제는 되돌릴 수 있음이고, 되돌림 장치를 지울 수 있으면 전제가 무너진다.
#
# 파일 시작 함수 목록:
#   _safe_source_path : 프로젝트 안 실경로 + .py 검증
#   _deny_reason      : 보호 대상 판정
#   _audit            : 감사기록 (변경 전/후 전문)
#   _run_pytest       : 테스트 실행 → (통과여부, 요약)
#   list_source_edits : 최근 변경 이력
#   edit_source       : 소스 변경 (검증→쓰기→테스트→실패 시 자동 원복)
#   revert_source     : 감사기록의 변경 전 내용으로 수동 원복
# ══════════════════════════════════════════════════════════════════════════════
import ast
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_ROOT = "/workspace/jayeondeule"
_PYTHON = f"{_ROOT}/venv/bin/python"
_PYTEST_TIMEOUT = 600
_MAX_SOURCE = 400000

# ⛔ 보호 대상 — LLM 이 자기 안전장치/시크릿을 지우지 못하게 한다.
#   경로 일부만 일치해도 차단(부분 문자열).
_DENY_PATHS = (
    # 4단계 자신 — 이걸 고칠 수 있으면 아래 모든 보호가 무의미해진다
    "src/ai/tools_source_edit.py",
    # 2·3단계 경계 (scripts/llm 한정, stop 미구현)
    "src/ai/tools_script.py",
    "src/ai/tools_service.py",
    # 물리 안전·비상·관리자지시 — 농장 설비 보호
    "src/control/interlock.py",
    "src/control/environment_logic.py",
    "src/control/relay_manager.py",
    "src/control/admin_directive.py",
    # DB 보호테이블 정의
    "src/ai/tools_db.py",
    # 시크릿·설정
    ".env", "mcp.json", "kakao_notify.py",
)
_DENY_RE = re.compile(r"(^|/)\.env|\.pem$|\.key$|secret|credential|passwd", re.I)

_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS llm_source_audit (
    id           BIGSERIAL PRIMARY KEY,
    executed_at  TIMESTAMP NOT NULL DEFAULT now(),
    path         VARCHAR(300),
    reason       TEXT,
    before_text  TEXT,
    after_text   TEXT,
    tests_passed BOOLEAN,
    reverted     BOOLEAN DEFAULT FALSE,
    detail       TEXT
)
"""


# ────────────────────────────────────────────────────────────────────
# 프로젝트 루트 안의 .py 실경로 검증.
# ────────────────────────────────────────────────────────────────────
def _safe_source_path(path: str) -> Optional[str]:
    if not path:
        return None
    p = os.path.realpath(os.path.join(_ROOT, path))
    if not p.startswith(os.path.realpath(_ROOT) + os.sep):
        return None
    if not p.endswith(".py"):
        return None
    return p


# ────────────────────────────────────────────────────────────────────
# 보호 대상 판정. 허용이면 None.
# ────────────────────────────────────────────────────────────────────
def _deny_reason(rel: str) -> Optional[str]:
    norm = rel.replace("\\", "/")
    if _DENY_RE.search(norm):
        return f"{rel} 은 시크릿 계열이라 변경할 수 없습니다."
    for d in _DENY_PATHS:
        if d in norm:
            return (f"{rel} 은 보호 대상입니다({d}) — 안전장치(자동복구·인터록·비상가드·"
                    f"보호테이블·스크립트/서비스 경계)와 시크릿은 LLM 이 변경할 수 없습니다. "
                    f"이 파일 수정이 꼭 필요하면 농장주에게 사유를 설명하고 직접 요청하세요.")
    return None


# ────────────────────────────────────────────────────────────────────
# 감사기록 — 변경 전/후 전문 보존(복원 근거).
# ────────────────────────────────────────────────────────────────────
def _audit(path: str, reason: str, before: str, after: str,
           passed: bool, reverted: bool, detail: str) -> Optional[int]:
    # ⛔ fetch_one 은 읽기 경로라 커밋하지 않는다 — INSERT..RETURNING 을 fetch_one
    #   으로 하면 id 는 돌아오지만 행이 롤백된다(2026-07-17 실측). 반드시 커밋하는
    #   execute_query 로 INSERT 하고 id 는 별도 조회한다.
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(_CREATE_AUDIT, ())
            d.execute_query(
                "INSERT INTO llm_source_audit "
                "(path, reason, before_text, after_text, tests_passed, reverted, detail) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (path[:300], (reason or "")[:500], before, after, passed, reverted,
                 (detail or "")[:4000]))
            row = d.fetch_one(
                "SELECT id FROM llm_source_audit WHERE path=%s "
                "ORDER BY id DESC LIMIT 1", (path[:300],))
        return (row or {}).get("id")
    except Exception as e:
        logger.warning(f"[소스변경] 감사기록 실패: {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# pytest 실행 → (통과여부, 요약줄).
# ────────────────────────────────────────────────────────────────────
def _run_pytest(target: str = "tests/") -> Tuple[bool, str]:
    try:
        r = subprocess.run([_PYTHON, "-m", "pytest", target, "-q", "--no-header", "-x"],
                           capture_output=True, text=True, timeout=_PYTEST_TIMEOUT, cwd=_ROOT)
        tail = [l for l in (r.stdout or "").strip().splitlines() if l.strip()][-3:]
        return r.returncode == 0, " | ".join(tail)[:600]
    except subprocess.TimeoutExpired:
        return False, f"pytest {_PYTEST_TIMEOUT}초 초과"
    except Exception as e:
        return False, str(e)


# ────────────────────────────────────────────────────────────────────
# 최근 소스 변경 이력.
# ────────────────────────────────────────────────────────────────────
def list_source_edits(limit: int = 10) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(_CREATE_AUDIT, ())
            rows = d.fetch_all(
                "SELECT id, to_char(executed_at,'MM-DD HH24:MI') t, path, reason, "
                "tests_passed, reverted FROM llm_source_audit "
                "ORDER BY id DESC LIMIT %s", (max(1, min(int(limit or 10), 50)),),
                as_dict=True) or []
        return {"success": True, "count": len(rows), "edits": rows,
                "note": "revert_source(audit_id) 로 변경 전 내용으로 되돌릴 수 있습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 운영 소스 변경. content 는 파일 전문(부분 패치 아님).
# 구문 오류·테스트 실패 시 자동으로 원래 내용으로 되돌린다.
# ────────────────────────────────────────────────────────────────────
def edit_source(path: str, content: str, reason: str = "",
                test_target: str = "tests/") -> Dict[str, Any]:
    rel = (path or "").strip().lstrip("/")
    p = _safe_source_path(rel)
    if not p:
        return {"success": False,
                "error": "프로젝트 안의 .py 파일만 변경 가능합니다 (경로 이탈 불가)."}

    denied = _deny_reason(rel)
    if denied:
        logger.warning(f"[소스변경] 보호 대상 거부: {rel}")
        return {"success": False, "error": denied}

    if not content or not content.strip():
        return {"success": False, "error": "content(파일 전문)가 필요합니다."}
    if len(content) > _MAX_SOURCE:
        return {"success": False, "error": f"본문이 {_MAX_SOURCE}자를 초과합니다."}

    try:
        ast.parse(content)
    except SyntaxError as e:
        return {"success": False,
                "error": f"구문 오류 — 파일을 변경하지 않았습니다. {e.lineno}행: {e.msg}"}

    if not os.path.isfile(p):
        return {"success": False,
                "error": f"없는 파일: {rel}. 신규 파일 생성은 아직 지원하지 않습니다."}

    before = open(p, encoding="utf-8").read()
    if before == content:
        return {"success": False, "error": "내용이 기존과 동일합니다."}

    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"쓰기 실패: {e}"}

    passed, summary = _run_pytest(test_target)
    if not passed:
        # 자동 원복 — 깨진 코드를 운영에 남기지 않는다
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(before)
            restored = True
        except Exception as e:
            restored = False
            logger.error(f"[소스변경] 자동 원복 실패! {rel}: {e}")
        aid = _audit(rel, reason, before, content, False, restored, summary)
        logger.warning(f"[소스변경] 테스트 실패 → {'원복' if restored else '원복실패'} {rel}")
        return {"success": False, "path": rel, "audit_id": aid,
                "tests_passed": False, "reverted": restored,
                "error": (f"테스트 실패로 자동 원복했습니다. 결과: {summary}"
                          if restored else
                          f"테스트 실패 + 원복까지 실패했습니다(수동 조치 필요). {summary}"),
                "message": "실패 원인을 보고 content 를 고쳐 다시 시도하세요."}

    aid = _audit(rel, reason, before, content, True, False, summary)
    logger.info(f"[소스변경] {rel} 변경 성공 (audit #{aid}) 사유={reason[:60]!r}")
    return {"success": True, "path": rel, "audit_id": aid, "tests_passed": True,
            "tests": summary,
            "message": (f"{rel} 변경 완료 — 테스트 통과. 감사기록 #{aid} (변경 전 내용 보존, "
                        f"revert_source 로 원복 가능). 서비스에 반영하려면 "
                        f"restart_service 를 호출하세요.")}


# ────────────────────────────────────────────────────────────────────
# 감사기록의 변경 전 내용으로 수동 원복.
# ────────────────────────────────────────────────────────────────────
def revert_source(audit_id: int, reason: str = "") -> Dict[str, Any]:
    try:
        # 인자검증을 DB 접근 전에 — 잘못된 audit_id 가 db_session 안에서 int() 예외를
        # 일으켜 무의미한 ERROR+스택트레이스를 남기던 소음을 제거(정직한 거부 반환).
        try:
            audit_id = int(audit_id)
        except (TypeError, ValueError):
            return {"success": False,
                    "error": "audit_id 는 정수여야 합니다 (list_source_edits 로 id 확인)."}
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            row = d.fetch_one(
                "SELECT path, before_text FROM llm_source_audit WHERE id=%s",
                (audit_id,))
        if not row:
            return {"success": False, "error": f"없는 감사기록: {audit_id}"}
        rel, before = row["path"], row["before_text"]
        p = _safe_source_path(rel)
        if not p or _deny_reason(rel):
            return {"success": False, "error": f"원복 불가 경로: {rel}"}
        cur = open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
        with open(p, "w", encoding="utf-8") as f:
            f.write(before)
        _audit(rel, f"revert #{audit_id}: {reason}", cur, before, True, True, "manual revert")
        logger.info(f"[소스변경] #{audit_id} 원복 {rel}")
        return {"success": True, "path": rel,
                "message": f"{rel} 을 감사기록 #{audit_id} 의 변경 전 내용으로 되돌렸습니다. "
                           f"restart_service 로 반영하세요."}
    except Exception as e:
        return {"success": False, "error": str(e)}
