# ══════════════════════════════════════════════════════════════════════════════
# MCP 게이트웨이 — LLM 이 등록된 MCP 서버의 모든 도구를 직접 호출한다.
#
# 설계 의도(농장주 지시 2026-07-17): python 이 기능을 감싸 대신 처리하지 말고,
#   MCP 고유 기능을 LLM 에게 그대로 넘긴다. 서버·도구를 개별 python 래퍼로
#   만들면 그 수만큼 코드가 늘고 프롬프트가 폭발하므로, 발견(list)+호출(call)
#   두 도구만 노출해 .vscode/mcp.json 에 등록된 전부(현재 98개)를 연다.
#   → 새 MCP 서버 추가 시 mcp.json 한 줄이면 끝. 코드 변경 불필요.
#
# 안전:
#   · 쓰기 도구 deny-list — 파일 쓰기/이동은 "LLM 소스 변경" 단계에서 개방 예정
#     (농장주가 그 작업을 차후로 분리 지시). MCP_GATEWAY_ALLOW_WRITE=1 로 해제.
#   · 결과 문자열 상한 (LLM 컨텍스트 보호)
#
# 파일 시작 함수 목록:
#   _deny_reason    : 쓰기 도구 차단 판정
#   _cap            : 결과 문자열 상한 적용
#   mcp_list_tools  : 등록된 MCP 서버 + 도구 목록 (server 지정 시 해당 서버만)
#   mcp_call        : 임의 MCP 서버의 임의 도구 호출
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
import re
from typing import Any, Dict, Optional

from agri_ai_core.logs import setup_logger

logger = setup_logger(__name__)

_MAX_CHARS = 8000
_DEFAULT_TIMEOUT = 45

# filesystem 쓰기·삭제 계열 — MCP_GATEWAY_ALLOW_WRITE=1 로 개방(농장주 지시).
#   delete 계열도 포함해 둔다(표준 서버엔 없지만 방어적).
_WRITE_TOOLS = {
    "filesystem": {"write_file", "edit_file", "move_file", "create_directory",
                   "delete_file", "delete_directory", "remove"},
}

# filesystem 경로 인자를 갖는 도구 — 시크릿/안전장치 경로 가드 적용 대상.
_PATH_TOOLS = {
    "read_file", "read_text_file", "read_media_file", "write_file", "edit_file",
    "move_file", "create_directory", "delete_file", "delete_directory", "remove",
    "list_directory", "directory_tree", "search_files", "get_file_info",
}

# ⛔ 시크릿 계열 — filesystem MCP 로 읽기·쓰기 모두 차단(MCP_GATEWAY_ALLOW_WRITE 무관).
#   filesystem 루트가 레포 전체라, 이 가드 없으면 LLM 이 mcp_call('filesystem',
#   'read_file',{path:'.env'}) 로 DB 비밀번호·API 키를 열람할 수 있다(2026-07-18).
_SECRET_RE = re.compile(
    r"(^|/)\.env|\.pem$|\.key$|\.crt$|secret|credential|passwd|token|"
    r"mcp\.json|authorized_keys|(^|/)\.ssh(/|$)|pg_hba|postgresql\.auto\.conf",
    re.I)


def _iter_values(args: Any):
    # dict/list 를 재귀 순회하며 모든 스칼라 값을 yield (인자 기반 주문 우회 검사용)
    if args is None:
        return
    if isinstance(args, dict):
        for _v in args.values():
            yield from _iter_values(_v)
    elif isinstance(args, (list, tuple, set)):
        for _v in args:
            yield from _iter_values(_v)
    else:
        yield args


def _iter_paths(args: Any):
    """도구 인자에서 경로 값을 모두 뽑는다(path/source/destination/paths[])."""
    if not isinstance(args, dict):
        return
    for k in ("path", "source", "destination", "src", "dst"):
        v = args.get(k)
        if isinstance(v, str):
            yield v
    for k in ("paths", "files"):
        v = args.get(k)
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str):
                    yield item


