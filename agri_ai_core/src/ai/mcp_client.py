# ══════════════════════════════════════════════════════════════════════════════════════
# MCP (Model Context Protocol) 클라이언트 — MCP 서버(web-search, postgres 등) 공통 호출.
# --->
# _mark_server_unavailable: mark server unavailable
# _get_runtime_disable_seconds: get runtime disable seconds
# _get_runtime_disabled_reason: get runtime disabled reason
# _mark_server_available: mark server available
# _error_to_text: error to text
# _should_mark_unavailable: should mark unavailable
# _is_dns_resolution_error: is dns resolution error
# _log_dns_diagnostics_once: log dns diagnostics once
# _load_mcp_servers: load mcp servers
# _jsonrpc: jsonrpc
# _find_response: find response
# _read_response: stdin 유지 read-loop 로 target id 응답 수신
# _terminate: MCP 서버 프로세스 그룹 회수 (⛔ 누수 방지 — 모든 경로에서 필수 호출)
# list_mcp_server_tools: MCP 서버 tools/list 조회 (게이트웨이용)
# _extract_text_blocks: extract text blocks
# _format_search_result: 검색 결과 항목을 표준 dict 형태로 생성
# _check_error_with_dns_diag: 에러 텍스트에 DNS 관련 키워드가 있으면 DNS 진단을 1회 실행
# _try_parse_json: 텍스트를 JSON으로 파싱 시도
# call_mcp_server_tool: call mcp server tool
# _coerce_json_and_text: coerce json and text
# _direct_http_json_request: direct http json request
# _parse_mcp_fetch_result: parse mcp fetch result
# _parse_fetch_tool_names: parse fetch tool names
# mcp_fetch_request: mcp fetch request
# mcp_fetch_json: mcp fetch json
# mcp_http_request: mcp http request
# _parse_markdown_table: parse markdown table
# search_web: search web
# get_current_weather: get current weather
# ══════════════════════════════════════════════════════════════════════════════════════
import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.validators import is_true
from agri_ai_core.src.utils.json_utils import safe_json_load

logger = setup_logger(__name__)

DEFAULT_PROTOCOL_VERSION = "2024-11-05"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# MCP 서버 종료 대기(초). stdin EOF 후 이 시간 내 미종료 시 프로세스 그룹 SIGKILL.
_TERMINATE_GRACE_SEC = int(os.getenv("MCP_TERMINATE_GRACE_SEC", "3"))
MCP_CONFIG_PATH = PROJECT_ROOT / ".vscode" / "mcp.json"

# MCP 서버/도구명 — .vscode/mcp.json 의 등록명과 반드시 일치해야 한다.
# env 로 덮을 수 있게 하여 설정 교체 시 코드 수정 불필요.
_WEB_SEARCH_SERVER = (os.getenv("MCP_WEB_SEARCH_SERVER") or "searxng").strip()
_WEB_SEARCH_TOOL = (os.getenv("MCP_WEB_SEARCH_TOOL") or "searxng_web_search").strip()
# URL 본문 수집 — 설정상 web_url_read 를 가진 searxng 서버가 유일한 실동작 경로.
_FETCH_SERVER = (os.getenv("MCP_FETCH_SERVER") or "searxng").strip()
_MCP_SERVER_RUNTIME_UNAVAILABLE: Dict[str, Tuple[float, str]] = {}
MCP_RUNTIME_DISABLE_SECONDS = max(1, int(os.getenv("MCP_RUNTIME_DISABLE_SECONDS", "60")))
_SERVER_UNAVAILABLE_KEYWORDS = (
    "timeout",
    "timed out",
    "eai_again",
    "enotfound",
    "getaddrinfo",
    "cannot find module",
    "not found",
    "command not found",
    "no such file",
)
_DNS_ERROR_KEYWORDS = (
    "eai_again",
    "enotfound",
    "getaddrinfo",
    "temporary failure in name resolution",
    "name or service not known",
)
_LAST_DNS_DIAG_AT: float = 0.0


def _mark_server_unavailable(server_name: str, reason: str) -> None:
    prev = _MCP_SERVER_RUNTIME_UNAVAILABLE.get(server_name)
    _MCP_SERVER_RUNTIME_UNAVAILABLE[server_name] = (time.time(), reason)
    if prev is None:
        logger.warning(f"[MCP:{server_name}] 런타임 비활성화: {reason}")


