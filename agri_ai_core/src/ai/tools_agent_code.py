# ══════════════════════════════════════════════════════════════════════════════
# Agent 전용 코딩 도구 — 실행·체이닝(write→run→디버깅→재실행) 지원
#
# 주기 Agent(ai_monitor_agent.run_agent)의 ReAct 루프가 코드를 작성·실행하고
# stderr 를 보고 스스로 고쳐 재실행하도록 코딩 도구를 결합한다. 채팅 파이프라인의
# 검증된 구현(write_script/run_script/source_*/db_read_query)을 얇게 래핑.
#
# 안전:
#   · 스크립트는 scripts/llm/ 샌드박스 한정(경로이탈·sudo 불가·timeout) — 운영소스 불변
#   · source_read/source_search/db_read_query 는 read-only
#   · edit_source(운영소스 변경)는 의도적으로 미포함 — 이 결합은 분석·디버깅용
#   · 전부 dict 반환(성공·실패) — ReAct 루프가 동일 형식으로 파싱
#
# 파일 시작 함수 목록:
#   agent_write_script / agent_run_script / agent_read_script / agent_list_scripts
#   agent_source_read / agent_source_search / agent_db_read
#   TOOL_REGISTRY / TOOL_SPECS / tool_specs_text
# ══════════════════════════════════════════════════════════════════════════════
from typing import Any, Dict, List, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)


def agent_write_script(script: str = None, content: str = None,
                       reason: str = "") -> Dict[str, Any]:
    if not script or not content:
        return {"error": "script(파일명)와 content(코드)는 필수입니다."}
    try:
        from agri_ai_core.src.ai.tools_script import write_script
        return write_script(script=str(script), content=str(content), reason=reason or "agent")
    except Exception as e:
        logger.warning(f"[Agent코드] write_script 실패: {e}")
        return {"error": f"스크립트 작성 실패: {e}"}


def agent_run_script(script: str = None, args: Any = None,
                     timeout: int = None, reason: str = "") -> Dict[str, Any]:
    if not script:
        return {"error": "script(실행할 파일명)는 필수입니다. 먼저 write_script 로 작성하세요."}
    try:
        from agri_ai_core.src.ai.tools_script import run_script
        run_args = args if isinstance(args, list) else ([] if args is None else [str(args)])
        to = timeout if isinstance(timeout, int) and timeout > 0 else 60
        return run_script(script=str(script), args=run_args, timeout=to, reason=reason or "agent")
    except Exception as e:
        logger.warning(f"[Agent코드] run_script 실패: {e}")
        return {"error": f"스크립트 실행 실패: {e}"}


def agent_read_script(script: str = None) -> Dict[str, Any]:
    if not script:
        return {"error": "script(파일명)는 필수입니다."}
    try:
        from agri_ai_core.src.ai.tools_script import read_script
        return read_script(script=str(script))
    except Exception as e:
        logger.warning(f"[Agent코드] read_script 실패: {e}")
        return {"error": f"스크립트 읽기 실패: {e}"}


def agent_list_scripts() -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_script import list_scripts
        return list_scripts()
    except Exception as e:
        logger.warning(f"[Agent코드] list_scripts 실패: {e}")
        return {"error": f"스크립트 목록 실패: {e}"}


def agent_source_read(file_path: str = None, start_line: int = 1,
                      end_line: int = None) -> Dict[str, Any]:
    if not file_path:
        return {"error": "file_path 는 필수입니다."}
    try:
        from agri_ai_core.src.ai.tools_source import source_read
        sl = start_line if isinstance(start_line, int) and start_line >= 1 else 1
        return source_read(file_path=str(file_path), start_line=sl, end_line=end_line)
    except Exception as e:
        logger.warning(f"[Agent코드] source_read 실패: {e}")
        return {"error": f"소스 읽기 실패: {e}"}


def agent_source_search(query: str = None, path: str = ".",
                        max_results: int = None) -> Dict[str, Any]:
    if not query or len(str(query).strip()) < 2:
        return {"error": "query(검색어)는 2자 이상이어야 합니다."}
    try:
        from agri_ai_core.src.ai.tools_source import source_search
        return source_search(query=str(query), path=path or ".", max_results=max_results)
    except Exception as e:
        logger.warning(f"[Agent코드] source_search 실패: {e}")
        return {"error": f"소스 검색 실패: {e}"}