# ────────────────────────────────────────────────────────────────────
# 차단 판정. 허용 시 None.
#   ① 시크릿 경로 — filesystem 이면 읽기·쓰기 불문 차단(ALLOW_WRITE 무관).
#   ② 안전장치 소스(_DENY_PATHS) — filesystem 쓰기 계열이면 차단(읽기는 허용).
#      MCP filesystem 쓰기가 edit_source 의 deny-list 를 우회하는 구멍을 막는다.
#   ③ 그 외 쓰기 계열 — MCP_GATEWAY_ALLOW_WRITE 게이트.
# ────────────────────────────────────────────────────────────────────
# 한국투자증권 KIS MCP — 주문 실행/정정/취소 도구는 AI 가 절대 호출 못하게 원천 차단.
# 농장주 지시: 시세·재무 조회 전용. inquire_*/list 는 read 라 허용. KIS_ALLOW_ORDER=1 로만 개방.
_KIS_SERVERS = {x.strip().lower() for x in
                os.getenv("KIS_MCP_SERVERS", "kis-trading,kis,korea-investment").split(",") if x.strip()}
_KIS_ORDER_RE = re.compile(r"(^order_)|(_order$)|(^order$)|(daytime_order)|(매수|매도|매매)|(정정|취소)|(buy|sell)",
                           re.IGNORECASE)
_KIS_ORDER_APITYPES = {"order_cash", "order_credit", "order_rvsecncl", "order_resv",
                       "order_resv_cncl", "order_resv_ccnl", "order_daytime"}


def _deny_reason(server: str, tool: str, args: Any = None) -> Optional[str]:
    srv = (server or "").lower()
    tl = tool or ""
    # 한국투자증권 KIS — 주문(매매) 실행/정정/취소 차단(시세·재무 조회 전용). inquire_*/list 는 허용.
    if srv in _KIS_SERVERS and os.getenv("KIS_ALLOW_ORDER", "0") != "1":
        tlow = tl.lower()
        name_order = (not tlow.startswith("inquire")) and ("list" not in tlow) and bool(_KIS_ORDER_RE.search(tl))
        # 범용 도구로 api_type/tr_id 를 주문값으로 넘겨 우회하는 경로도 차단(인자 검사)
        arg_order = False
        for _v in _iter_values(args):
            vs = str(_v).strip().lower()
            if not vs or vs.startswith("inquire") or "inquire" in vs:
                continue
            if vs in _KIS_ORDER_APITYPES or vs.startswith("order_") or _KIS_ORDER_RE.search(str(_v)):
                arg_order = True
                break
        if name_order or arg_order:
            return (f"{server}.{tool} 은 주문(매매) 실행 계열이라 차단됩니다 — 이 KIS 연동은 "
                    f"시세·재무 조회 전용입니다(농장주 지시, 인자 포함 원천 차단). 조회(inquire_*)만 사용하세요.")
    is_fs = srv == "filesystem"
    is_write = tl in _WRITE_TOOLS.get(srv, set())

    if is_fs and tl in _PATH_TOOLS:
        for p in _iter_paths(args):
            norm = p.replace("\\", "/")
            # ① 시크릿 — 읽기·쓰기 모두 차단
            if _SECRET_RE.search(norm):
                return (f"'{p}' 은 시크릿(비밀번호·키·토큰) 계열이라 filesystem MCP 로 "
                        f"접근할 수 없습니다. 농장 운영에 필요한 값은 전용 도구를 쓰세요.")
            # ② 안전장치 소스 — 쓰기 계열이면 차단(읽기는 허용)
            if is_write:
                try:
                    from agri_ai_core.src.ai.tools_source_edit import _DENY_PATHS
                except Exception:
                    _DENY_PATHS = ()
                for d in _DENY_PATHS:
                    if d in norm and not d.startswith("."):   # .env/mcp.json 은 위 시크릿에서 처리
                        return (f"'{p}' 은 안전장치 소스({d})라 filesystem MCP 로 변경할 수 "
                                f"없습니다. 소스 변경은 edit_source 도구를 쓰세요(자동복구·검증 포함).")

    # ③ 쓰기 계열 개방 여부
    if is_write and os.getenv("MCP_GATEWAY_ALLOW_WRITE", "0") != "1":
        return (f"{server}.{tool} 은 파일 쓰기 도구라 현재 차단되어 있습니다. "
                f"읽기 도구(read_file/list_directory/search_files)는 자유롭게 쓰세요.")
    return None