def _get_runtime_disable_seconds(server_name: str) -> int:
    specific_env_name = f"MCP_RUNTIME_DISABLE_SECONDS_{(server_name or '').upper().replace('-', '_')}"
    raw_value = os.getenv(specific_env_name)
    if raw_value is not None:
        try:
            return max(1, int(raw_value))
        except Exception:
            logger.warning(f"[MCP:{server_name}] 잘못된 {specific_env_name} 값: {raw_value} (기본값 사용)")
    return MCP_RUNTIME_DISABLE_SECONDS


def _get_runtime_disabled_reason(server_name: str) -> Optional[str]:
    item = _MCP_SERVER_RUNTIME_UNAVAILABLE.get(server_name)
    if not item:
        return None

    disabled_at, reason = item
    disable_seconds = _get_runtime_disable_seconds(server_name)
    elapsed = time.time() - disabled_at
    if elapsed >= disable_seconds:
        _MCP_SERVER_RUNTIME_UNAVAILABLE.pop(server_name, None)
        logger.debug(f"[MCP:{server_name}] 런타임 비활성 만료({disable_seconds}s), 재시도")
        return None
    return reason


def _mark_server_available(server_name: str) -> None:
    if server_name in _MCP_SERVER_RUNTIME_UNAVAILABLE:
        _MCP_SERVER_RUNTIME_UNAVAILABLE.pop(server_name, None)
        logger.debug(f"[MCP:{server_name}] 런타임 비활성 해제")


def _error_to_text(error: Any) -> str:
    if isinstance(error, str):
        return error
    try:
        return json.dumps(error, ensure_ascii=False)
    except Exception:
        return str(error)