def agent_db_read(sql: str = None, limit: int = 50) -> Dict[str, Any]:
    if not sql:
        return {"error": "sql(SELECT 쿼리)는 필수입니다."}
    try:
        from agri_ai_core.src.ai.tools_db import db_read_query
        lim = limit if isinstance(limit, int) and 1 <= limit <= 500 else 50
        return db_read_query(sql=str(sql), limit=lim)   # 읽기전용·자가교정 힌트 포함
    except Exception as e:
        logger.warning(f"[Agent코드] db_read_query 실패: {e}")
        return {"error": f"DB 조회 실패: {e}"}


# ────────────────────────────────────────────────────────────────────
# 레지스트리 — 채팅과 동일 도구명. 전부 read-only 또는 샌드박스 실행이라
# ai_monitor_agent 의 _WRITE_TOOL_NAMES(농장 제어)에는 포함되지 않는다.
# ────────────────────────────────────────────────────────────────────
TOOL_REGISTRY = {
    "write_script":   agent_write_script,
    "run_script":     agent_run_script,
    "read_script":    agent_read_script,
    "list_scripts":   agent_list_scripts,
    "source_read":    agent_source_read,
    "source_search":  agent_source_search,
    "db_read_query":  agent_db_read,
}

TOOL_SPECS = [
    {"name": "write_script",
     "description": "파이썬 스크립트를 scripts/llm/ 에 작성/수정(구문검증). 코드를 만들거나 디버깅용 재현 코드를 짤 때. 실행은 run_script.",
     "args": {"script": {"type": "str", "desc": "파일명(.py)"},
              "content": {"type": "str", "desc": "파이썬 코드 전체"}}},
    {"name": "run_script",
     "description": "작성한 스크립트를 실행하고 stdout/stderr 를 돌려준다(sudo 없음·timeout). 실패하면 stderr 를 읽고 write_script 로 고쳐 다시 run_script — 이 반복이 디버깅이다.",
     "args": {"script": {"type": "str", "desc": "실행할 파일명(.py)"},
              "args": {"type": "list", "desc": "실행 인자(선택)"}}},
    {"name": "read_script",
     "description": "작성한 스크립트 본문을 읽는다(수정 전 현재 내용 확인).",
     "args": {"script": {"type": "str", "desc": "파일명(.py)"}}},
    {"name": "list_scripts",
     "description": "scripts/llm/ 의 스크립트 목록(이름·크기·수정시각).",
     "args": {}},
    {"name": "source_read",
     "description": "운영 소스코드 본문을 읽는다(읽기 전용). 특정 파일의 구현 분석·디버깅에.",
     "args": {"file_path": {"type": "str", "desc": "레포 기준 경로"},
              "start_line": {"type": "int", "desc": "시작 줄(기본 1)"},
              "end_line": {"type": "int", "desc": "끝 줄(선택)"}}},
    {"name": "source_search",
     "description": "운영 소스 전역 키워드 검색(읽기 전용) — 어느 파일·줄에 있는지 파일:줄:내용 으로.",
     "args": {"query": {"type": "str", "desc": "검색어(2자 이상)"}}},
    {"name": "db_read_query",
     "description": "읽기전용 SELECT 로 DB 를 조회·분석(단일문). 없는 컬럼/타입오류면 error 에 실제 컬럼 힌트가 실려온다.",
     "args": {"sql": {"type": "str", "desc": "SELECT/WITH 쿼리"},
              "limit": {"type": "int", "desc": "행 상한(기본 50)"}}},
]


def tool_specs_text() -> str:
    lines = ["\n[코딩 도구 — 작성·실행·디버깅(write→run→수정→재실행) · 분석 read-only]"]
    for spec in TOOL_SPECS:
        arg = ", ".join(f"{k}({v.get('type','')})" for k, v in spec["args"].items())
        lines.append(f"- {spec['name']}({arg}): {spec['description']}")
    return "\n".join(lines) + "\n"
