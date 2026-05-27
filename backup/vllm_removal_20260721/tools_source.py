# ══════════════════════════════════════════════════════════════════════════════
# 소스코드 분석 도구 (읽기 전용) — LLM 의 시스템 구조·소스 자율 탐색
#
# 목적: LLM 이 소스를 스스로 찾고 읽고 설명할 수 있게 한다.
# 전부 읽기 전용이라 무위험.
#
# 보안:
#   - 프로젝트 루트(/workspace/jayeondeule) 밖 접근 불가 (realpath 검증)
#   - 시크릿 파일 차단: .env*, *.pem, *.key, kakao 토큰 등
#   - venv/node_modules/dist/logs/.git 등 비소스 경로 제외
#   - 응답 크기 캡 (검색 60건/8000자, 읽기 400줄/12000자)
#
# 파일 시작 함수 목록:
#   _safe_path        : 루트 안 실경로 검증 + 시크릿/제외 경로 차단
#   source_list       : 디렉토리 파일 목록 (소스 확장자 위주)
#   source_search     : 프로젝트 전역 텍스트 검색 (file:line 반환)
#   source_read       : 파일 구간 읽기 (줄번호 포함)
# ══════════════════════════════════════════════════════════════════════════════
import os
import re
import subprocess
from typing import Dict, Any

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_ROOT = "/workspace/jayeondeule"
_EXCLUDE_DIRS = {"venv", "node_modules", ".git", "logs", "__pycache__",
                 ".ollama", ".vllm_models", "target", "upload",
                 "dist", "dist_new", "dist_old", "dist_old2", "dist_old3"}
_SECRET_PATTERNS = re.compile(r"(^|/)\.env|\.pem$|\.key$|secret|credential|passwd", re.I)
_SOURCE_EXTS = (".py", ".js", ".jsx", ".java", ".sql", ".sh", ".md", ".txt",
                ".json", ".yml", ".yaml", ".properties", ".conf", ".css", ".html")

_MAX_SEARCH_RESULTS = 60
_MAX_SEARCH_CHARS = 8000
_MAX_READ_LINES = 400
_MAX_READ_CHARS = 12000


def _safe_path(rel_path: str):
    """루트 내부 실경로 반환. 위반 시 (None, 사유)."""
    if not rel_path:
        return None, "경로가 필요합니다."
    p = os.path.realpath(os.path.join(_ROOT, rel_path.lstrip("/")))
    if not (p == _ROOT or p.startswith(_ROOT + "/")):
        return None, "프로젝트 루트 밖 경로는 접근할 수 없습니다."
    rel = os.path.relpath(p, _ROOT)
    parts = rel.split(os.sep)
    if any(part in _EXCLUDE_DIRS for part in parts):
        return None, f"제외 경로입니다({parts[0]} 등 비소스/대용량 디렉토리)."
    if _SECRET_PATTERNS.search(rel):
        return None, "시크릿/민감 파일은 열람이 차단되어 있습니다."
    return p, None


def source_list(path: str = ".", pattern: str = None) -> Dict[str, Any]:
    try:
        base, err = _safe_path(path or ".")
        if err:
            return {"success": False, "error": err}
        if not os.path.isdir(base):
            return {"success": False, "error": f"디렉토리가 아닙니다: {path}"}
        entries = []
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs
                             if d not in _EXCLUDE_DIRS and not d.startswith("."))
            for f in sorted(files):
                if not f.endswith(_SOURCE_EXTS) or _SECRET_PATTERNS.search(f):
                    continue
                if pattern and pattern.lower() not in f.lower():
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, _ROOT)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                entries.append(f"{rel} ({size:,}B)")
                if len(entries) >= 300:
                    break
            if len(entries) >= 300:
                break
        return {"success": True, "count": len(entries),
                "message": ("[소스 파일 목록" + (f" — '{pattern}' 필터" if pattern else "")
                            + f", {len(entries)}건" + (" (300건 캡)" if len(entries) >= 300 else "")
                            + "]\n" + "\n".join(entries))}
    except Exception as e:
        logger.error(f"[소스도구] list 실패: {e}")
        return {"success": False, "error": str(e)}


