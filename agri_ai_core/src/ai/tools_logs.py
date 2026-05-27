# ══════════════════════════════════════════════════════════════════════════════
# 로그 분석 도구 (읽기 전용) — LLM 의 운영 로그 자율 조회·분석
#
# 목적: 농장주가 "오늘 에러 있었나", "배수밸브 제어 로그 보여줘", "LLM 실패 몇 건"
#   처럼 물으면 LLM 이 실제 로그를 근거로 답하게 한다.
#
# source_* 도구로 대체 불가한 이유:
#   - logs/ 는 source_* 의 제외 디렉토리이고, 애초에 캡(400줄)이 맞지 않는다.
#   - 로그는 3GB 규모(하루 56만 줄, 파일당 80MB). 통째 읽기가 불가능해
#     grep/tail/집계로만 접근해야 한다.
#
# 보안:
#   - logs 디렉토리(/workspace/jayeondeule/logs) 밖 접근 불가 (realpath 검증)
#   - 파일명 경로조작(.. /) 차단, .log 계열만 허용
#   - 시크릿 값 마스킹 (password/token/secret/key 등)
#   - 응답 크기 캡 (기본 50줄 / 최대 200줄 / 12000자)
#
# 파일 시작 함수 목록:
#   _log_dir          : 로그 루트 경로
#   _safe_log_file    : 로그 루트 안 실경로 검증 + 확장자 제한
#   _resolve_targets  : log_type/date → 대상 파일 (date 미지정 시 최신)
#   _mask_secrets     : 시크릿 값 마스킹
#   _cap              : 줄수/문자수 캡 적용
#   list_log_files    : 조회 가능한 로그 파일 목록 + 크기/수정시각
#   search_logs       : grep 기반 검색 (query/level/date/tail) + 전체 건수 집계
# ══════════════════════════════════════════════════════════════════════════════
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_ROOT = "/workspace/jayeondeule"
_LOG_SUBDIR = "logs"
_ALLOWED_SUFFIX = (".log",)
_LEVELS = ("ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL")

_MAX_LINES = 200
_DEFAULT_LINES = 50
_MAX_CHARS = 12000
_GREP_TIMEOUT = 20

# 로그에 섞여 들어간 시크릿 값 마스킹 — key=value / "key": "value" 양쪽 형태
_SECRET_KV = re.compile(
    r'((?:password|passwd|secret|token|api[_-]?key|client_secret|authorization)'
    r'["\']?\s*[:=]\s*["\']?)([^\s"\',}]{3,})',
    re.IGNORECASE,
)


# ────────────────────────────────────────────────────────────────────
# 로그 루트 절대경로.
# ────────────────────────────────────────────────────────────────────
def _log_dir() -> str:
    return os.path.realpath(os.path.join(_ROOT, _LOG_SUBDIR))


# ────────────────────────────────────────────────────────────────────
# 로그 루트 안의 실제 파일인지 검증. 벗어나거나 .log 가 아니면 None.
# ────────────────────────────────────────────────────────────────────
def _safe_log_file(name: str) -> Optional[str]:
    if not name:
        return None
    base = _log_dir()
    path = os.path.realpath(os.path.join(base, name))
    if not (path == base or path.startswith(base + os.sep)):
        return None
    if not path.endswith(_ALLOWED_SUFFIX):
        return None
    if not os.path.isfile(path):
        return None
    return path


# ────────────────────────────────────────────────────────────────────
# log_type + date 로 대상 로그 파일 결정.
# date 지정 시 '<type>_<date>.log', 없으면 '<type>.log'.
# date 미지정 시 해당 type 파일 중 최신 수정본. log_type 기본 'ai'.
# ────────────────────────────────────────────────────────────────────
def _resolve_targets(log_type: Optional[str], date: Optional[str]) -> List[str]:
    base = _log_dir()
    if not os.path.isdir(base):
        return []
    lt = (log_type or "ai").strip()
    if date:
        d = date.strip().lower()
        if d in ("today", "오늘"):
            d = datetime.now().strftime("%Y-%m-%d")
        cand = _safe_log_file(f"{lt}_{d}.log")
        if cand:
            return [cand]
        cand = _safe_log_file(f"{lt}.log")
        return [cand] if cand else []

    matches = []
    for fn in os.listdir(base):
        if not fn.endswith(_ALLOWED_SUFFIX):
            continue
        if fn == f"{lt}.log" or fn.startswith(f"{lt}_"):
            p = _safe_log_file(fn)
            if p:
                matches.append(p)
    if not matches:
        return []
    matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return matches[:1]


# ────────────────────────────────────────────────────────────────────
# 시크릿 값 마스킹 — 로그에 토큰/비밀번호가 찍혀 있어도 응답으로 새지 않게.
# ────────────────────────────────────────────────────────────────────
def _mask_secrets(text: str) -> str:
    return _SECRET_KV.sub(lambda m: f"{m.group(1)}***", text)