def _should_mark_unavailable(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(keyword in lowered for keyword in _SERVER_UNAVAILABLE_KEYWORDS)


def _is_dns_resolution_error(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(keyword in lowered for keyword in _DNS_ERROR_KEYWORDS)


def _log_dns_diagnostics_once(min_interval_sec: int = 30) -> None:
    global _LAST_DNS_DIAG_AT
    now = time.time()
    if now - _LAST_DNS_DIAG_AT < max(1, int(min_interval_sec)):
        return
    _LAST_DNS_DIAG_AT = now

    checks = [
        ("resolv.conf", "readlink -f /etc/resolv.conf && sed -n '1,20p' /etc/resolv.conf"),
        ("dns_google", "getent hosts www.google.com"),
        ("dns_naver", "getent hosts search.naver.com"),
        ("dns_bing", "getent hosts www.bing.com"),
    ]

    for name, command in checks:
        try:
            completed = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
                env=os.environ.copy(),
            )
            output = (completed.stdout or completed.stderr or "").strip().replace("\n", " | ")
            if len(output) > 420:
                output = f"{output[:420]}..."
            logger.warning(f"[DNS진단] {name}: rc={completed.returncode} output={output}")
        except Exception as diag_err:
            logger.warning(f"[DNS진단] {name} 실행 실패: {diag_err}")


# ════════════════════════════════════════════
# `.vscode/mcp.json`에서 MCP 서버 설정을 로드.
# 최상위 키는 두 포맷이 공존한다 — VSCode 는 "servers", Claude Desktop/표준
# 클라이언트는 "mcpServers". 우리 파일은 VSCode 소유라 "servers" 이므로 둘 다
# 수용한다. (한쪽만 보면 파일은 읽히는데 서버가 0개가 되어 모든 MCP 호출이
# "server not found" 로 조용히 폴백된다 — 2026-07-16 실측 확인.)
# ════════════════════════════════════════════
def _load_mcp_servers() -> Dict[str, Dict[str, Any]]:
    try:
        if not MCP_CONFIG_PATH.exists():
            logger.error(f"MCP 설정 파일이 없습니다: {MCP_CONFIG_PATH}")
            return {}
        raw = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
        servers = raw.get("mcpServers")
        if not isinstance(servers, dict) or not servers:
            servers = raw.get("servers")
        if not isinstance(servers, dict):
            logger.error(f"MCP 설정에 servers/mcpServers 키가 없습니다: {MCP_CONFIG_PATH}")
            return {}
        return servers
    except Exception as e:
        logger.error(f"MCP 설정 로드 실패: {e}")
        return {}


# 순수 유틸 함수들은 mcp_utils.py 에 정의 (하위 호환 alias 유지)
from agri_ai_core.src.ai.mcp_utils import (
    build_jsonrpc as _jsonrpc,
    find_response_line as _find_response,
    extract_text_blocks as _extract_text_blocks,
    format_search_result as _format_search_result,
    parse_markdown_table as _parse_markdown_table,
    parse_searxng_results as _parse_searxng_results,
)


# ────────────────────────────────────────────────────────────────────
# 에러 텍스트에 DNS 관련 키워드가 있으면 DNS 진단을 1회 실행.
# ────────────────────────────────────────────────────────────────────
def _check_error_with_dns_diag(error_text: str, context: str = "") -> None:
    if _is_dns_resolution_error(error_text):
        _log_dns_diagnostics_once()


# ────────────────────────────────────────────────────────────────────
# 텍스트를 JSON으로 파싱 시도. 실패 시 None 반환.
# ────────────────────────────────────────────────────────────────────
def _try_parse_json(text: str) -> Optional[Any]:
    stripped = text.strip()
    if not stripped:
        return None
    return safe_json_load(stripped)


# ────────────────────────────────────────────────────────────────────
# stdin 을 연 채로 stdout 을 줄 단위로 읽어 target_id 응답을 찾는다.
# 서버가 초기화 로그·notification 을 먼저 흘려도 건너뛰고, 응답을 받으면
# 즉시 반환한다(불필요한 대기 없음). 반환: (응답 dict|None, 읽은 stdout)
# ────────────────────────────────────────────────────────────────────
def _read_response(process, target_id: int, timeout: int, t_start: float):
    buf = []
    while True:
        remain = timeout - (time.time() - t_start)
        if remain <= 0:
            raise subprocess.TimeoutExpired(cmd="mcp", timeout=timeout)
        line = process.stdout.readline()
        if not line:
            break
        buf.append(line)
        try:
            msg = json.loads(line.strip())
        except Exception:
            continue
        if isinstance(msg, dict) and msg.get("id") == target_id:
            return msg, "".join(buf)
    return None, "".join(buf)


# ────────────────────────────────────────────────────────────────────
# mcp.json 의 서버별 env 블록을 os.environ 에 병합해 Popen 에 넘긴다.
#   과거엔 env=os.environ.copy() 만 써서 mcp.json 의 env 가 무시됐고,
#   searxng/naver 는 .env 에 같은 키가 우연히 있어야만 동작했다(2026-07-18 정비).
#   ${VAR} VSCode 치환 문법도 os.environ 기준으로 확장한다.
# ────────────────────────────────────────────────────────────────────
def _server_env(server: Dict[str, Any]) -> Dict[str, str]:
    env = os.environ.copy()
    block = server.get("env") if isinstance(server, dict) else None
    if isinstance(block, dict):
        for k, v in block.items():
            if v is None:
                continue
            env[str(k)] = os.path.expandvars(str(v))   # ${NAVER_CLIENT_ID} 등 확장
    return env


# ────────────────────────────────────────────────────────────────────
# MCP 서버 프로세스 회수. ⛔ Popen 한 모든 경로(성공 포함)에서 반드시 호출.
# npx 는 sh → npm exec → node 로 손자를 낳으므로 process.kill() 은
# 직계(npx)만 죽이고 node 는 고아로 영생한다(2026-07-17 5,201개 누수 → OOM 실증).
# stdin 을 닫아 EOF 로 자발 종료를 유도하고, 안 죽으면 프로세스 그룹째 SIGKILL.
# ────────────────────────────────────────────────────────────────────
def _terminate(process) -> None:
    if process is None:
        return
    try:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
    except Exception:
        pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SEC)
    except Exception:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    for stream in (process.stdout, process.stderr):
        try:
            if stream and not stream.closed:
                stream.close()
        except Exception:
            pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SEC)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────
