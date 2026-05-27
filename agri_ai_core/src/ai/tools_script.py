# ══════════════════════════════════════════════════════════════════════════════
# 스크립트 작성·실행 도구 — 로컬 AI 가 스스로 분석 스크립트를 만들고 돌린다.
#
# 설계(농장주 지시 2026-07-17, 2단계):
#   전용 도구로 답할 수 없는 계산·집계·가공을 LLM 이 python 으로 직접 작성해
#   실행한다. python 코드를 사람이 미리 짜두지 않아도 되게 하는 것이 목적.
#
# 안전 경계 (⛔ 완화 금지 — 3단계 서버관리/4단계 소스변경의 전제):
#   · scripts/llm/ 밖 작성·실행 불가 (realpath 검증 — 심볼릭 링크 우회 차단)
#   · .py 만 허용
#   · 작성 시 ast.parse 구문 검증 → 실패하면 파일을 만들지 않는다
#   · 실행: 운영 venv python, sudo 없음, timeout 60s, 출력 8000자 캡
#   · 전건 감사기록 (llm_script_audit) — 무엇을 만들고 돌렸는지 추적 가능
#
# 파일 시작 함수 목록:
#   _safe_script_path : scripts/llm/ 안 실경로 검증 + .py 제한
#   _audit            : 감사기록 (best-effort — 실패해도 본 흐름 유지)
#   _cap              : 출력 상한
#   list_scripts      : 작성된 스크립트 목록
#   read_script       : 스크립트 본문 읽기
#   write_script      : 스크립트 작성/수정 (구문 검증 후)
#   run_script        : 스크립트 실행 (인자·타임아웃)
# ══════════════════════════════════════════════════════════════════════════════
import ast
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_ROOT = "/workspace/jayeondeule"
_SCRIPT_DIR = os.path.join(_ROOT, "scripts", "llm")
_PYTHON = os.path.join(_ROOT, "venv", "bin", "python")

_MAX_OUTPUT = 8000
_MAX_SOURCE = 60000
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 300

