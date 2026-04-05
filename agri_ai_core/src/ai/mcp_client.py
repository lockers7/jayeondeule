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
# _pick_postgres_tool_name: pick postgres tool name
# _call_postgres_tool: call postgres tool
# postgres_query: postgres query
# search_web: search web
# get_current_weather: get current weather
# ══════════════════════════════════════════════════════════════════════════════════════
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.validators import is_true

logger = setup_logger(__name__)

DEFAULT_PROTOCOL_VERSION = "2024-11-05"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MCP_CONFIG_PATH = PROJECT_ROOT / ".vscode" / "mcp.json"
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
# ════════════════════════════════════════════
def _load_mcp_servers() -> Dict[str, Dict[str, Any]]:
    try:
        if not MCP_CONFIG_PATH.exists():
            logger.error(f"MCP 설정 파일이 없습니다: {MCP_CONFIG_PATH}")
            return {}
        raw = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
        servers = raw.get("mcpServers", {})
        if not isinstance(servers, dict):
            return {}
        return servers
    except Exception as e:
        logger.error(f"MCP 설정 로드 실패: {e}")
        return {}


def _jsonrpc(id_value: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": id_value, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def _find_response(stdout: str, response_id: int) -> Optional[Dict[str, Any]]:
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == response_id:
            return message
    return None


def _extract_text_blocks(result: Dict[str, Any]) -> List[str]:
    contents = result.get("content")
    if not isinstance(contents, list):
        return []

    texts: List[str] = []
    for item in contents:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return texts


def _format_search_result(title: str, snippet: str, url: str, source: str = "web_search") -> Dict[str, Any]:
    """검색 결과 항목을 표준 dict 형태로 생성."""
    return {"title": title, "snippet": snippet, "url": url, "source": source}


def _check_error_with_dns_diag(error_text: str, context: str = "") -> None:
    """에러 텍스트에 DNS 관련 키워드가 있으면 DNS 진단을 1회 실행."""
    if _is_dns_resolution_error(error_text):
        _log_dns_diagnostics_once()


def _try_parse_json(text: str) -> Optional[Any]:
    """텍스트를 JSON으로 파싱 시도. 실패 시 None 반환."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


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
            env=os.environ.copy(),
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

        process.stdin.write(json.dumps(init_request, ensure_ascii=False) + "\n")
        process.stdin.write(json.dumps(call_request, ensure_ascii=False) + "\n")
        process.stdin.flush()

        stdout, stderr = process.communicate(timeout=timeout)

        if stderr:
            # web-search는 "running on stdio"를 stderr로 출력하므로 debug 레벨로 처리
            logger.debug(f"[MCP:{server_name}] stderr: {stderr.strip()}")

        response = _find_response(stdout, 2)
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
        if process:
            try:
                process.kill()
            except Exception:
                pass
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


def _coerce_json_and_text(value: Any) -> Tuple[Optional[Any], str]:
    if isinstance(value, (dict, list)):
        return value, json.dumps(value, ensure_ascii=False)
    if value is None:
        return None, ""
    text = str(value)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed, text
    except Exception:
        pass
    return None, text


def _direct_http_json_request(
    method: str,
    url: str,
    json_body: Optional[Any] = None,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Optional[Any], str]:
    normalized_method = (method or "GET").upper()
    normalized_headers: Dict[str, str] = dict(headers or {})
    body_bytes = None

    if json_body is not None:
        try:
            body_text = json.dumps(json_body, ensure_ascii=False)
        except Exception:
            body_text = str(json_body)
        body_bytes = body_text.encode("utf-8")
        if not any(key.lower() == "content-type" for key in normalized_headers):
            normalized_headers["Content-Type"] = "application/json"

    request = urlrequest.Request(
        url=url,
        data=body_bytes,
        method=normalized_method,
        headers=normalized_headers,
    )

    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            raw_text = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200) or 200)
    except urlerror.HTTPError as http_err:
        body = ""
        try:
            body = http_err.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(http_err)
        status_code = int(getattr(http_err, "code", 500) or 500)
        parsed_json, _ = _coerce_json_and_text(body)
        return status_code, parsed_json, body
    except urlerror.URLError as url_err:
        return 503, None, f"Direct HTTP connection error: {url_err.reason}"
    except Exception as err:
        return 500, None, f"Direct HTTP request failed: {err}"

    parsed_json, parsed_text = _coerce_json_and_text(raw_text)
    return status_code, parsed_json, parsed_text


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
    # fetch 서버 기본 도구 집합. request는 일부 구현체에서 미지원이라 기본에서 제외.
    default_tools = "fetch,http_fetch"
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
            result = call_mcp_server_tool("fetch", tool_name, args, timeout=timeout)
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
        try:
            data = json.loads(raw_text)
        except Exception:
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


def _parse_markdown_table(text: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) < 2:
        return []

    header = [h.strip() for h in table_lines[0].strip("|").split("|")]
    data_start_idx = 1
    if set(table_lines[1].replace("|", "").replace("-", "").replace(" ", "")) == {""}:
        data_start_idx = 2

    rows: List[Dict[str, Any]] = []
    for line in table_lines[data_start_idx:]:
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) != len(header):
            continue
        rows.append(dict(zip(header, cols)))
    return rows


_POSTGRES_TOOL_NAME = os.getenv("MCP_POSTGRES_TOOL_NAME", "query")


def _pick_postgres_tool_name() -> str:
    return _POSTGRES_TOOL_NAME


def _call_postgres_tool(sql: str, timeout: int = 30) -> Dict[str, Any]:
    tool_name = _pick_postgres_tool_name()
    argument_candidates = [
        {"sql": sql},
        {"query": sql},
    ]

    last_error: Dict[str, Any] = {"error": "Unknown MCP postgres error"}
    for args in argument_candidates:
        result = call_mcp_server_tool("postgres", tool_name, args, timeout=timeout)
        if "error" not in result:
            return result
        last_error = result
        error_text = str(result.get("error", "")).lower()
        # 서버 미설치/네트워크 단절 상황에서는 즉시 탈출하여 지연을 최소화
        if any(keyword in error_text for keyword in ("timeout", "eai_again", "not found", "command")):
            break

    return last_error


# ════════════════════════════════════════════════════════
# MCP postgres 서버를 통해 SQL 실행 후 행 데이터를 정규화.
# ════════════════════════════════════════════════════════
def postgres_query(sql: str, timeout: int = 30) -> Dict[str, Any]:
    if not sql or not isinstance(sql, str):
        return {"success": False, "error": "SQL is required", "rows": []}

    result = _call_postgres_tool(sql=sql, timeout=timeout)
    if "error" in result:
        return {"success": False, "error": result["error"], "rows": []}

    if result.get("isError"):
        error_text = "\n".join(_extract_text_blocks(result)) or "MCP postgres execution error"
        return {"success": False, "error": error_text, "rows": []}

    text_blocks = _extract_text_blocks(result)
    if not text_blocks:
        return {"success": True, "rows": [], "raw": result}

    # 1) JSON 파싱 시도
    for text in text_blocks:
        parsed = _try_parse_json(text)

        if isinstance(parsed, list):
            if all(isinstance(item, dict) for item in parsed):
                return {"success": True, "rows": parsed, "raw": result}
            return {"success": True, "rows": [{"value": item} for item in parsed], "raw": result}

        if isinstance(parsed, dict):
            for key in ("rows", "result", "data"):
                value = parsed.get(key)
                if isinstance(value, list):
                    if all(isinstance(item, dict) for item in value):
                        return {"success": True, "rows": value, "raw": result}
                    return {"success": True, "rows": [{"value": item} for item in value], "raw": result}
            return {"success": True, "rows": [parsed], "raw": result}

    # 2) Markdown table 파싱 시도
    for text in text_blocks:
        parsed_table = _parse_markdown_table(text)
        if parsed_table:
            return {"success": True, "rows": parsed_table, "raw": result}

    # 3) 결과가 텍스트만 있는 경우(INSERT/UPDATE 등)
    return {"success": True, "rows": [], "raw": result, "text": "\n".join(text_blocks)}


# ═══════════════════════════════════
# MCP web-search 서버를 통한 웹 검색.
# ═══════════════════════════════════
def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    try:
        if not query or not query.strip():
            return {"success": False, "error": "Empty search query", "results": []}

        t_start = time.time()
        logger.info(f"[MCP웹검색] 시작 query=\"{query[:100]}\" max_results={max_results}")
        result = call_mcp_server_tool(
            server_name="web-search",
            tool_name="search",
            arguments={"query": query, "limit": max(1, min(int(max_results or 5), 10))},
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
                # 비구조 텍스트면 fallback 1건으로 저장
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