# MCP 서버의 tools/list 조회 — 게이트웨이(LLM 도구 발견)용.
# call_mcp_server_tool 과 통신 방식은 같고 method 만 다르다.
# 반환: {"tools": [...]} 또는 {"error": "..."}
# ────────────────────────────────────────────────────────────────────
def list_mcp_server_tools(server_name: str, timeout: int = 45) -> Dict[str, Any]:
    servers = _load_mcp_servers()
    server = servers.get(server_name)
    if not server:
        return {"error": f"MCP server not found: {server_name}"}
    command = server.get("command")
    if not command:
        return {"error": f"MCP server command missing: {server_name}"}

    t_start = time.time()
    process = None
    try:
        process = subprocess.Popen(
            [command, *[str(a) for a in server.get("args", [])]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=str(PROJECT_ROOT), env=_server_env(server),
            start_new_session=True,
        )
        init = _jsonrpc(1, "initialize", {
            "protocolVersion": DEFAULT_PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "agri-ai-core", "version": "1.0.0"}})
        process.stdin.write(json.dumps(init, ensure_ascii=False) + "\n")
        process.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, ensure_ascii=False) + "\n")
        process.stdin.write(json.dumps(
            _jsonrpc(2, "tools/list", {}), ensure_ascii=False) + "\n")
        process.stdin.flush()

        response, _ = _read_response(process, 2, timeout, t_start)
        if not response:
            return {"error": f"tools/list 응답 없음: {server_name}"}
        if "error" in response:
            return {"error": _error_to_text(response["error"])}
        return {"tools": response.get("result", {}).get("tools", [])}
    except subprocess.TimeoutExpired:
        return {"error": f"MCP timeout: {server_name}.tools/list ({timeout}s)"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        _terminate(process)


def call_mcp_server_tool(
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: int = 30,

# ════════════════════════════════
# 지정 MCP 서버의 도구를 1회 호출.
# ════════════════════════════════
) -> Dict[str, Any]:
    t_start = time.time()
    # 인자 요약 (긴 값 잘라서 로깅)
    args_summary = {}
    for k, v in (arguments or {}).items():
        sv = str(v)
        args_summary[k] = sv[:80] + "..." if len(sv) > 80 else sv
    logger.info(f"[MCP호출] 시작 server={server_name} tool={tool_name} args={args_summary} timeout={timeout}s")

    disabled_reason = _get_runtime_disabled_reason(server_name)
    if disabled_reason:
        reason = disabled_reason
        logger.warning(f"[MCP호출] 비활성화 server={server_name}: {reason}")
        return {"error": f"MCP server disabled at runtime: {server_name} ({reason})"}

    servers = _load_mcp_servers()
    server = servers.get(server_name)
    if not server:
        logger.warning(f"[MCP호출] 서버 미등록: {server_name}")
        return {"error": f"MCP server not found: {server_name}"}

    command = server.get("command")
    args = server.get("args", [])
    if not command:
        return {"error": f"MCP server command missing: {server_name}"}
    if not isinstance(args, list):
        args = []

    cmd = [command, *[str(arg) for arg in args]]
    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=_server_env(server),
            start_new_session=True,
        )

        if process.stdin is None:
            return {"error": f"MCP stdin unavailable: {server_name}"}

        init_request = _jsonrpc(
            1,
            "initialize",
            {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agri-ai-core", "version": "1.0.0"},
            },
        )
        call_request = _jsonrpc(
            2,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )

        # stdin 을 열어둔 채 id=2 응답이 올 때까지 읽는다.
        # communicate() 는 입력을 쓰고 stdin 을 즉시 닫는데, 일부 MCP 서버는
        # EOF 를 받으면 큐에 남은 tools/call 을 처리하지 않고 종료한다
        # (naver-search 실측: initialize 만 응답 → "Failed to parse" 오진).
        # MCP 표준의 notifications/initialized 도 함께 보낸다.
        process.stdin.write(json.dumps(init_request, ensure_ascii=False) + "\n")
        process.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            ensure_ascii=False) + "\n")
        process.stdin.write(json.dumps(call_request, ensure_ascii=False) + "\n")
        process.stdin.flush()

        response, stdout = _read_response(process, 2, timeout, t_start)

        if not response:
            error_msg = "Failed to parse MCP tools/call response"
            if _should_mark_unavailable(error_msg):
                _mark_server_unavailable(server_name, error_msg)
            return {"error": error_msg, "raw_stdout": stdout[-1000:]}

        if "error" in response:
            error_text = _error_to_text(response["error"])
            if _should_mark_unavailable(error_text):
                _mark_server_unavailable(server_name, error_text)
            return {"error": response["error"]}

        _mark_server_available(server_name)
        elapsed = time.time() - t_start
        result_data = response.get("result", {})
        logger.debug(f"[MCP응답구조] server={server_name} tool={tool_name} keys={list(result_data.keys()) if isinstance(result_data, dict) else type(result_data).__name__}")
        logger.info(f"[MCP호출] 성공 server={server_name} tool={tool_name} ({elapsed:.1f}s)")
        return result_data

    except subprocess.TimeoutExpired:
        elapsed = time.time() - t_start
        error_msg = f"MCP timeout: {server_name}.{tool_name} ({timeout}s)"
        logger.warning(f"[MCP호출] 타임아웃 ({elapsed:.1f}s): {error_msg}")
        _mark_server_unavailable(server_name, error_msg)
        return {"error": error_msg}
    except Exception as e:
        elapsed = time.time() - t_start
        logger.error(f"[MCP호출] 오류 server={server_name} tool={tool_name} ({elapsed:.1f}s): {e}")
        error_msg = str(e)
        if _should_mark_unavailable(error_msg):
            _mark_server_unavailable(server_name, error_msg)
        return {"error": error_msg}
    finally:
        _terminate(process)