def source_search(query: str, path: str = ".", max_results: int = None) -> Dict[str, Any]:
    try:
        if not query or len(query.strip()) < 2:
            return {"success": False, "error": "검색어는 2자 이상이어야 합니다."}
        base, err = _safe_path(path or ".")
        if err:
            return {"success": False, "error": err}
        limit = min(int(max_results or _MAX_SEARCH_RESULTS), _MAX_SEARCH_RESULTS)
        excludes = []
        for d in _EXCLUDE_DIRS:
            excludes += ["--exclude-dir", d]

        # 멀티워드 → 단어별 OR 매칭 (LLM 이 "interlock 흡입팬 밸브" 처럼 여러 단어를
        # 넣는 실사용 패턴 대응 — 고정문구 전체 매칭은 0건이 되기 쉬움).
        # 더 많은 단어를 포함한 줄을 상위로 정렬한다.
        words = [w for w in query.split() if len(w) >= 2][:6] or [query.strip()]
        cmd = ["grep", "-rn", "-I", "--fixed-strings", "--max-count", "8"] + excludes
        for w in words:
            cmd += ["-e", w]
        cmd += [base]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        scored = []
        for line in (r.stdout or "").splitlines():
            fp = line.split(":", 1)[0]
            if _SECRET_PATTERNS.search(fp):
                continue
            rel = line.replace(_ROOT + "/", "")
            hits = sum(1 for w in words if w in line)
            scored.append((-hits, rel))
        scored.sort()
        lines = [t[1] for t in scored[:limit]]
        body = "\n".join(lines)[:_MAX_SEARCH_CHARS]
        if not lines:
            return {"success": True, "count": 0,
                    "message": f"'{query}' 검색 결과 없음 (경로: {path}) — 더 짧은 단어로 재검색하세요."}
        return {"success": True, "count": len(lines),
                "message": f"[소스 검색 '{query}' — {len(lines)}건, 관련도순 (파일:줄:내용)]\n{body}\n"
                           f"※ 상세는 source_read(file_path, start_line)로 확인하세요."}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "검색 시간 초과(15s) — 검색어를 구체화하세요."}
    except Exception as e:
        logger.error(f"[소스도구] search 실패: {e}")
        return {"success": False, "error": str(e)}


def source_read(file_path: str, start_line: int = 1, end_line: int = None) -> Dict[str, Any]:
    try:
        p, err = _safe_path(file_path)
        if err:
            return {"success": False, "error": err}
        if not os.path.isfile(p):
            return {"success": False, "error": f"파일이 없습니다: {file_path}"}
        try:
            start = max(1, int(start_line or 1))
        except (TypeError, ValueError):
            start = 1
        try:
            end = int(end_line) if end_line else start + _MAX_READ_LINES - 1
        except (TypeError, ValueError):
            end = start + _MAX_READ_LINES - 1
        end = min(end, start + _MAX_READ_LINES - 1)

        out, total = [], 0
        with open(p, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i < start:
                    continue
                if i > end:
                    break
                out.append(f"{i:5d}| {line.rstrip()}")
                total += len(line)
                if total > _MAX_READ_CHARS:
                    out.append("… (크기 캡 도달 — 다음 구간은 start_line 을 올려 재호출)")
                    break
        rel = os.path.relpath(p, _ROOT)
        n_total = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        return {"success": True,
                "message": f"[{rel} — {start}~{min(end, n_total)}줄 / 총 {n_total}줄]\n"
                           + "\n".join(out)}
    except Exception as e:
        logger.error(f"[소스도구] read 실패: {e}")
        return {"success": False, "error": str(e)}