# ────────────────────────────────────────────────────────────────────
# 줄수/문자수 캡 적용 → (표시줄 list, truncated 여부).
# ────────────────────────────────────────────────────────────────────
def _cap(lines: List[str], limit: int) -> Tuple[List[str], bool]:
    out: List[str] = []
    total = 0
    truncated = len(lines) > limit
    for ln in lines[:limit]:
        ln = _mask_secrets(ln.rstrip("\n"))
        if total + len(ln) > _MAX_CHARS:
            truncated = True
            break
        out.append(ln)
        total += len(ln)
    return out, truncated


# ────────────────────────────────────────────────────────────────────
# 조회 가능한 로그 파일 목록 — 이름/크기/최종수정. LLM 이 대상을 고르는 용도.
# ────────────────────────────────────────────────────────────────────
def list_log_files() -> Dict[str, Any]:
    try:
        base = _log_dir()
        if not os.path.isdir(base):
            return {"success": False, "error": "로그 디렉토리 없음"}
        rows = []
        for fn in sorted(os.listdir(base)):
            p = _safe_log_file(fn)
            if not p:
                continue
            st = os.stat(p)
            rows.append({
                "file": fn,
                "size_mb": round(st.st_size / 1048576, 1),
                "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        rows.sort(key=lambda r: r["modified"], reverse=True)
        return {"success": True, "count": len(rows), "files": rows[:40],
                "note": "search_logs(log_type,date) 로 조회. log_type 예: ai, web, scheduler"}
    except Exception as e:
        logger.warning(f"[로그도구] list_log_files 실패: {e}")
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 로그 검색/조회 — 3GB 규모를 grep/tail 로만 접근한다.
#   query : 검색어(공백 구분 다중어 = AND). 생략 시 레벨 필터 또는 최근 조회.
#   level : ERROR|WARNING|INFO|DEBUG|CRITICAL — 해당 레벨만.
#   date  : 'YYYY-MM-DD' | 'today'. 생략 시 해당 log_type 최신 파일.
#   tail  : True 면 매칭의 '최근' 쪽 반환(기본 True — 운영 질문은 대개 최신).
# 반환: matched(전체 매칭 건수) + lines(캡 적용 표본).
# ────────────────────────────────────────────────────────────────────
def search_logs(query: Optional[str] = None,
                level: Optional[str] = None,
                date: Optional[str] = None,
                log_type: Optional[str] = None,
                max_results: int = _DEFAULT_LINES,
                tail: bool = True) -> Dict[str, Any]:
    try:
        try:
            limit = max(1, min(int(max_results or _DEFAULT_LINES), _MAX_LINES))
        except (TypeError, ValueError):
            limit = _DEFAULT_LINES

        targets = _resolve_targets(log_type, date)
        if not targets:
            return {"success": False,
                    "error": f"대상 로그 없음 (log_type={log_type or 'ai'}, date={date or '최신'}). "
                             f"list_log_files 로 목록을 먼저 확인하세요."}
        target = targets[0]

        lv = (level or "").strip().upper()
        if lv and lv not in _LEVELS:
            return {"success": False, "error": f"level 은 {'|'.join(_LEVELS)} 중 하나"}

        words = [w for w in (query or "").split() if w][:5]

        # 조건 없음 → 최근 N줄
        if not lv and not words:
            r = subprocess.run(["tail", "-n", str(limit), target],
                               capture_output=True, text=True, timeout=_GREP_TIMEOUT)
            lines, trunc = _cap((r.stdout or "").splitlines(), limit)
            return {"success": True, "file": os.path.basename(target),
                    "mode": "tail", "matched": len(lines), "returned": len(lines),
                    "truncated": trunc, "lines": lines}

        # 레벨(있으면) 또는 첫 단어로 파일 grep → 나머지 단어는 파이프로 AND 축약
        terms = ([f"[{lv}]"] if lv else []) + words
        p = subprocess.run(
            ["grep", "-a", "-I", "--fixed-strings", "-e", terms[0], target],
            capture_output=True, text=True, timeout=_GREP_TIMEOUT)
        buf = p.stdout or ""
        for w in terms[1:]:
            if not buf:
                break
            p = subprocess.run(["grep", "-a", "-I", "--fixed-strings", "-e", w],
                               input=buf, capture_output=True, text=True,
                               timeout=_GREP_TIMEOUT)
            buf = p.stdout or ""

        all_lines = buf.splitlines()
        matched = len(all_lines)
        picked = all_lines[-limit:] if tail else all_lines[:limit]
        lines, _ = _cap(picked, limit)
        return {"success": True,
                "file": os.path.basename(target),
                "mode": "search",
                "query": query, "level": lv or None,
                "matched": matched,
                "returned": len(lines),
                "truncated": matched > len(lines),
                "lines": lines}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "로그 검색 시간 초과 — 검색어를 좁히세요"}
    except Exception as e:
        logger.warning(f"[로그도구] search_logs 실패: {e}")
        return {"success": False, "error": str(e)}