# HTTP/JSON 유틸은 src/utils/http_client.py 에 정의 (하위 계층에서도 사용 가능).
# 하위 호환 alias 로 재노출.
from agri_ai_core.src.utils.http_client import (
    coerce_json_and_text as _coerce_json_and_text,
    http_json_request as _direct_http_json_request,
)


def _parse_mcp_fetch_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("isError"):
        error_text = "\n".join(_extract_text_blocks(result)) or "MCP fetch error"
        return {"success": False, "status_code": 500, "json": None, "text": error_text, "raw": result}

    text_blocks = _extract_text_blocks(result)
    if not text_blocks:
        return {"success": True, "status_code": 200, "json": None, "text": "", "raw": result}

    joined_text = "\n".join(text_blocks).strip()

    for block in text_blocks:
        parsed = _try_parse_json(block)

        if isinstance(parsed, list):
            return {
                "success": True,
                "status_code": 200,
                "json": parsed,
                "text": json.dumps(parsed, ensure_ascii=False),
                "raw": result,
            }

        if isinstance(parsed, dict):
            status_raw = parsed.get("statusCode", parsed.get("status", 200))
            status_code = 200
            try:
                status_code = int(status_raw)
            except Exception:
                status_code = 200

            body = parsed.get("body")
            if body is None:
                body = parsed.get("data")
            if body is None and "content" in parsed and not isinstance(parsed.get("content"), list):
                body = parsed.get("content")
            if body is None:
                body = parsed

            body_json, body_text = _coerce_json_and_text(body)
            return {
                "success": 200 <= status_code < 400,
                "status_code": status_code,
                "json": body_json,
                "text": body_text,
                "raw": result,
            }

    parsed_json, parsed_text = _coerce_json_and_text(joined_text)
    return {
        "success": True,
        "status_code": 200,
        "json": parsed_json,
        "text": parsed_text,
        "raw": result,
    }


def _parse_fetch_tool_names() -> List[str]:
    # 설정에 실재하는 도구명이어야 한다. 과거 기본값 "fetch" 는 어느 등록 서버에도
    # 없는 이름이었다 — @kazuph/mcp-fetch 는 imageFetch 만 제공. 현 설정에서 URL
    # 본문을 읽을 수 있는 실제 도구는 searxng 의 web_url_read 뿐이다(2026-07-16 실측).
    default_tools = "web_url_read"
    raw = os.getenv("MCP_FETCH_TOOL_NAMES", default_tools)
    candidates = [name.strip() for name in raw.split(",") if name and name.strip()]

    # 순서를 유지하면서 중복 제거
    seen = set()
    normalized: List[str] = []
    for tool_name in candidates:
        key = tool_name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(tool_name)

    return normalized or ["fetch"]


def mcp_fetch_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Any] = None,
    timeout: int = 20,

