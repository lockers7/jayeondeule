# ══════════════════════════════════════════════════════════
# LLM 클라이언트 핵심 모듈 — Ollama API 통신 및 Tool Use 응답 생성.
# ══════════════════════════════════════════════════════════
import os
import re
import time
import json
import threading
import traceback
from typing import Any, Dict, List, Optional
from queue import Queue as ThreadQueue
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import ollama
except Exception:
    ollama = None

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import NUM_PREDICT, NUM_CTX, NUM_PREDICT_TOOL_CALL, get_ollama_url, get_model_name
from agri_ai_core.src.utils.validators import is_true
from agri_ai_core.src.ai.utils import GREETING_RE as _GREETING_RE
from agri_ai_core.src.ai.llm_response import (
    clean_llm_response,
    _clean_page_content,
    _refine_search_web,
    _refine_fetch_url,
    _refine_realtime_data,
    _refine_tool_result,
    _strip_nav_noise,
    _refine_farm_knowledge,
    _finalize_user_facing_answer,
    _align_markdown_tables,
    _strip_hallucinated_urls,
    _display_width,
    _pad_to_width,
)

logger = setup_logger(__name__)

# 도구 한국어 표시명 매핑
_TOOL_DISPLAY_NAMES = {
    "get_farm_realtime_data": "센서/릴레이 데이터 조회",
    "search_farm_knowledge": "농장 지식 검색",
    "search_web": "웹 검색",
    "fetch_url_content": "웹페이지 내용 수집",
    "control_relay": "장치 제어",
    "search_gas_price": "유가 정보 조회",
}


def _build_tool_detail_message(tool_name: str, tool_args: dict) -> str:
    """도구 호출 시 사용자에게 보여줄 상세 정보 메시지 생성."""
    if tool_name == "get_farm_realtime_data":
        house_id = tool_args.get("house_id", "")
        data_type = tool_args.get("data_type", "all")
        type_label = {"sensor": "센서", "relay": "릴레이", "all": "센서/릴레이"}.get(data_type, data_type)
        return f"{house_id}호 재배사 {type_label} (PostgreSQL)"
    elif tool_name == "search_web":
        query = tool_args.get("query", "")[:30]
        return f"'{query}' 검색 (SearXNG)"
    elif tool_name == "search_farm_knowledge":
        query = tool_args.get("query", "")[:30]
        file_name = tool_args.get("file_name", "")
        if file_name:
            return f"'{file_name}' 문서 검색 (ChromaDB)"
        return f"'{query}' 지식 검색 (ChromaDB)"
    elif tool_name == "fetch_url_content":
        url = tool_args.get("url", "")[:40]
        return f"{url}"
    elif tool_name == "search_gas_price":
        qt = tool_args.get("query_type", "")
        sido = tool_args.get("sido", "")
        label = {"avg_national": "전국 평균", "avg_sido": "시도별", "avg_sigun": "시군구별", "low_price": "최저가"}.get(qt, qt)
        return f"{sido} {label} 유가 (Opinet)" if sido else f"{label} 유가 (Opinet)"
    elif tool_name == "control_relay":
        device = tool_args.get("device_flag", "")
        action = tool_args.get("action", "")
        return f"{device} {action}"
    return ""


def _report_progress(progress_queue: Optional[ThreadQueue], message: str, phase: str = "processing",
                     tool_name: str = None, iteration: int = None, max_iterations: int = None):
    """Tool Use 루프 내부에서 진행 상태를 외부(스트리밍 핸들러)로 보고합니다."""
    if progress_queue is None:
        return
    event = {"message": message, "phase": phase}
    if tool_name:
        event["tool_name"] = tool_name
        event["tool_display"] = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
    if iteration is not None:
        event["iteration"] = iteration
    if max_iterations is not None:
        event["max_iterations"] = max_iterations
    try:
        progress_queue.put_nowait(event)
    except Exception:
        pass  # 큐 오류 시 무시 (진행 상태 누락은 치명적이지 않음)


# 워밍업 관련 전역 변수
# ══════════════════════════════════════════════════════════
_warmup_lock = threading.Lock()
_warmup_started = False
_llm_warmed = False

# 모델 캐싱
_cached_model_name = None
_model_cache_lock = threading.Lock()
_direct_ollama_disabled_reason: Optional[str] = None

# GPU 비율 캐시: {model_name: (gpu_ratio, cached_at)}
_gpu_ratio_cache: Dict[str, tuple] = {}
_GPU_RATIO_CACHE_TTL = 60  # 초: 60초마다 재조회 (VRAM 변동 반영)

def _get_model_gpu_ratio(model_name: str) -> float:
    """Ollama /api/ps 에서 모델의 실제 GPU 탑재 비율을 조회 후 1.2배 적용.
    캐시 TTL 60초. 조회 실패 시 0.0 반환 (보수적 설정 적용).
    × 1.2 적용 이유: VRAM 증설로 탑재율이 올라갈수록 자동으로 높은 티어 선택.
    예) 실제 89.6% × 1.2 = 107.5% → 95%+ 최상위 티어 적용
        실제 60.0% × 1.2 = 72.0%  → 70%+ 티어 적용
    """
    now = time.time()
    if model_name in _gpu_ratio_cache:
        ratio, cached_at = _gpu_ratio_cache[model_name]
        if now - cached_at < _GPU_RATIO_CACHE_TTL:
            return ratio
    # 모델별 GPU 비율 보정 계수: mistral 계열 1.2, 그 외 1.0
    _boost = 1.2 if "mistral" in model_name.lower() else 1.0
    try:
        ollama_url = get_ollama_url().rstrip("/")
        req = urlrequest.Request(f"{ollama_url}/api/ps")
        with urlrequest.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        for m in data.get("models", []):
            if m.get("name", "").startswith(model_name.split(":")[0]):
                total = m.get("size", 0)
                vram  = m.get("size_vram", 0)
                raw_ratio = (vram / total) if total > 0 else 0.0
                ratio = raw_ratio * _boost
                _gpu_ratio_cache[model_name] = (ratio, now)
                logger.debug(
                    f"[GPU비율] {model_name}: {vram/1e9:.1f}GB / {total/1e9:.1f}GB"
                    f" = {raw_ratio*100:.1f}% × {_boost} = {ratio*100:.1f}%"
                )
                return ratio
    except Exception as e:
        logger.debug(f"[GPU비율] 조회 실패 ({e}), 보수적 설정 적용")
    _gpu_ratio_cache[model_name] = (0.0, now)
    return 0.0