# ────────────────────────────────────────────────────────────────────
# 결과 문자열 상한 — 초과 시 절단 표기.
# ────────────────────────────────────────────────────────────────────
def _cap(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    return text[:_MAX_CHARS] + f"\n...(총 {len(text)}자 중 {_MAX_CHARS}자만 표시)"


# ────────────────────────────────────────────────────────────────────
# 등록된 MCP 서버와 각 서버의 도구 목록.
# server 미지정 시 서버 이름만(가벼움), 지정 시 그 서버의 도구 상세.
# ────────────────────────────────────────────────────────────────────
def mcp_list_tools(server: str = None) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.mcp_client import (_load_mcp_servers,
                                                    list_mcp_server_tools)
        servers = _load_mcp_servers()
        if not servers:
            return {"success": False, "error": "등록된 MCP 서버가 없습니다."}

        if not server:
            return {"success": True, "servers": sorted(servers.keys()),
                    "note": "특정 서버의 도구를 보려면 mcp_list_tools(server='이름') 호출."}

        if server not in servers:
            return {"success": False,
                    "error": f"MCP 서버 '{server}' 미등록. 사용 가능: {sorted(servers.keys())}"}

        res = list_mcp_server_tools(server, timeout=_DEFAULT_TIMEOUT)
        if res.get("error"):
            return {"success": False, "error": res["error"]}
        tools = [{"name": t.get("name"), "description": (t.get("description") or "")[:200]}
                 for t in (res.get("tools") or [])]
        return {"success": True, "server": server, "count": len(tools), "tools": tools}
    except Exception as e:
        logger.warning(f"[MCP게이트웨이] list 실패: {e}")
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────────────────────────
# 임의 MCP 서버의 임의 도구 호출. args 는 그 도구의 스키마를 따른다
# (모르면 mcp_list_tools(server=...) 로 먼저 확인).
# ────────────────────────────────────────────────────────────────────
def mcp_call(server: str, tool: str, args: Any = None,
             timeout: int = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    if not server or not tool:
        return {"success": False, "error": "server 와 tool 이 필요합니다."}

    # args 를 먼저 정규화해야 경로 가드가 인자를 검사할 수 있다.
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return {"success": False, "error": "args 는 JSON 객체여야 합니다."}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"success": False, "error": "args 는 JSON 객체여야 합니다."}

    denied = _deny_reason(server, tool, args)
    if denied:
        logger.warning(f"[MCP게이트웨이] 차단 {server}.{tool} args={list(args)}: {denied[:60]}")
        return {"success": False, "error": denied}

    try:
        from agri_ai_core.src.ai.mcp_client import call_mcp_server_tool, _extract_text_blocks
        try:
            to = max(5, min(int(timeout or _DEFAULT_TIMEOUT), 120))
        except (TypeError, ValueError):
            to = _DEFAULT_TIMEOUT

        res = call_mcp_server_tool(server, tool, args, timeout=to)
        if res.get("error"):
            return {"success": False, "server": server, "tool": tool, "error": res["error"]}
        if res.get("isError"):
            return {"success": False, "server": server, "tool": tool,
                    "error": _cap("\n".join(_extract_text_blocks(res)) or "도구 오류")}

        text = "\n".join(_extract_text_blocks(res))
        if not text:
            try:
                text = json.dumps(res, ensure_ascii=False, default=str)
            except Exception:
                text = str(res)
        return {"success": True, "server": server, "tool": tool, "result": _cap(text)}
    except Exception as e:
        logger.warning(f"[MCP게이트웨이] {server}.{tool} 실패: {e}")
        return {"success": False, "server": server, "tool": tool, "error": str(e)}