# ════════════════════════════════════════════════════════════════════════
# MCP fetch 서버를 사용해 HTTP 요청 수행.
# 서버/도구 비호환 시 실패 응답을 반환하며, 호출자가 직접 폴백을 적용한다.
# ════════════════════════════════════════════════════════════════════════
) -> Dict[str, Any]:
    if not url or not isinstance(url, str):
        return {"success": False, "status_code": 400, "json": None, "text": "URL is required"}

    t_start = time.time()
    logger.info(f"[MCP Fetch] 시작 method={method} url={url[:120]} timeout={timeout}s")

    normalized_method = (method or "GET").upper()
    normalized_headers: Dict[str, str] = dict(headers or {})
    if json_body is not None and not any(key.lower() == "content-type" for key in normalized_headers):
        normalized_headers["Content-Type"] = "application/json"

    body_text = ""
    if json_body is not None:
        try:
            body_text = json.dumps(json_body, ensure_ascii=False)
        except Exception:
            body_text = str(json_body)

    tool_names = _parse_fetch_tool_names()

    argument_candidates = [
        {"url": url},
        {"url": url, "method": normalized_method},
        {"url": url, "method": normalized_method, "headers": normalized_headers},
    ]

    if json_body is not None:
        argument_candidates.extend(
            [
                {
                    "url": url,
                    "method": normalized_method,
                    "headers": normalized_headers,
                    "body": body_text,
                },
                {
                    "url": url,
                    "method": normalized_method,
                    "headers": normalized_headers,
                    "json": json_body,
                },
                {
                    "url": url,
                    "method": normalized_method,
                    "headers": normalized_headers,
                    "data": body_text,
                },
            ]
        )

    seen = set()
    deduped_candidates: List[Dict[str, Any]] = []
    for candidate in argument_candidates:
        try:
            key = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(candidate)

    last_error = "MCP fetch call failed"
    for tool_name in tool_names:
        tool_unknown = False
        for args in deduped_candidates:
            result = call_mcp_server_tool(_FETCH_SERVER, tool_name, args, timeout=timeout)
            if "error" in result:
                error_text = _error_to_text(result.get("error"))
                last_error = error_text
                if "unknown tool" in error_text.lower():
                    tool_unknown = True
                    break
                continue

            parsed = _parse_mcp_fetch_result(result)
            if parsed.get("success"):
                parsed["tool_name"] = tool_name
                elapsed = time.time() - t_start
                content_len = len(str(parsed.get("text", "") or ""))
                logger.info(f"[MCP Fetch] 성공 ({elapsed:.1f}s) status={parsed.get('status_code')} content_len={content_len}자")
                return parsed

            last_error = parsed.get("text") or last_error

        if tool_unknown:
            logger.debug(f"[MCP:fetch] 지원하지 않는 도구 스킵: {tool_name}")

    elapsed = time.time() - t_start
    logger.warning(f"[MCP Fetch] 실패 ({elapsed:.1f}s) url={url[:120]} error={last_error[:100]}")
    return {"success": False, "status_code": 500, "json": None, "text": last_error}


def mcp_fetch_json(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Any] = None,
    timeout: int = 20,

# ═════════════════════════════════════════
# MCP fetch 요청 결과를 JSON 중심으로 반환.
# ═════════════════════════════════════════
) -> Dict[str, Any]:
    result = mcp_fetch_request(
        url=url,
        method=method,
        headers=headers,
        json_body=json_body,
        timeout=timeout,
    )
    if not result.get("success"):
        return {"success": False, "status_code": result.get("status_code", 500), "error": result.get("text")}

    data = result.get("json")
    if data is None:
        raw_text = result.get("text", "")
        data = safe_json_load(raw_text)
        if data is None:
            return {
                "success": False,
                "status_code": result.get("status_code", 500),
                "error": "MCP fetch response is not JSON",
                "text": raw_text,
            }

    return {"success": True, "status_code": result.get("status_code", 200), "data": data, "text": result.get("text", "")}