_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS llm_script_audit (
    id          BIGSERIAL PRIMARY KEY,
    executed_at TIMESTAMP NOT NULL DEFAULT now(),
    action      VARCHAR(16),
    script      VARCHAR(200),
    reason      TEXT,
    detail      TEXT
)
"""


# ────────────────────────────────────────────────────────────────────
# scripts/llm/ 안의 .py 실경로 검증. 벗어나거나 확장자가 다르면 None.
# ────────────────────────────────────────────────────────────────────
def _safe_script_path(name: str) -> Optional[str]:
    if not name:
        return None
    base = os.path.realpath(_SCRIPT_DIR)
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(base + os.sep):
        return None
    if not path.endswith(".py"):
        return None
    return path


# ────────────────────────────────────────────────────────────────────
# 감사기록 — 작성/실행 전건. 실패해도 본 흐름은 막지 않는다.
# ────────────────────────────────────────────────────────────────────
def _audit(action: str, script: str, reason: str, detail: str) -> None:
    try:
        from agri_ai_core.src.postgresql.connection import db_session
        with db_session() as d:
            d.execute_query(_CREATE_AUDIT, ())
            d.execute_query(
                "INSERT INTO llm_script_audit (action, script, reason, detail) "
                "VALUES (%s, %s, %s, %s)",
                (action, (script or "")[:200], (reason or "")[:500], (detail or "")[:4000]))
    except Exception as e:
        logger.debug(f"[스크립트] 감사기록 실패(무시): {e}")


# ────────────────────────────────────────────────────────────────────
# 출력 상한 적용.
# ────────────────────────────────────────────────────────────────────
def _cap(text: str) -> str:
    text = text or ""
    if len(text) <= _MAX_OUTPUT:
        return text
    return text[:_MAX_OUTPUT] + f"\n...(총 {len(text)}자 중 {_MAX_OUTPUT}자만 표시)"


# ────────────────────────────────────────────────────────────────────
# 작성된 스크립트 목록 (이름·크기·수정시각).
# ────────────────────────────────────────────────────────────────────
def list_scripts() -> Dict[str, Any]:
    try:
        os.makedirs(_SCRIPT_DIR, exist_ok=True)
        rows: List[Dict[str, Any]] = []
        for fn in sorted(os.listdir(_SCRIPT_DIR)):
            p = _safe_script_path(fn)
            if not p or not os.path.isfile(p):
                continue
            st = os.stat(p)
            rows.append({"script": fn, "bytes": st.st_size,
                         "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
        return {"success": True, "count": len(rows), "scripts": rows,
                "dir": "scripts/llm/",
                "note": "write_script 로 작성, run_script 로 실행."}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 스크립트 본문 읽기 — 수정 전 현재 내용 확인용.
# ────────────────────────────────────────────────────────────────────
def read_script(script: str) -> Dict[str, Any]:
    p = _safe_script_path(script)
    if not p:
        return {"success": False, "error": "scripts/llm/ 안의 .py 만 접근 가능합니다."}
    if not os.path.isfile(p):
        return {"success": False, "error": f"없는 스크립트: {script}"}
    try:
        return {"success": True, "script": script, "content": _cap(open(p, encoding="utf-8").read())}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 스크립트 작성/수정. ast.parse 로 구문을 검증해 통과한 것만 파일로 쓴다
# (깨진 코드가 디스크에 남지 않게).
# ────────────────────────────────────────────────────────────────────
def write_script(script: str, content: str, reason: str = "") -> Dict[str, Any]:
    p = _safe_script_path(script)
    if not p:
        return {"success": False,
                "error": "scripts/llm/ 안의 .py 만 작성 가능합니다 (경로 이탈 불가)."}
    if not content or not content.strip():
        return {"success": False, "error": "content 가 비어 있습니다."}
    if len(content) > _MAX_SOURCE:
        return {"success": False, "error": f"본문이 {_MAX_SOURCE}자를 초과합니다."}

    try:
        ast.parse(content)
    except SyntaxError as e:
        return {"success": False,
                "error": f"구문 오류 — 파일을 만들지 않았습니다. {e.lineno}행: {e.msg}"}

    try:
        os.makedirs(_SCRIPT_DIR, exist_ok=True)
        existed = os.path.isfile(p)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        _audit("write", script, reason, content[:4000])
        logger.info(f"[스크립트] {'수정' if existed else '작성'} {script} ({len(content)}자) 사유={reason[:60]!r}")
        return {"success": True, "script": script, "bytes": len(content),
                "action": "수정" if existed else "작성",
                "message": f"{script} {'수정' if existed else '작성'} 완료 (구문 검증 통과). "
                           f"run_script 로 실행하세요."}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 스크립트 실행 — 운영 venv python, sudo 없음, timeout 제한.
# 실패해도 예외를 밖으로 내지 않고 stdout/stderr 를 그대로 돌려준다
# (LLM 이 오류를 읽고 스스로 고치게).
# ────────────────────────────────────────────────────────────────────
def run_script(script: str, args: Optional[List[str]] = None,
               timeout: int = _DEFAULT_TIMEOUT, reason: str = "") -> Dict[str, Any]:
    p = _safe_script_path(script)
    if not p:
        return {"success": False, "error": "scripts/llm/ 안의 .py 만 실행 가능합니다."}
    if not os.path.isfile(p):
        return {"success": False,
                "error": f"없는 스크립트: {script}. list_scripts 로 확인하거나 write_script 로 작성하세요."}
    try:
        to = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))
    except (TypeError, ValueError):
        to = _DEFAULT_TIMEOUT

    argv = [str(a) for a in (args or [])]
    try:
        r = subprocess.run([_PYTHON, p, *argv], capture_output=True, text=True,
                           timeout=to, cwd=_ROOT, env=os.environ.copy())
        ok = r.returncode == 0
        _audit("run", script, reason, f"rc={r.returncode} args={argv} out={(r.stdout or '')[:1500]}")
        logger.info(f"[스크립트] 실행 {script} rc={r.returncode} ({len(r.stdout or '')}자)")
        return {"success": ok, "script": script, "returncode": r.returncode,
                "stdout": _cap(r.stdout), "stderr": _cap(r.stderr),
                "message": ("실행 성공" if ok else
                            f"종료코드 {r.returncode} — stderr 를 보고 스크립트를 고쳐 재시도하세요.")}
    except subprocess.TimeoutExpired:
        _audit("run", script, reason, f"timeout {to}s")
        return {"success": False, "script": script,
                "error": f"{to}초 내 종료하지 않아 중단했습니다. 처리량을 줄이거나 timeout 을 늘리세요."}
    except Exception as e:
        return {"success": False, "script": script, "error": str(e)}