def _get_free_vram_mib() -> int:
    """nvidia-smi로 현재 여유 VRAM(MiB) 반환. 조회 실패 시 0 반환 (보수적 설정 적용)."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        free_mib = int(result.stdout.strip().split("\n")[0])
        logger.debug(f"[VRAM여유] {free_mib} MiB")
        return free_mib
    except Exception as e:
        logger.debug(f"[VRAM여유] 조회 실패 ({e}), 보수적 설정 적용")
        return 0

def _get_model_ctx_options(model_name: str, num_predict: int) -> dict:
    """num_ctx 고정(16384) — GPU 100% 유지, CPU 오프로딩/모델 언로드 방지."""
    return {"num_ctx": NUM_CTX, "num_predict": num_predict}

# 환경 변수 설정
os.environ['OLLAMA_MAX_LOADED_MODELS'] = '1'
os.environ['OLLAMA_NUM_PARALLEL'] = '2'
os.environ['OLLAMA_KEEP_ALIVE'] = '-1'  # 모델 상시 GPU 상주 (언로드 방지)


def _use_mcp_fetch() -> bool:
    # MCP fetch는 환경 의존성이 커서 기본값은 비활성화한다.
    return is_true(os.getenv("USE_MCP_FETCH", "false"))


def _use_ollama_package() -> bool:
    return ollama is not None and is_true(os.getenv("USE_OLLAMA_PACKAGE", "true"))


def _use_direct_ollama_http() -> bool:
    return is_true(os.getenv("USE_DIRECT_OLLAMA_HTTP", "true"))


def _is_direct_ollama_enabled() -> bool:
    return _use_direct_ollama_http() and not _direct_ollama_disabled_reason


def _disable_direct_ollama_http(reason: str) -> None:
    global _direct_ollama_disabled_reason
    if _direct_ollama_disabled_reason:
        return
    _direct_ollama_disabled_reason = reason
    logger.warning(f"Ollama direct HTTP 비활성화: {reason}")


def _is_connection_related_error(err: Exception) -> bool:
    message = str(err).lower()
    return any(
        keyword in message
        for keyword in (
            "failed to connect to ollama",
            "ollama connection error",
            "operation not permitted",
            "connection refused",
            "timed out",
            "timeout",
            "mcp server disabled at runtime: fetch",
            "mcp timeout: fetch",
            "direct http is unavailable",
            "no available ollama transport",
        )
    )


# 모델 목록(dict 리스트)에서 이름을 추출하는 공통 헬퍼
# ══════════════════════════════════════════════════════════
def _extract_model_names(models_list) -> List[str]:
    names: List[str] = []
    if not isinstance(models_list, list):
        return names
    for model in models_list:
        if isinstance(model, dict):
            name = model.get("name") or model.get("model")
        else:
            name = getattr(model, "model", None) or getattr(model, "name", None)
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def _pkg_ollama_list_models() -> List[str]:
    if not _use_ollama_package():
        return []
    result = ollama.list()
    models = getattr(result, "models", None)
    if models is None and isinstance(result, dict):
        models = result.get("models", [])
    return _extract_model_names(models or [])


def _build_chat_payload(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    think: Optional[bool] = None,
) -> Dict[str, Any]:
    """Ollama chat API용 공통 payload 빌드."""
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    if keep_alive:
        payload["keep_alive"] = keep_alive
    if think is not None:
        payload["think"] = think
    return payload


def _pkg_ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    think: Optional[bool] = None,
) -> Any:
    if not _use_ollama_package():
        raise RuntimeError("ollama package unavailable")
    return ollama.chat(**_build_chat_payload(model, messages, options, tools, keep_alive, think))




def _build_ollama_url(path: str) -> str:
    base = get_ollama_url().rstrip("/")
    if path.startswith("/"):
        return f"{base}{path}"
    return f"{base}/{path}"


def _direct_ollama_json(
    path: str,
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    url = _build_ollama_url(path)
    body_bytes = None
    headers: Dict[str, str] = {}

    if json_body is not None:
        body_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urlrequest.Request(url=url, data=body_bytes, method=(method or "GET").upper(), headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as http_err:
        body = ""
        try:
            body = http_err.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(http_err)
        raise RuntimeError(f"Ollama HTTP {http_err.code}: {body[:200]}")
    except urlerror.URLError as url_err:
        reason_text = str(url_err.reason)
        if "operation not permitted" in reason_text.lower():
            _disable_direct_ollama_http("runtime network permission denied")
            raise RuntimeError("Ollama direct HTTP is unavailable in this runtime")
        raise RuntimeError(f"Ollama connection error: {url_err.reason}")
    except Exception as err:
        raise RuntimeError(f"Ollama direct request failed: {err}")

    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception as err:
        raise RuntimeError(f"Ollama JSON parse error: {err}")
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama response is not a JSON object")
    return parsed


def _direct_ollama_list_models(timeout: int = 8) -> List[str]:
    data = _direct_ollama_json(path="/api/tags", method="GET", timeout=timeout)
    return _extract_model_names(data.get("models", []))


def _direct_ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    timeout: int = 600,
    think: Optional[bool] = None,
) -> Dict[str, Any]:
    payload = _build_chat_payload(model, messages, options, tools, keep_alive, think)
    return _direct_ollama_json(path="/api/chat", method="POST", json_body=payload, timeout=timeout)




def _mcp_ollama_list_models(timeout: int = 20) -> List[str]:
    from agri_ai_core.src.ai.mcp_client import mcp_fetch_json

    result = mcp_fetch_json(url=f"{get_ollama_url()}/api/tags", method="GET", timeout=timeout)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "MCP tags call failed")

    data = result.get("data")
    if not isinstance(data, dict):
        return []
    return _extract_model_names(data.get("models", []))


def _mcp_ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    timeout: int = 120,
    think: Optional[bool] = None,
) -> Dict[str, Any]:
    from agri_ai_core.src.ai.mcp_client import mcp_fetch_json

    payload = _build_chat_payload(model, messages, options, tools, keep_alive, think)
    result = mcp_fetch_json(
        url=f"{get_ollama_url()}/api/chat",
        method="POST",
        json_body=payload,
        timeout=timeout,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "MCP chat call failed")

    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Ollama chat 응답 파싱 실패")
    return data




def _serialize_for_log(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize_for_log(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_log(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: _serialize_for_log(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def _log_llm_request_json(model, messages, options, tools, keep_alive):
    try:
        payload = _build_chat_payload(model, _serialize_for_log(messages),
                                       _serialize_for_log(options) if options else None,
                                       _serialize_for_log(tools) if tools else None,
                                       keep_alive)
        logger.info(
            "[LLM 호출 JSON 요청]\n%s",
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )
    except Exception as log_err:
        logger.warning(f"[LLM 요청 JSON 로깅 실패] {log_err}")


def _log_llm_response_json(result, transport, elapsed):
    try:
        if isinstance(result, dict):
            response_json = result
        elif hasattr(result, "model_dump"):
            response_json = result.model_dump()
        elif hasattr(result, "__dict__"):
            response_json = {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
        else:
            response_json = str(result)
        logger.info(
            "[LLM 호출 JSON 응답] transport=%s (%.1fs)\n%s",
            transport,
            elapsed,
            json.dumps(response_json, ensure_ascii=False, indent=2, default=str),
        )

        # [PERF:대화] Ollama 응답 시간 분해 (나노초→초)
        if isinstance(response_json, dict):
            _total_ns = response_json.get("total_duration", 0)
            _load_ns = response_json.get("load_duration", 0)
            _prompt_ns = response_json.get("prompt_eval_duration", 0)
            _eval_ns = response_json.get("eval_duration", 0)
            _prompt_cnt = response_json.get("prompt_eval_count", 0)
            _eval_cnt = response_json.get("eval_count", 0)
            if _total_ns > 0:
                _eval_tok_per_s = (_eval_cnt / (_eval_ns / 1e9)) if _eval_ns > 0 else 0
                logger.debug(
                    f"[PERF:대화] Ollama내부시간: "
                    f"모델로드={_load_ns / 1e9:.1f}s, "
                    f"프롬프트처리={_prompt_ns / 1e9:.1f}s({_prompt_cnt}tok), "
                    f"답변생성={_eval_ns / 1e9:.1f}s({_eval_cnt}tok, {_eval_tok_per_s:.1f}tok/s), "
                    f"총={_total_ns / 1e9:.1f}s"
                )
    except Exception as log_err:
        logger.warning(f"[LLM 응답 JSON 로깅 실패] {log_err}")


def _ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
):
    # options 안의 "think" 키를 최상위 레벨로 승격 (Ollama API 요구사항)
    think_value = None
    if options and "think" in options:
        think_value = options.pop("think")

    errors: List[str] = []
    msg_count = len(messages or [])
    tool_count = len(tools or [])
    t_start = time.time()

    logger.info(
        f"[Ollama요청] model={model} messages={msg_count} tools={tool_count} "
        f"options={{{', '.join(f'{k}={v}' for k, v in (options or {}).items())}}}"
    )

    # LLM 호출 전체 JSON 로깅 (system prompt, user prompt, tools, options 포함)
    _log_llm_request_json(model, messages, options, tools, keep_alive)

    _TRANSPORTS = [
        ("package", _use_ollama_package, _pkg_ollama_chat),
        ("MCP",     _use_mcp_fetch,      _mcp_ollama_chat),
        ("direct",  _is_direct_ollama_enabled, _direct_ollama_chat),
    ]

    for label, check_fn, call_fn in _TRANSPORTS:
        if not check_fn():
            continue
        try:
            result = call_fn(
                model=model, messages=messages, options=options,
                tools=tools, keep_alive=keep_alive, think=think_value,
            )
            elapsed = time.time() - t_start
            _log_llm_response_json(result, label, elapsed)
            resp_content = _extract_message_content(result)
            log_msg = (
                f"[Ollama응답] transport={label} ({elapsed:.1f}s) "
                f"답변길이={len(resp_content)}자"
            )
            if label == "package":
                resp_tool_calls = _extract_tool_calls(
                    _normalize_assistant_message(
                        result.message if hasattr(result, 'message')
                        else (result.get('message', {}) if isinstance(result, dict) else {})
                    )
                )
                log_msg += f" tool_calls={len(resp_tool_calls)}개"
            logger.info(log_msg)
            return result
        except Exception as err:
            errors.append(str(err))
            if label == "direct":
                raise
            logger.warning(f"Ollama chat 호출 실패({label}) -> fallback: {err}")

    error_tail = errors[-1] if errors else "all transports unavailable"
    raise RuntimeError(f"No available Ollama transport: {error_tail}")




def _extract_message_content(response: Any) -> str:
    if hasattr(response, "message"):
        message = getattr(response, "message")
        if hasattr(message, "content"):
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content

    if isinstance(response, dict):
        message = response.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        response_text = response.get("response")
        if isinstance(response_text, str):
            return response_text
    return ""


def _normalize_assistant_message(assistant_message: Any) -> Dict[str, Any]:
    if isinstance(assistant_message, dict):
        normalized: Dict[str, Any] = {
            "role": assistant_message.get("role") or "assistant",
            "content": assistant_message.get("content") or "",
        }
        tool_calls = assistant_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            normalized["tool_calls"] = tool_calls
        return normalized

    normalized = {
        "role": getattr(assistant_message, "role", "assistant"),
        "content": getattr(assistant_message, "content", "") or "",
    }
    tool_calls = getattr(assistant_message, "tool_calls", None)
    if tool_calls:
        try:
            normalized["tool_calls"] = list(tool_calls)
        except Exception:
            normalized["tool_calls"] = tool_calls
    return normalized


# LLM 응답에서 도구 호출 추출 (tool_calls 필드 우선, content에 JSON 도구 호출이 텍스트로 출력된 경우도 파싱)
def _extract_tool_calls(assistant_message: Dict[str, Any]) -> List[Any]:
    tool_calls = assistant_message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        return tool_calls

    # content에 도구 호출 JSON이 텍스트로 출력된 경우 파싱 시도
    # 예: {"name": "search_farm_knowledge", "arguments": {...}}
    content = assistant_message.get("content", "").strip()
    if content.startswith("{") and content.endswith("}"):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
                # 도구 호출 JSON을 정규 tool_call 형식으로 변환
                tool_call = {"function": {"name": parsed["name"], "arguments": parsed["arguments"]}}
                # content를 비워서 최종답변으로 사용되지 않도록 함
                assistant_message["content"] = ""
                assistant_message["tool_calls"] = [tool_call]
                logger.warning(
                    f"[Tool Use] content에서 도구호출 JSON 감지 → tool_calls로 변환: {parsed['name']}"
                )
                return [tool_call]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return []


def _extract_tool_name(tool_call: Any) -> Optional[str]:
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        name = tool_call.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    function = getattr(tool_call, "function", None)
    if function is not None:
        name = getattr(function, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    name = getattr(tool_call, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _extract_tool_arguments(tool_call: Any) -> Dict[str, Any]:
    raw_args: Any = None
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        if isinstance(function, dict):
            raw_args = function.get("arguments")
        if raw_args is None:
            raw_args = tool_call.get("arguments")
    else:
        function = getattr(tool_call, "function", None)
        if function is not None:
            raw_args = getattr(function, "arguments", None)
        if raw_args is None:
            raw_args = getattr(tool_call, "arguments", None)

    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _coerce_numeric_id(provided_id, default_id):
    """LLM이 비정수 값을 ID로 넣는 경우 기본값(정수)으로 교정한다."""
    if provided_id in (None, "") or default_id in (None, ""):
        return provided_id
    provided_text = str(provided_id).strip()
    default_text = str(default_id).strip()
    if default_text.isdigit() and not provided_text.isdigit():
        return default_text
    return provided_id



def _normalize_tool_arguments(
    tool_name: str,
    tool_args: Dict[str, Any],
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
    user_query: str = "",
) -> Dict[str, Any]:
    args = tool_args or {}
    default_args = (default_tool_args or {}).get(tool_name, {}) or {}

    def _pick(key: str, fallback: Any = None) -> Any:
        value = args.get(key)
        if value is None or value == "":
            value = default_args.get(key)
        if value is None or value == "":
            value = fallback
        return value

    if tool_name == "search_web":
        return {
            "query": _pick("query"),
            "n_results": _pick("n_results"),
            "auto_fetch_max": _pick("auto_fetch_max"),
        }
    # 시스템관리자 farm_id 결정: LLM 대화에서 구체적 농장 지정 → 해당 농장, 미지정 → 세션 선택 농장
    def _resolve_admin_farm_id(session_fid, llm_fid_raw):
        """시스템관리자(세션=0)일 때 LLM 판단값으로 farm_id 결정.
        숫자 → 그대로, 농장명 → DB 역조회, 무효 → 세션값 유지."""
        if str(session_fid) != "0":
            return session_fid  # 농장사용자는 세션값 강제
        _llm_fid = str(llm_fid_raw or "").strip()
        if not _llm_fid or _llm_fid == "0":
            return session_fid
        if _llm_fid.isdigit():
            return _llm_fid  # LLM이 숫자 farm_id 전달 (정상)
        # 농장명(문자열) → farm_id 역조회
        try:
            from agri_ai_core.src.ai.tools_executor import _get_farm_name, _farm_name_cache, _farm_name_cache_loaded
            if not _farm_name_cache_loaded:
                _get_farm_name("0")  # 캐시 로드 트리거
            for fid, fname in _farm_name_cache.items():
                if fname == _llm_fid or _llm_fid in fname:
                    logger.info(f"[farm_id해석] 농장명 '{_llm_fid}' → farm_id={fid}")
                    return fid
        except Exception as e:
            logger.warning(f"[farm_id해석] 농장명 역조회 실패: {e}")
        return session_fid  # 매칭 실패 → 세션값 유지

    if tool_name == "search_farm_knowledge":
        _tool_query = _pick("query") or ""
        _meta_kws = ("파일", "학습", "목록", "리스트", "자료", "문서", "업로드", "RAG", "데이터")
        _user_has_meta = any(kw in (user_query or "") for kw in _meta_kws)
        _query_has_meta = any(kw in _tool_query for kw in _meta_kws)
        _session_fid = default_args.get("farm_id")
        _farm_id = _resolve_admin_farm_id(_session_fid, args.get("farm_id"))
        result = {
            "query": _tool_query,
            "n_results": _pick("n_results", 5),
            "file_name": _pick("file_name"),
            "farm_id": _farm_id,
            "house_id": _pick("house_id"),
        }
        if _user_has_meta and not _query_has_meta:
            result["_meta_hint"] = True
        return result
    if tool_name == "delete_farm_knowledge":
        _session_fid = default_args.get("farm_id")
        _farm_id = _resolve_admin_farm_id(_session_fid, args.get("farm_id"))
        return {
            "file_name": _pick("file_name"),
            "farm_id": _farm_id,
        }
    if tool_name == "get_farm_realtime_data":
        default_farm_id = default_args.get("farm_id")
        default_house_id = default_args.get("house_id")

        # farm_id 결정: _resolve_admin_farm_id 공용 로직 사용
        # 시스템관리자(세션=0) → LLM 판단값 허용, 농장사용자 → 세션값 강제
        farm_id = _resolve_admin_farm_id(default_farm_id, args.get("farm_id"))

        # house_id: LLM이 선택 가능 (특정 재배사 조회 허용), 미지정 시 세션값 사용
        # house_id=0은 생육정보 전용 공통재배사이므로 센서/릴레이 데이터 없음 → 세션값으로 보정
        house_id = _coerce_numeric_id(_pick("house_id"), default_house_id)
        if str(house_id or "").strip() == "0":
            logger.info(
                f"[farm_id] house_id=0(공통재배사) → 세션값={default_house_id} 보정"
            )
            house_id = default_house_id

        # data_type: 'relay'/'sensor' 단독 요청 시 AI분석·알고리즘 추천값 없어 모델이 hallucination
        # → 항상 'all'로 강제하여 완전한 데이터(센서+릴레이+AI권장) 반환
        data_type = "all"

        return {
            "house_id": house_id,
            "farm_id": farm_id,
            "data_type": data_type,
        }
    if tool_name == "search_gas_price":
        return {
            "query_type": _pick("query_type", "avg_national"),
            "sido": _pick("sido"),
            "sigun": _pick("sigun"),
            "prodcd": _pick("prodcd", "B027"),
            "fuel_name": _pick("fuel_name"),
        }
    return args


# Ollama에서 사용 가능한 모델 목록 가져오기
# --->
# ══════════════════════════════════════════════════════════
def _get_available_models():
    if _use_ollama_package():
        try:
            return _pkg_ollama_list_models()
        except Exception as pkg_err:
            logger.warning(f"Ollama 모델 ���록 조회 실패(package) -> MCP/direct fallback: {pkg_err}")

    if _use_mcp_fetch():
        try:
            return _mcp_ollama_list_models()
        except Exception as mcp_err:
            logger.warning(f"Ollama 모델 목록 조회 실패(MCP) -> direct fallback: {mcp_err}")

    if _is_direct_ollama_enabled():
        try:
            return _direct_ollama_list_models()
        except Exception as direct_err:
            logger.warning(f"Ollama 모델 목록 조회 실패(direct): {direct_err}")
            return []

    return []


# 환경 설정에서 모델명을 가져오거나 기본값을 반환 (캐싱)
# ══════════════════════════════════════════════════════════
def _get_model_name() -> str:
    global _cached_model_name

    # 캐시된 모델 이름이 있으면 바로 반환
    with _model_cache_lock:
        if _cached_model_name:
            return _cached_model_name

    preferred_model = get_model_name()
    fallback_model = "qwen3:latest"

    logger.info(f"[모델선택] 설정 모델: {preferred_model}, 폴백 모델: {fallback_model}")

    # 사용 가능한 모델 목록 조회
    available_models = _get_available_models()
    logger.info(f"[모델선택] 사용 가능 모델: {available_models}")

    # 선호 모델이 있는지 확인
    if preferred_model in available_models:
        logger.info(f"[모델선택] 선호 모델 '{preferred_model}' 사용")
        with _model_cache_lock:
            _cached_model_name = preferred_model
        return preferred_model

    # 선호 모델이 없으면 폴백 모델 확인
    if fallback_model in available_models:
        logger.warning(f"[모델선택] 선호 모델 '{preferred_model}'을 찾을 수 없어 '{fallback_model}' 사용")
        with _model_cache_lock:
            _cached_model_name = fallback_model
        return fallback_model

    # 둘 다 없으면 선호 모델 반환 (Ollama가 자동 다운로드 시도)
    logger.info(f"[모델선택] 모델 '{preferred_model}'을 사용합니다 (필요시 자동 다운로드)")
    with _model_cache_lock:
        _cached_model_name = preferred_model
    return preferred_model


# LLM 워밍업
# LLM 워밍업 수행
# ══════════════════════════════════════════════════════════
def _perform_llm_warmup():
    global _llm_warmed
    if _llm_warmed:
        return

    try:
        model_name = _get_model_name()
        _ollama_chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a concise assistant. Respond with one word."},
                {"role": "user", "content": "ping"}
            ],
            options={
                "temperature": 0.0,
                "top_p": 0.1,
                "top_k": 1,
                "num_predict": 4
            }
        )
        _llm_warmed = True
        logger.debug("LLM warm-up completed.")
    except Exception as warm_err:
        logger.warning(f"LLM warm-up failed: {warm_err}")


# 백그라운드 워밍업 초기화
# 백그라운드 워밍업 초기화
# ══════════════════════════════════════════════════════════
def initialize_background_warmup(farm_id=None, house_id=None, farm_name=None, house_name=None):
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True

    def _warmup_runner():
        _perform_llm_warmup()

    threading.Thread(target=_warmup_runner, daemon=True).start()




def _emit_question_log_once(
    user_query: str,
    farm_name: Optional[str],
    max_tool_iterations: int,
    tools_count: int,

# 질문 상세 로그는 호출당 1회만 출력한다.
# ══════════════════════════════════════════════════════════
) -> None:
    if not is_true(os.getenv("LLM_VERBOSE_QUESTION_LOG", "true")):
        return

    raw_query = user_query or ""
    logger.debug(
        f"[질문상세] tools={tools_count} max_iter={max_tool_iterations} "
        f"farm={farm_name or '-'} query_len={len(raw_query)}"
    )




# 도구 결과 정제 (tool_result → LLM 메시지 추가 전 지능형 축약)
# ══════════════════════════════════════════════════════════




# 사용된 도구 목록으로 응답 유형 결정.
# ══════════════════════════════════════════════════════════
def _determine_response_type(tools_used: List[str]) -> str:
    if "search_web" in tools_used or "fetch_url_content" in tools_used:
        return "web_search"
    if "get_farm_realtime_data" in tools_used:
        return "farm_data"
    if "search_farm_knowledge" in tools_used:
        return "knowledge"
    return "general"


# 구조화된 응답 결과 생성.
# ══════════════════════════════════════════════════════════
def _build_structured_result(
    response_text: str,
    sources: list,
    tools_used: list,
) -> Dict[str, Any]:
    # 출처 URL 기반 중복 제거 (동일 URL 최초 1건만 유지)
    deduped_sources: list = []
    seen_urls: set = set()
    for src in (sources or []):
        url = (src.get("url") or "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped_sources.append(src)
        elif not url:
            deduped_sources.append(src)

    return {
        "response": response_text,
        "sources": deduped_sources,
        "tools_used": tools_used if tools_used else [],
        "response_type": _determine_response_type(tools_used),
    }


# 인사/잡담만으로 구성된 턴 쌍(user+assistant)을 제외한다.
# ══════════════════════════════════════════════════════════
def _filter_greeting_turns(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered = []
    i = 0
    while i < len(history):
        turn = history[i]
        role = turn.get("role", "")
        content = turn.get("content", "").strip()

        # user 메시지가 짧고(30자 미만) 인사 패턴에 매칭되면 해당 쌍 스킵
        if (
            role == "user"
            and len(content) < 30
            and _GREETING_RE.search(content)
            and i + 1 < len(history)
            and history[i + 1].get("role") == "assistant"
        ):
            i += 2  # user + assistant 쌍 건너뜀
            continue

        filtered.append(turn)
        i += 1
    return filtered


# 일반 대화 여부 판단 (순수 대화 vs 도구 필요 요청)
# ══════════════════════════════════════════════════════════
_CONVERSATIONAL_EXTRA_RE = re.compile(
    r"^(맞아|그렇구나|알겠어|알겠습니다|응|넵|네|오케이|오케|ㅎㅎ|ㅋㅋ|ㄱㄱ"
    r"|잘됐|잘됐네|좋네|좋겠다|다행|아 그래|그렇군|그렇구|알았어|이해"
    r"|그랬군|저런|힘드셨겠다|괜찮아|괜찮으세요)"
)
_PREV_CONV_REF_WORDS = ("아까", "방금", "이전에", "그때 뭐", "지난번", "이전 대화", "아까 말한", "방금 말한")


def _is_conversational_query(query: str) -> bool:
    """요구/지시가 아닌 순수 일반 대화인지 판단한다.
    True: 인사·감탄·짧은 반응·이전 대화 참조 등 → 직전 대화 맥락 포함 가능
    False(기본): 데이터 조회·장치 제어·정보 요청 등 → 최신 도구 데이터 우선, assistant 맥락 불포함
    """
    q = (query or "").strip()
    if not q:
        return True
    # 인사 패턴 (기존 GREETING_RE)
    if len(q) <= 30 and _GREETING_RE.search(q):
        return True
    # 추가 감탄/반응 패턴 (짧은 경우만)
    if len(q) <= 20 and _CONVERSATIONAL_EXTRA_RE.search(q):
        return True
    # 이전 대화 참조 질문 ("아까 뭐라고 했어?", "방금 말한 온도가 뭐야?")
    if any(ref in q for ref in _PREV_CONV_REF_WORDS):
        return True
    return False


# 농장 기본 정보 텍스트 생성
# DB에서 농장/재배사 정보를 조회하여 system prompt에 삽입할 텍스트 생성
# Returns: str | None: 농장 정보 텍스트
# ══════════════════════════════════════════════════════════
def _build_farm_info_text() -> str:
    try:
        from agri_ai_core.src.postgresql.reader import read_farm_house_list
        from agri_ai_core.src.postgresql.connection import db_session

        # 농장 기본 정보 (주요 재배 작물, 주소 포함)
        with db_session() as db:
            farms = db.fetch_all(
                "SELECT f.farm_id, f.farm_name, f.addr, "
                "c.code_name AS main_crop, f.rmks "
                "FROM FARM_M_INFO f "
                "LEFT JOIN CODE_M_INFO c ON c.code_id = 'main_prdt' AND c.code_item = f.main_prdt "
                "WHERE f.farm_id != 0",
                as_dict=True,
            )

        if not farms:
            return None

        lines = []
        for farm in farms:
            lines.append(f"- 농장명: {farm.get('farm_name', '-')}")
            if farm.get("main_crop"):
                lines.append(f"- 주요 재배 작물: {farm['main_crop']}")
            if farm.get("addr"):
                lines.append(f"- 주소: {farm['addr']}")
            if farm.get("rmks"):
                lines.append(f"- 비고: {farm['rmks']}")

        # 재배사 목록
        house_list = read_farm_house_list()
        if house_list:
            house_names = [h.get("hous_name", "") for h in house_list]
            lines.append(f"- 재배사: {', '.join(house_names)}")

        return "\n".join(lines) if lines else None
    except Exception as e:
        logger.debug(f"[농장정보] 조회 실패: {e}")
        return None


def _execute_and_merge_tools(
    tool_calls: list, messages: list, default_tool_args: dict,
    user_query: str, tools_used: list, collected_sources: list,
    execute_tool, iteration: int, max_tool_iterations: int,
    progress_queue=None,
):
    """도구 호출 실행, 결과 정제, 메시지 병합을 처리.
    - 동일 반복 내 중복 호출 제거 (같은 함수+인자 캐시)
    - 결과를 1개 tool 메시지로 병합 (컨텍스트 절약)
    - search_web 출처 수집
    """
    logger.info(f"[Tool Use] 도구호출 {len(tool_calls)}건 감지 (반복{iteration + 1})")
    _results = []
    _dedup_cache = {}

    for tc_idx, tool_call in enumerate(tool_calls, start=1):
        tool_name = _extract_tool_name(tool_call)
        tool_args = _extract_tool_arguments(tool_call)
        if not tool_name:
            logger.warning(f"[Tool Use] 도구 이름 파싱 실패: {tool_call}")
            continue

        tool_args = _normalize_tool_arguments(
            tool_name, tool_args, default_tool_args=default_tool_args, user_query=user_query,
        )

        # 중복 호출 캐시
        _key = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))
        if _key in _dedup_cache:
            logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name} → 중복 생략")
            continue

        logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name}({tool_args})")

        # 진행 상태
        display = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
        detail = _build_tool_detail_message(tool_name, tool_args)
        _report_progress(
            progress_queue,
            f"{display} 중... ({tc_idx}/{len(tool_calls)})" + (f" — {detail}" if detail else ""),
            "tool_calling", tool_name=tool_name,
            iteration=iteration + 1, max_iterations=max_tool_iterations,
        )

        if tool_name not in tools_used:
            tools_used.append(tool_name)

        # 실행
        t0 = time.time()
        result = execute_tool(tool_name, tool_args)
        elapsed = time.time() - t0
        logger.info(f"[도구결과] [{tc_idx}/{len(tool_calls)}] {tool_name} ({elapsed:.1f}s) 결과길이={len(result or '')}자")

        _report_progress(
            progress_queue, f"{display} 완료 ({elapsed:.1f}초, {len(result or '')}자 수신)",
            "tool_done", tool_name=tool_name,
            iteration=iteration + 1, max_iterations=max_tool_iterations,
        )
        logger.info(f"[도구결과데이터] {tool_name}:\n{result}")

        # search_web 출처 수집
        if result and tool_name == "search_web":
            try:
                _, sources = _refine_search_web(result, user_query)
                collected_sources.extend(sources)
            except (json.JSONDecodeError, TypeError):
                pass

        # 정제
        refined = _refine_tool_result(tool_name, result, user_query)
        logger.info(f"[도구정제] {tool_name} 원본={len(result or '')}자 → 정제={len(refined)}자")
        _results.append(refined)
        _dedup_cache[_key] = True

    # 결과 병합 (적정범위 중복 제거 포함)
    if _results:
        _seen = set()
        deduped = []
        for r in _results:
            parts = r.split(" | ")
            filtered = []
            for part in parts:
                if part.startswith("적정범위(공통):"):
                    if "적정범위(공통)" not in _seen:
                        _seen.add("적정범위(공통)")
                        filtered.append(part)
                else:
                    filtered.append(part)
            deduped.append(" | ".join(filtered))
        merged = "\n".join(deduped)
        messages.append({"role": "tool", "content": merged})
        logger.info(f"[도구결과병합] {len(_results)}건 → 1메시지 ({len(merged)}자)")


def _check_answer_retry(
    final_answer: str, user_query: str, tools_used: List[str],
    iteration: int, max_iterations: int, done_reason: str,
    had_tools: bool, retry_state: dict,
) -> Optional[str]:
    """LLM 답변을 검증하고, 재시도가 필요하면 재시도 메시지를 반환. 불필요하면 None.
    retry_state: 각 유형별 중복 방지 플래그 딕셔너리 (호출자에서 관리)
    """
    _stripped = final_answer.strip()
    _can_retry = iteration < max_iterations - 1

    # 1) 1차 반복 토큰 한도 도달 → 도구 사용 강제
    if iteration == 0 and done_reason == "length" and had_tools:
        _relay_kws = ("반대로", "반전", "셋팅", "설정", "제어", "켜", "꺼", "가동", "중지")
        if any(kw in user_query for kw in _relay_kws):
            msg = ("릴레이 제어 요청은 반드시 control_relay 도구를 호출해야 합니다. "
                   "이전 대화의 답변을 복사하지 마세요. "
                   "먼저 get_farm_realtime_data(data_type='all', house_id='1')로 현재 상태를 확인하고, "
                   "control_relay로 실제 제어를 수행하세요.")
        else:
            msg = ("위 요청을 처리하려면 반드시 도구를 호출해야 합니다. "
                   "직접 답변하지 말고 적절한 도구를 호출하세요.")
        logger.warning(f"[Tool Use] 1차 반복 토큰한도(length) → 도구 강제 재시도")
        return msg

    # 2) 삭제 의도 감지 + delete 미호출
    _delete_phrases = ("삭제", "지웠", "제거", "지울 수 없", "찾을 수 없어 삭제")
    if (any(p in _stripped for p in _delete_phrases)
            and "delete_farm_knowledge" not in tools_used
            and _can_retry and not retry_state.get("delete")):
        retry_state["delete"] = True
        logger.warning(f"[Tool Use] 삭제 의도 감지 + delete 미호출 (반복{iteration + 1}) → 재시도")
        return f"반드시 delete_farm_knowledge 도구를 호출하여 삭제를 실행하세요. 원래 요청: \"{user_query}\""

    # 3) 학습/파일 내용 감지 + search 미호출
    _knowledge_hints = ("학습", "파일", "문서", "목록", "리스트", ".pdf", ".csv", ".txt", "farm_scope", "자료")
    if (any(kw in _stripped for kw in _knowledge_hints)
            and "search_farm_knowledge" not in tools_used
            and "delete_farm_knowledge" not in tools_used
            and _can_retry and not retry_state.get("knowledge")):
        retry_state["knowledge"] = True
        logger.warning(f"[Tool Use] 학습/파일 내용 감지 + search 미호출 (반복{iteration + 1}) → 재시도")
        return (f"반드시 search_farm_knowledge 도구를 호출하여 실제 데이터를 검색한 후 답변하세요. "
                f"원래 요청: \"{user_query}\"")

    # 4) 릴레이 제어 답변 + control_relay 미호출
    _relay_done = ("설정했어요", "설정했습니다", "제어했어요", "제어했습니다", "완료했어요", "완료했습니다",
                   "변경했어요", "변경했습니다", "반전했어요", "반전했습니다", "전환했어요", "전환했습니다",
                   "켜드렸어요", "꺼드렸어요", "켰어요", "껐어요", "켜줬어요", "꺼줬어요",
                   "켜드렸습니다", "꺼드렸습니다", "성공적으로 켜", "성공적으로 꺼")
    if (any(p in _stripped for p in _relay_done)
            and "control_relay" not in tools_used
            and _can_retry and not retry_state.get("relay")):
        retry_state["relay"] = True
        logger.warning(f"[Tool Use] 릴레이 답변 + control_relay 미호출 (반복{iteration + 1}) → 재시도")
        return f"이전 답변을 복사하지 말고, 반드시 control_relay 도구를 호출하세요. 원래 요청: \"{user_query}\""

    # 5) 도구 결과 raw 덤프 (JSON 그대로 출력)
    if (_stripped.startswith('{"content":')
            and "get_farm_realtime_data" in tools_used
            and "control_relay" not in tools_used
            and _can_retry and not retry_state.get("dump")):
        retry_state["dump"] = True
        logger.warning(f"[Tool Use] raw 덤프 감지 (반복{iteration + 1}) → 재시도")
        return f"도구 결과를 그대로 출력하지 말고 한국어로 자연스럽게 설명하세요. 원래 요청: \"{user_query}\""

    # 6) JSON 형식 응답
    if _stripped.startswith("{") and _stripped.endswith("}") and _can_retry:
        try:
            if isinstance(json.loads(_stripped), dict) and not retry_state.get("json"):
                retry_state["json"] = True
                logger.warning(f"[Tool Use] JSON 응답 감지 (반복{iteration + 1}) → 자연어 재생성")
                return f"JSON이 아닌 한국어 문장으로 답변하세요. 원래 요청: \"{user_query}\""
        except (json.JSONDecodeError, TypeError):
            pass

    # 7) 도구 호출 후 짧은 답변 (대기 문구)
    if (tools_used and len(_stripped) < 80 and _can_retry
            and not _stripped.startswith("|") and not retry_state.get("short")):
        retry_state["short"] = True
        logger.warning(f"[Tool Use] 짧은 답변 감지 (반복{iteration + 1}, {len(_stripped)}자) → 재시도")
        return (f"도구 결과가 이미 제공되었습니다. 대기 문구 없이 바로 답변하세요. "
                f"정보 부족 시 search_web으로 추가 검색하세요. 원래 요청: \"{user_query}\"")

    return None  # 재시도 불필요


def _build_conversation_context(messages: list, conversation_history: list, user_query: str):
    """하이브리드 대화 컨텍스트를 messages 리스트에 주입.
    - system 메시지(관련 과거 대화): 400자 제한, 참고용 명시
    - 최근 턴: system role로 묶어 참고용 맥락 주입 (user/assistant role 오염 방지)
    - 요구/지시 쿼리: assistant 이전 응답 제외 (최신 도구 데이터 우선)
    - 유사 중복 턴 자동 제거
    """
    system_context = [t for t in conversation_history if t.get("role") == "system"]
    actual_turns = [t for t in conversation_history if t.get("role") != "system"]
    filtered_turns = _filter_greeting_turns(actual_turns)
    skipped = len(actual_turns) - len(filtered_turns)

    # 관련 과거 대화 주입
    for ctx in system_context:
        content = ctx.get("content", "")[:400]
        if len(ctx.get("content", "")) > 400:
            content += "..."
        messages.append({"role": "system", "content": f"[이전 대화 요약 - 참고용, 답변 근거로 사용 금지]\n{content}"})

    # 쿼리 유형 판단
    _user_query_stripped = (user_query or "").strip()
    _user_refs_number = bool(re.search(r'\d+번', _user_query_stripped))
    _is_conv = _is_conversational_query(user_query)
    if not _is_conv:
        logger.info("[멀티턴] 요구/지시 쿼리 감지 → assistant 이전 맥락 제외 (최신 데이터 우선)")

    # 최근 턴 필터링 및 조립
    _context_parts = []
    _skip_next_assistant = False
    _prev_assistant_prefix = ""
    _dedup_count = 0

    for turn in filtered_turns:
        role, content = turn.get("role", "user"), turn.get("content", "")

        # 빈/실패 assistant 응답 제거
        if role == "assistant":
            if not content.strip():
                _skip_next_assistant = False
                continue
            if len(content.strip()) < 30 and content.strip().rstrip(".") in ("확인이 필요합니다", "확인이 필요해요", "정보가 없습니다"):
                _skip_next_assistant = False
                continue

        # 중복 user 턴 대응 assistant 스킵
        if _skip_next_assistant and role == "assistant":
            _skip_next_assistant = False
            continue

        # 현재 질문과 동일한 과거 user 턴 제거
        if role == "user" and content.strip() == _user_query_stripped:
            _skip_next_assistant = True
            continue

        # 직전 대화 내 연속 동일 user 질문 제거
        if role == "user" and _context_parts:
            _last = next((cp[5:] for cp in reversed(_context_parts) if cp.startswith("사용자: ")), None)
            if _last and _last.strip()[:60] == content.strip()[:60]:
                _skip_next_assistant = True
                _dedup_count += 1
                continue

        _skip_next_assistant = False

        # 유사 assistant 답변 중복 제거 (앞 150자 80% 이상 유사)
        if role == "assistant" and len(content) > 80:
            _cur_prefix = content.strip()[:150]
            if _prev_assistant_prefix and _cur_prefix:
                _common = sum(1 for a, b in zip(_prev_assistant_prefix, _cur_prefix) if a == b)
                _max_len = max(len(_prev_assistant_prefix), len(_cur_prefix))
                if _max_len > 0 and _common / _max_len > 0.8:
                    removed = min(2, len(_context_parts))
                    for _ in range(removed):
                        _context_parts.pop()
                    _dedup_count += 1
            _prev_assistant_prefix = _cur_prefix

        # assistant 컨텐츠 처리
        if role == "assistant":
            if not _is_conv:
                continue  # 요구/지시: assistant 이전 응답 전체 제외
            # 릴레이 제어 결과는 내용 대체
            _relay_indicators = ("릴레이", "AI 환경 판단", "AI 권장", "반대로")
            _done_indicators = ("설정했어요", "변경했어요", "제어했어요", "반전했어요", "전환했어요",
                                "설정했습니다", "변경했습니다", "제어했습니다",
                                "켜드렸어요", "꺼드렸어요", "켰어요", "껐어요", "켜줬어요", "꺼줬어요",
                                "켜드렸습니다", "꺼드렸습니다", "성공적으로 켜", "성공적으로 꺼")
            if any(i in content for i in _relay_indicators) and any(i in content for i in _done_indicators):
                content = "(이전 제어 완료)"
            else:
                _has_list = bool(
                    re.search(r'\d+[\.\)]\s*\*{0,2}\S+\.(pdf|txt|csv|json|md)', content)
                    or re.search(r'\|\s*\d+\s*\|.*\.(pdf|txt|csv|json|md)', content)
                )
                _max_len = 800 if (_has_list or _user_refs_number) else 350
                if len(content) > _max_len:
                    content = content[:_max_len] + "..."
        elif role == "user" and len(content) > 400:
            content = content[:400] + "..."

        _context_parts.append(f"{'사용자' if role == 'user' else 'AI'}: {content}")

    if _dedup_count:
        logger.info(f"[멀티턴] 유사 답변 중복 {_dedup_count}건 제거 완료")

    if _context_parts:
        _prev_context = "\n".join(_context_parts)
        if _is_conv:
            _header = (
                "[직전 대화 맥락 - 대화 연속성 참고용]\n"
                "아래는 직전 대화예요. 현재 질문이 직전 대화와 자연스럽게 이어지는 경우(예: '그럼', '그래서', '또', '다른') 맥락을 이어서 답변하세요.\n"
                "중요: 이 맥락은 참고용이며, 파일/학습/자료/문서/데이터 관련 질문에는 반드시 search_farm_knowledge 도구를 사용하세요.\n"
                "이전 대화에서 비슷한 답변이 있더라도, 도구를 다시 호출하여 최신 정보를 검색하세요.\n"
                "이전 답변을 그대로 복사하거나 반복하는 것은 금지합니다.\n"
            )
        else:
            _header = (
                "[직전 대화 흐름 - 사용자 질문 맥락 파악용]\n"
                "아래는 사용자의 이전 질문 흐름이에요. 현재 요청의 맥락(예: '그럼', '그것도')을 파악하는 데만 참고하세요.\n"
                "중요: 반드시 도구를 호출하여 최신 데이터로 응답하세요. 이전 답변 내용은 포함되지 않으므로 절대 추측하거나 복사하지 마세요.\n"
            )
        messages.append({"role": "system", "content": _header + _prev_context})

    logger.info(
        f"[멀티턴] 하이브리드 컨텍스트: 관련대화={len(system_context)}건, "
        f"최근턴={len(filtered_turns)}턴 (인사/잡담 {skipped}턴 제외, messages={len(messages)}개)"
    )


def get_llm_response_with_tools(
    user_query: str,
    farm_name: str = None,
    temperature: float = 0.5,
    max_tool_iterations: int = 8,
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    speech_style: str = None,
    progress_queue: Optional[ThreadQueue] = None,

# (get_llm_response_with_tools 파라미터 블록 계속)
) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_definition import get_available_tools, get_system_prompt_with_tools
        from agri_ai_core.src.ai.tools_executor import execute_tool

        model_name = _get_model_name()
        tools = get_available_tools()

        # 농장명이 있으면 농장 시스템 프롬프트, 없으면 일반 프롬프트
        if farm_name:
            farm_info = _build_farm_info_text()
            system_prompt = get_system_prompt_with_tools(farm_name, farm_info, speech_style=speech_style or "male")
        else:
            system_prompt = (
                "당신은 다양한 분야의 지식을 갖춘 AI 어시스턴트입니다.\n\n"
                "**말투 (절대 규칙):**\n"
                "- 모든 문장을 반드시 존댓말 어미(~합니다/~입니다/~해요/~세요/~습니다)로 끝내세요.\n"
                "- 설명·나열·요약도 존댓말 문장으로 마무리하세요.\n"
                "- 반말 어미(~한다/~된다/~이다/~했다) 사용 절대 금지합니다.\n"
                "- 불릿/번호 항목도 문장으로 끝날 때는 존댓말로 마무리하세요.\n"
                "- 친절하고 따뜻하게 응대합니다.\n\n"
                "**대화 원칙:**\n"
                "- 질문에는 구체적이고 실용적인 정보를 포함하여 충분히 답변합니다.\n"
                "- 정보가 부족하면 솔직하게 안내하되, 관련된 유용한 내용을 추가로 제공합니다.\n"
                "- 사용자의 의도를 파악하여 맥락에 맞는 풍부한 답변을 제공합니다.\n\n"
                "**출력 형식:**\n"
                "- 내부 추론/독백/분석 과정을 절대 출력하지 않습니다.\n"
                "- <think> 태그 사용 절대 금지합니다. 순수 답변 본문만 출력합니다.\n"
                "/no_think"
            )

        _emit_question_log_once(
            user_query=user_query,
            farm_name=farm_name,
            max_tool_iterations=max_tool_iterations,
            tools_count=len(tools or []),
        )

        # 메시지 히스토리
        messages = [{"role": "system", "content": system_prompt}]

        # 하이브리드 대화 컨텍스트 주입
        if conversation_history:
            _build_conversation_context(messages, conversation_history, user_query)

        messages.append({"role": "user", "content": user_query})

        # 웹 검색 출처 URL 수집용
        _collected_sources = []
        # 사용된 도구 추적
        _tools_used: List[str] = []

        logger.info(
            f"[Tool Use] 시작 model={model_name} tools={len(tools)}개 "
            f"messages={len(messages)}개 max_iterations={max_tool_iterations}"
        )

        # [PERF:대화] 전체 Tool Use 루프 시작
        _t_tooluse_start = time.time()

        # 도구 호출 반복 (최대 max_tool_iterations회)
        _prev_had_tool_calls = True  # 첫 반복은 항상 도구 제공
        _empty_response_count = 0  # 빈 응답 연속 횟수
        _retry_state = {}  # 방어 로직 중복 방지 플래그 (각 유형별 1회만 발동)
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] --- 반복 {iteration + 1}/{max_tool_iterations} ---")

            # 진행 상태 보고: LLM 호출 시작
            if iteration == 0:
                _report_progress(progress_queue,
                                 f"질문을 분석하고 필요한 도구/데이터를 파악하고 있습니다... (1/{max_tool_iterations}단계)",
                                 "llm_analyzing",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)
            elif iteration == max_tool_iterations - 1:
                _report_progress(progress_queue,
                                 f"수집된 정보를 종합하여 최종 답변을 작성하고 있습니다... ({iteration + 1}/{max_tool_iterations}단계)",
                                 "llm_generating",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)
            else:
                _report_progress(progress_queue,
                                 f"추가 데이터를 조회하고 답변을 구성하고 있습니다... ({iteration + 1}/{max_tool_iterations}단계)",
                                 "llm_generating",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)

            # LLM 호출
            # 이전 반복에서 도구 호출이 있었으면 → 다음에도 도구 제공 (다단계 호출 지원)
            # 이전 반복에서 도구 호출이 없었으면 → 도구 제거 (최종 답변 생성)
            # GPU 탑재 비율 기반 컨텍스트 옵션 (모델·VRAM 변경 시 자동 적용)
            _ctx_opts = _get_model_ctx_options(model_name, NUM_PREDICT)
            if _prev_had_tool_calls:
                # 도구 호출 모드: 첫 반복은 도구 JSON만 생성하면 되므로 출력 제한
                # → 도구 호출 속도 향상 + LLM이 도구 대신 장문 답변 생성하는 환각 방지
                iter_num_predict = NUM_PREDICT_TOOL_CALL if iteration == 0 else _ctx_opts["num_predict"]
                iter_tools = tools
            else:
                iter_num_predict = _ctx_opts["num_predict"]
                iter_tools = None
            t_iter = time.time()
            response = _ollama_chat(
                model=model_name,
                messages=messages,
                tools=iter_tools,
                options={
                    "temperature": temperature,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_predict": iter_num_predict,
                    "num_ctx": _ctx_opts["num_ctx"],
                    "think": False,   # 항상 적용: 모든 모델 thinking 비활성화
                },
                keep_alive='1h'
            )

            # 응답에서 메시지 추출
            if hasattr(response, 'message'):
                assistant_message_raw = response.message
            elif isinstance(response, dict) and 'message' in response:
                assistant_message_raw = response['message']
            else:
                logger.error("LLM 응답 형식 오류")
                return _build_structured_result("죄송합니다. 응답을 생성할 수 없습니다.", [], [])

            assistant_message = _normalize_assistant_message(assistant_message_raw)

            # done_reason 추출 (length면 토큰 한도 도달, stop이면 정상 종료)
            _done_reason = None
            if hasattr(response, 'done_reason'):
                _done_reason = response.done_reason
            elif isinstance(response, dict):
                _done_reason = response.get('done_reason')

            # 메시지 히스토리에 추가
            messages.append(assistant_message)

            # 도구 호출 추출 및 상태 추적
            tool_calls = _extract_tool_calls(assistant_message)
            iter_elapsed = time.time() - t_iter
            _prev_had_tool_calls = bool(tool_calls)

            if not tool_calls:
                final_answer = assistant_message.get("content", "")
                _tooluse_total_s = time.time() - _t_tooluse_start
                logger.info(
                    f"[Tool Use] 도구호출 없음 → 최종답변 반환 (반복{iteration + 1}, {iter_elapsed:.1f}s) "
                    f"답변길이={len(final_answer)}자 done_reason={_done_reason}"
                )
                logger.debug(
                    f"[PERF:대화] ToolUse루프-LLM호출={iter_elapsed:.1f}s, "
                    f"ToolUse루프-전체={_tooluse_total_s:.1f}s (반복{iteration + 1})"
                )

                # 방어 로직: LLM 답변 검증 및 필요시 강제 재시도
                _retry = _check_answer_retry(
                    final_answer=final_answer, user_query=user_query,
                    tools_used=_tools_used, iteration=iteration,
                    max_iterations=max_tool_iterations, done_reason=_done_reason,
                    had_tools=iter_tools is not None, retry_state=_retry_state,
                )
                if _retry:
                    messages.pop()
                    messages.append({"role": "user", "content": _retry})
                    _prev_had_tool_calls = True
                    continue

                # 빈 응답 감지 (qwen3 thinking 모드에서 content="" 반환하는 경우)
                if not final_answer.strip():
                    _empty_response_count += 1
                    if _empty_response_count <= 1 and iteration < max_tool_iterations - 1:
                        logger.warning(
                            f"[Tool Use] 빈 응답 감지 (반복{iteration + 1}) → 도구 호출 재시도 "
                            f"(빈응답횟수={_empty_response_count})"
                        )
                        # 빈 응답 메시지 제거 후 도구 호출 유도 (원본 질문 포함)
                        messages.pop()  # 빈 assistant 메시지 제거
                        messages.append({
                            "role": "user",
                            "content": (
                                f"사용자의 원래 요청: \"{user_query}\"\n"
                                f"도구를 호출하여 위 요청을 처리하세요. "
                                f"반드시 적절한 도구를 선택하고 호출해야 합니다."
                            ),
                        })
                        _prev_had_tool_calls = True
                        continue
                    elif _empty_response_count > 1:
                        logger.warning(
                            f"[Tool Use] 빈 응답 {_empty_response_count}회 연속 → 루프 종료"
                        )
                        final_answer = "죄송합니다. 요청을 처리하지 못했습니다. 다시 시도해 주세요."
                        return _build_structured_result(final_answer, _collected_sources, _tools_used)
                else:
                    _empty_response_count = 0  # 유효한 응답이면 카운터 리셋

                _report_progress(progress_queue, "답변을 정리하고 있습니다...", "finalizing")
                _t_final = time.time()
                finalized = _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=final_answer,
                )
                _final_s = time.time() - _t_final
                logger.debug(f"[PERF:대화] 후처리(_finalize)={_final_s:.1f}s")

                _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                return _build_structured_result(finalized, _collected_sources, _tools_used)

            # 도구 호출 실행 + 결과 병합
            _execute_and_merge_tools(
                tool_calls=tool_calls, messages=messages,
                default_tool_args=default_tool_args, user_query=user_query,
                tools_used=_tools_used, collected_sources=_collected_sources,
                execute_tool=execute_tool, iteration=iteration,
                max_tool_iterations=max_tool_iterations,
                progress_queue=progress_queue,
            )

        # 최대 반복 횟수 도달
        logger.warning(f"[Tool Use] 최대 반복 횟수({max_tool_iterations}) 도달")

        # 마지막 메시지가 assistant 메시지면 그것을 반환
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                finalized = _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=msg.get("content", "죄송합니다. 응답을 완료할 수 없습니다."),
                )
                _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                return _build_structured_result(finalized, _collected_sources, _tools_used)
            elif hasattr(msg, 'content') and hasattr(msg, 'role'):
                if msg.role == "assistant":
                    finalized = _finalize_user_facing_answer(
                        model_name=model_name,
                        user_query=user_query,
                        farm_name=farm_name,
                        raw_answer=msg.content,
                    )
                    _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                    finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                    return _build_structured_result(finalized, _collected_sources, _tools_used)

        return _build_structured_result("죄송합니다. 응답을 생성할 수 없습니다.", [], [])

    except Exception as e:
        if _is_connection_related_error(e):
            logger.warning(f"Tool Use LLM 응답 생성 실패(연결/환경): {e}")
            return _build_structured_result(
                "죄송합니다. 현재 LLM 서버 연결이 불안정합니다. 잠시 후 다시 시도해 주세요.", [], [])
        else:
            logger.error(f"Tool Use LLM 응답 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
        return _build_structured_result(f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}", [], [])