def mcp_http_request(
    method: str,
    url: str,
    json_body: Optional[Any] = None,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,

# ═══════════════════════════════════════════
# MCP fetch 기반 공통 HTTP JSON 요청.
# Returns: (status_code, data, text_or_error)
# ═══════════════════════════════════════════
) -> Tuple[int, Optional[Any], str]:
    # .env 미적용 환경에서도 지연/오류를 줄이기 위해 기본 비활성.
    use_mcp_fetch = is_true(os.getenv("USE_MCP_FETCH", "false"))
    mcp_error_text = ""
    mcp_status_code = 500

    if use_mcp_fetch:
        result = mcp_fetch_json(
            url=url,
            method=method,
            headers=headers,
            json_body=json_body,
            timeout=timeout,
        )
        if result.get("success"):
            status_code = int(result.get("status_code", 200))
            data = result.get("data")
            text = result.get("text", "")
            if not text and data is not None:
                try:
                    text = json.dumps(data, ensure_ascii=False)
                except Exception:
                    text = str(data)
            return status_code, data, text

        mcp_error_text = str(result.get("error") or "MCP fetch failed")
        mcp_status_code = int(result.get("status_code", 500))
        logger.warning(f"MCP fetch 실패 -> direct HTTP fallback: {mcp_error_text}")

    direct_status, direct_data, direct_text = _direct_http_json_request(
        method=method,
        url=url,
        json_body=json_body,
        timeout=timeout,
        headers=headers,
    )

    if direct_data is not None:
        return direct_status, direct_data, direct_text
    if 200 <= direct_status < 400:
        return direct_status, direct_data, direct_text

    if use_mcp_fetch:
        combined_error = (
            f"{mcp_error_text} | direct fallback failed: {direct_text}"
            if mcp_error_text
            else direct_text
        )
        return mcp_status_code, None, combined_error

    return direct_status, None, direct_text



# ═══════════════════════════════════
# MCP web-search 서버를 통한 웹 검색.
# ═══════════════════════════════════
def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    try:
        if not query or not query.strip():
            return {"success": False, "error": "Empty search query", "results": []}

        t_start = time.time()
        logger.info(f"[MCP웹검색] 시작 query=\"{query[:100]}\" max_results={max_results}")
        # 서버/도구명은 .vscode/mcp.json 의 실제 등록명과 일치해야 한다 —
        # 과거 "web-search"/"search" 는 설정에 없는 이름이라 항상 not found 였다.
        result = call_mcp_server_tool(
            server_name=_WEB_SEARCH_SERVER,
            tool_name=_WEB_SEARCH_TOOL,
            arguments={"query": query,
                       "num_results": max(1, min(int(max_results or 5), 10))},
            timeout=30,
        )

        if "error" in result:
            logger.warning(f"웹 검색 실패(call_mcp_server_tool): {result['error']}")
            _check_error_with_dns_diag(str(result.get("error", "")))
            return {"success": False, "error": result["error"], "results": []}

        if result.get("isError"):
            error_text = "\n".join(_extract_text_blocks(result)) or "web-search failed"
            logger.warning(f"웹 검색 실패(web-search isError): {error_text}")
            _check_error_with_dns_diag(error_text)
            return {"success": False, "error": error_text, "results": []}

        text_blocks = _extract_text_blocks(result)
        formatted: List[Dict[str, Any]] = []

        for text in text_blocks:
            text = text.strip()
            if not text:
                continue

            parsed = _try_parse_json(text)

            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, dict):
                items = parsed.get("results", [])
            else:
                # mcp-searxng 는 JSON 이 아니라 Title/Description/URL 텍스트 블록을
                # 반환한다 — 전용 파서로 항목 단위 분해. 실패 시에만 통짜 폴백.
                sx = _parse_searxng_results(text)
                if sx:
                    formatted.extend(sx)
                else:
                    formatted.append(_format_search_result(query, text[:700], "#"))
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                formatted.append(_format_search_result(
                    item.get("title", query),
                    item.get("description", "")[:1000],
                    item.get("url", "#"),
                ))

        elapsed = time.time() - t_start
        logger.info(f"[MCP웹검색] 완료 ({elapsed:.1f}s) {len(formatted)}건")
        return {
            "success": True,
            "results": formatted,
            "query": query,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"웹 검색 중 오류: {e}")
        return {"success": False, "error": str(e), "results": []}


# ═══════════════════════════════════
# MCP web-search 기반 현재 날씨 조회.
# ═══════════════════════════════════
def get_current_weather(location: str) -> Dict[str, Any]:
    try:
        logger.debug(f"날씨 조회: {location}")
        query = f"{location} 현재 날씨 기온 습도"
        result = search_web(query, max_results=3)
        if result.get("success"):
            return {
                "success": True,
                "location": location,
                "weather_info": result.get("results", []),
                "timestamp": datetime.now().isoformat(),
                "source": "web_search",
            }
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "location": location,
        }
    except Exception as e:
        logger.error(f"날씨 조회 중 오류: {e}")
        return {"success": False, "error": str(e), "location": location}
