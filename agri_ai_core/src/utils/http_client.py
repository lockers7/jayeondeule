# ════════════════════════════════════════════════════════════════════
# HTTP JSON 클라이언트 — 범용 HTTP 요청 유틸 (stdlib urllib 기반).
# AI/MCP 계층에 의존하지 않는 base util. 하위 계층(chroma/postgresql/
# control 등)에서 안전하게 import 가능.
# --->
# coerce_json_and_text : 응답 본문을 (JSON, text) 튜플로 정규화
# http_json_request    : JSON body/response HTTP 요청 → (status, data, text)
# ════════════════════════════════════════════════════════════════════
import json
from typing import Any, Dict, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

from agri_ai_core.src.utils.json_utils import safe_json_load


# ────────────────────────────────────────────────────────────────────
# 응답 본문을 (JSON dict/list, text) 튜플로 정규화.
# ────────────────────────────────────────────────────────────────────
def coerce_json_and_text(value: Any) -> Tuple[Optional[Any], str]:
    if isinstance(value, (dict, list)):
        return value, json.dumps(value, ensure_ascii=False)
    if value is None:
        return None, ""
    text = str(value)
    parsed = safe_json_load(text)
    if isinstance(parsed, (dict, list)):
        return parsed, text
    return None, text


# ────────────────────────────────────────────────────────────────────
# 직접 HTTP 요청 (urllib). JSON body 송신 + 응답을 (status, data, text) 반환.
#   2xx/3xx              : (status, parsed_json_or_None, raw_text)
#   HTTPError            : (status, parsed_body_or_None, body_text)
#   URLError/기타 예외   : (503/500, None, error_msg)
# ────────────────────────────────────────────────────────────────────
def http_json_request(
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
        except (TypeError, ValueError):
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
        try:
            body = http_err.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(http_err)
        status_code = int(getattr(http_err, "code", 500) or 500)
        parsed_json, _ = coerce_json_and_text(body)
        return status_code, parsed_json, body
    except urlerror.URLError as url_err:
        return 503, None, f"Direct HTTP connection error: {url_err.reason}"
    except Exception as err:
        return 500, None, f"Direct HTTP request failed: {err}"

    parsed_json, parsed_text = coerce_json_and_text(raw_text)
    return status_code, parsed_json, parsed_text
