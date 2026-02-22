# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 클라이언트 핵심 모듈
# Ollama LLM API와 통신하며, Tool Use(Function Calling)를 통한 응답 생성을 담당합니다.
# --->
# _get_available_models: Ollama에서 사용 가능한 모델 목록 가져오기
# _get_model_name: 환경 설정에서 모델명을 가져오거나 기본값을 반환
# _perform_llm_warmup: LLM 워밍업 수행
# initialize_background_warmup: 백그라운드 워밍업 초기화
# get_llm_response_with_tools: Tool Use 지원 LLM 응답 생성 (LLM이 도구 자율 선택)
# filter_llm_response: LLM 응답 필터링
# clean_llm_response: LLM 응답 정리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import time
import json
import hashlib
import threading
import traceback
from typing import Any, Dict, List, Optional, Set
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import ollama
except Exception:
    ollama = None

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import settings
from agri_ai_core.config import NUM_PREDICT

logger = setup_logger(__name__)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 워밍업 관련 전역 변수
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_warmup_lock = threading.Lock()
_warmup_started = False
_llm_warmed = False

# 모델 캐싱
_cached_model_name = None
_model_cache_lock = threading.Lock()
_direct_ollama_disabled_reason: Optional[str] = None

# 환경 변수 설정
os.environ['OLLAMA_MAX_LOADED_MODELS'] = '1'
os.environ['OLLAMA_NUM_PARALLEL'] = '2'
os.environ['OLLAMA_KEEP_ALIVE'] = '1h'


def _get_ollama_url() -> str:
    return (
        getattr(settings.model, "ollama_url", None)
        or os.getenv("OLLAMA_URL")
        or "http://localhost:11434"
    )


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _use_mcp_fetch() -> bool:
    # MCP fetch는 환경 의존성이 커서 기본값은 비활성화한다.
    return _is_true(os.getenv("USE_MCP_FETCH", "false"))


def _use_ollama_package() -> bool:
    return ollama is not None and _is_true(os.getenv("USE_OLLAMA_PACKAGE", "true"))


def _use_direct_ollama_http() -> bool:
    return _is_true(os.getenv("USE_DIRECT_OLLAMA_HTTP", "true"))


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


def _pkg_ollama_list_models() -> List[str]:
    if not _use_ollama_package():
        return []

    result = ollama.list()
    names: List[str] = []

    if hasattr(result, "models"):
        for model in getattr(result, "models", []) or []:
            name = getattr(model, "model", None) or getattr(model, "name", None)
            if isinstance(name, str) and name.strip():
                names.append(name)
        return names

    if isinstance(result, dict):
        for model in result.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            name = model.get("model") or model.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name)
    return names


def _pkg_ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
) -> Any:
    if not _use_ollama_package():
        raise RuntimeError("ollama package unavailable")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    if keep_alive:
        payload["keep_alive"] = keep_alive

    return ollama.chat(**payload)




def _build_ollama_url(path: str) -> str:
    base = _get_ollama_url().rstrip("/")
    if path.startswith("/"):
        return f"{base}{path}"
    return f"{base}/{path}"


def _direct_ollama_json(
    path: str,
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 120,
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
    models = data.get("models", [])
    names: List[str] = []
    if isinstance(models, list):
        for model in models:
            if isinstance(model, dict):
                name = model.get("name") or model.get("model")
                if isinstance(name, str) and name.strip():
                    names.append(name)
    return names


def _direct_ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    if keep_alive:
        payload["keep_alive"] = keep_alive

    return _direct_ollama_json(path="/api/chat", method="POST", json_body=payload, timeout=timeout)




def _mcp_ollama_list_models(timeout: int = 20) -> List[str]:
    from agri_ai_core.src.ai.mcp_client import mcp_fetch_json

    result = mcp_fetch_json(url=f"{_get_ollama_url()}/api/tags", method="GET", timeout=timeout)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "MCP tags call failed")

    data = result.get("data")
    if not isinstance(data, dict):
        return []

    models = data.get("models", [])
    names: List[str] = []
    if isinstance(models, list):
        for model in models:
            if isinstance(model, dict):
                name = model.get("name") or model.get("model")
                if isinstance(name, str) and name.strip():
                    names.append(name)
    return names


def _mcp_ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    from agri_ai_core.src.ai.mcp_client import mcp_fetch_json

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    if keep_alive:
        payload["keep_alive"] = keep_alive

    result = mcp_fetch_json(
        url=f"{_get_ollama_url()}/api/chat",
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
        payload = {
            "model": model,
            "messages": _serialize_for_log(messages),
            "stream": False,
        }
        if options:
            payload["options"] = _serialize_for_log(options)
        if tools:
            payload["tools"] = _serialize_for_log(tools)
        if keep_alive:
            payload["keep_alive"] = keep_alive
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
    except Exception as log_err:
        logger.warning(f"[LLM 응답 JSON 로깅 실패] {log_err}")


def _ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
):
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

    if _use_ollama_package():
        try:
            result = _pkg_ollama_chat(
                model=model,
                messages=messages,
                options=options,
                tools=tools,
                keep_alive=keep_alive,
            )
            elapsed = time.time() - t_start
            _log_llm_response_json(result, "package", elapsed)
            resp_content = _extract_message_content(result)
            resp_tool_calls = _extract_tool_calls(
                _normalize_assistant_message(
                    result.message if hasattr(result, 'message') else (result.get('message', {}) if isinstance(result, dict) else {})
                )
            )
            logger.info(
                f"[Ollama응답] transport=package ({elapsed:.1f}s) "
                f"답변길이={len(resp_content)}자 tool_calls={len(resp_tool_calls)}개"
            )
            return result
        except Exception as pkg_err:
            logger.warning(f"Ollama chat 호출 실패(package) -> MCP/direct fallback: {pkg_err}")
            errors.append(str(pkg_err))

    if _use_mcp_fetch():
        try:
            result = _mcp_ollama_chat(
                model=model,
                messages=messages,
                options=options,
                tools=tools,
                keep_alive=keep_alive,
            )
            elapsed = time.time() - t_start
            _log_llm_response_json(result, "MCP", elapsed)
            resp_content = _extract_message_content(result)
            logger.info(
                f"[Ollama응답] transport=MCP ({elapsed:.1f}s) 답변길이={len(resp_content)}자"
            )
            return result
        except Exception as mcp_err:
            logger.warning(f"Ollama chat 호출 실패(MCP) -> direct fallback: {mcp_err}")
            errors.append(str(mcp_err))

    if _is_direct_ollama_enabled():
        try:
            result = _direct_ollama_chat(
                model=model,
                messages=messages,
                options=options,
                tools=tools,
                keep_alive=keep_alive,
            )
            elapsed = time.time() - t_start
            _log_llm_response_json(result, "direct", elapsed)
            resp_content = _extract_message_content(result)
            logger.info(
                f"[Ollama응답] transport=direct ({elapsed:.1f}s) 답변길이={len(resp_content)}자"
            )
            return result
        except Exception as direct_err:
            errors.append(str(direct_err))
            raise

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


def _extract_tool_calls(assistant_message: Dict[str, Any]) -> List[Any]:
    tool_calls = assistant_message.get("tool_calls")
    if isinstance(tool_calls, list):
        return tool_calls
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


def _normalize_tool_arguments(
    tool_name: str,
    tool_args: Dict[str, Any],
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
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
        return {"query": _pick("query")}
    if tool_name == "search_farm_knowledge":
        return {
            "query": _pick("query"),
            "n_results": _pick("n_results", 3),
        }
    if tool_name == "get_farm_realtime_data":
        return {
            "house_id": _pick("house_id"),
            "farm_id": _pick("farm_id"),
            "data_type": _pick("data_type", "all"),
        }
    return args


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Ollama에서 사용 가능한 모델 목록 가져오기
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_available_models():
    if _use_ollama_package():
        try:
            return _pkg_ollama_list_models()
        except Exception as pkg_err:
            logger.warning(f"Ollama 모델 목록 조회 실패(package) -> MCP/direct fallback: {pkg_err}")

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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 환경 설정에서 모델명을 가져오거나 기본값을 반환
# 설정된 모델이 없으면 자동으로 폴백
# 캐싱을 통해 매번 모델 목록 조회를 방지
# --->
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_model_name() -> str:
    global _cached_model_name

    # 캐시된 모델 이름이 있으면 바로 반환
    with _model_cache_lock:
        if _cached_model_name:
            return _cached_model_name

    preferred_model = getattr(settings.model, "name", None) or "qwen3:14b"
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 워밍업
# LLM 워밍업 수행
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 백그라운드 워밍업 초기화
# 백그라운드 워밍업 초기화
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def initialize_background_warmup(farm_id=None, house_id=None, farm_name=None, house_name=None):
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True

    def _warmup_runner():
        _perform_llm_warmup()

    threading.Thread(target=_warmup_runner, daemon=True).start()




# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 생각 과정 정규식 패턴 (공통)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_THINKING_PATTERNS = [
    r'^(Okay|Well|So|Now),?\s+.*?(user said|need to|should|I need|I should)',
    r'^(Okay|Well|So|Hmm),?\s+that means\b',
    r'^(Okay|Well|So|Now),?\s+(let\'s see|let me)',
    r'^Let (me|\'s)\s+(think|see|check|figure|understand)',
    r'^(First|Hmm|Wait),?\s+(I|let|the)',
    r'^I (need to|should|will|\'ll)\s+',
    r'^The user (is|provided|asked|wants|mentioned|has|said)',
    r'^Looking at (this|the|what)',
    r'^Based on (this|the|what)',
    # 데이터 검증/확인 패턴 (사용자 요청 추가)
    r'^Double-check\s+',
    r'^Checking\s+(if|the|that)',
    r'^Verify\s+(if|the|that)',
    r'^\w+\s+\d+(\.\d+)?\s*(°C|°F|%|ppm)\s+(is|are)\s+(okay|good|fine|normal|comfortable|acceptable)',
    r'^(Temperature|Humidity|CO2|Pressure|Level)\s+\d+',
    r'^Relays?:\s+',
    r'^So\s+(the|this|it)\s+(system|environment|condition)',
    r'^No\s+(immediate\s+)?action\s+(needed|required)',
]

_KOREAN_CHAR_RE = re.compile(r"[가-힣]")

_REASONING_HINT_KEYWORDS = [
    "first,",
    "second,",
    "third,",
    "hmm,",
    "wait,",
    "that means",
    "so the main points",
    "putting it all together",
    "here's the answer",
    "in a clear, concise",
    "in korean sentence",
    "relay statuses",
    "advise checking",
    "the system expects",
    "can't be converted to json",
    "json serializable",
    "maybe it's",
    "might be a problem",
]

_DEFAULT_REASONING_TERMS = [
    "first,",
    "second,",
    "third,",
    "hmm,",
    "wait,",
    "so,",
    "so the main points",
    "putting it all together",
    "in a clear, concise",
    "here's the answer",
    "let me think",
    "based on",
    "relay statuses",
    "sensor data",
]

_MEASURE_TOKEN_PATTERN = re.compile(
    r"[-+]?\d+(?:\.\d+)?\s*(?:°c|°f|%|ppm|m|lux|루멘|도|℃|℉)?",
    re.IGNORECASE,
)

_SENSOR_CONCEPT_MAP = {
    "temperature": ("temperature", "temp", "온도", "기온", "실내 온도", "외부 기온"),
    "humidity": ("humidity", "습도"),
    "co2": ("co2", "이산화탄소"),
    "light": ("light", "조도", "루멘"),
    "water_level": ("water level", "수위"),
    "water_temp": ("water temp", "수온"),
    "relay": ("relay", "릴레이"),
}


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# reasoning/독백 탐지용 용어 목록.
# 환경변수 LLM_REASONING_EXTRA_TERMS로 추가 term을 주입할 수 있다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _load_reasoning_terms() -> List[str]:
    extra_raw = os.getenv("LLM_REASONING_EXTRA_TERMS", "")
    extra_terms = [term.strip().lower() for term in extra_raw.split(",") if term and term.strip()]

    merged = []
    seen = set()
    for term in [*_DEFAULT_REASONING_TERMS, *extra_terms]:
        normalized = term.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged


_REASONING_TERMS = _load_reasoning_terms()
_reasoning_terms_logged = False


def _find_reasoning_terms(text: str) -> List[str]:
    lowered = (text or "").lower()
    return [term for term in _REASONING_TERMS if term in lowered]


def _log_reasoning_terms_once() -> None:
    # 기존 호출부 호환용 no-op (답변로그는 호출당 1회만 출력).
    global _reasoning_terms_logged
    _reasoning_terms_logged = True


def _line_has_korean(text: str) -> bool:
    return bool(_KOREAN_CHAR_RE.search(text or ""))


def _count_korean_chars(text: str) -> int:
    return len(_KOREAN_CHAR_RE.findall(text or ""))


def _looks_like_reasoning_line(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False

    lowered = stripped.lower()
    for pattern in _THINKING_PATTERNS:
        if re.match(pattern, stripped, re.IGNORECASE):
            return True

    if any(keyword in lowered for keyword in _REASONING_HINT_KEYWORDS):
        return True

    return bool(_find_reasoning_terms(stripped))


def _extract_measure_tokens(text: str) -> Set[str]:
    tokens = set()
    for token in _MEASURE_TOKEN_PATTERN.findall((text or "").lower()):
        normalized = " ".join(token.split())
        if not normalized:
            continue
        # 숫자만 있는 토큰은 정보량이 낮아 과탐 방지를 위해 제외
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
            continue
        tokens.add(normalized)
    return tokens


def _extract_sensor_concepts(text: str) -> Set[str]:
    lowered = (text or "").lower()
    concepts = set()
    for concept, aliases in _SENSOR_CONCEPT_MAP.items():
        if any(alias in lowered for alias in aliases):
            concepts.add(concept)
    return concepts


def _is_english_korean_overlap(english_paragraph: str, korean_paragraph: str) -> bool:
    eng_measures = _extract_measure_tokens(english_paragraph)
    kor_measures = _extract_measure_tokens(korean_paragraph)
    shared_measures = eng_measures & kor_measures

    eng_concepts = _extract_sensor_concepts(english_paragraph)
    kor_concepts = _extract_sensor_concepts(korean_paragraph)
    shared_concepts = eng_concepts & kor_concepts

    # 값(측정치)와 개념(온도/습도/릴레이 등)이 함께 겹치면 중복 번역 블록으로 본다.
    if len(shared_measures) >= 2 and len(shared_concepts) >= 1:
        return True
    if len(shared_concepts) >= 3:
        return True
    return False


def _snapshot_answer_stage(stage: str, text: str) -> Dict[str, Any]:
    raw = text or ""
    try:
        max_chars = max(0, int(os.getenv("LLM_VERBOSE_ANSWER_LOG_MAX_CHARS", "12000")))
    except Exception:
        max_chars = 12000

    if max_chars and len(raw) > max_chars:
        shown = raw[:max_chars] + "\n...(truncated)..."
    else:
        shown = raw

    return {
        "stage": stage,
        "length": len(raw),
        "text": shown,
    }


def _short_text_digest(text: str) -> str:
    raw = (text or "").encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()[:12]


def _emit_question_log_once(
    user_query: str,
    farm_name: Optional[str],
    max_tool_iterations: int,
    tools_count: int,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질문 상세 로그는 호출당 1회만 출력한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> None:
    if not _is_true(os.getenv("LLM_VERBOSE_QUESTION_LOG", "true")):
        return

    raw_query = user_query or ""
    logger.debug(
        f"[질문상세] tools={tools_count} max_iter={max_tool_iterations} "
        f"farm={farm_name or '-'} query_len={len(raw_query)}"
    )


def _emit_answer_log_once(
    user_query: str,
    final_mode: str,
    stages: List[Dict[str, Any]],
    dropped_details: List[str],
    detected_terms: List[str],
    rewrite_attempts: int,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 답변 필터링 상세 로그 (DEBUG 레벨). INFO 로깅은 _finalize_user_facing_answer에서 직접 수행.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> None:
    if not _is_true(os.getenv("LLM_VERBOSE_ANSWER_LOG", "true")):
        return

    raw_len = stages[0].get("length", 0) if stages else 0
    final_len = stages[-1].get("length", 0) if stages else 0

    changed_stages = []
    prev_text = None
    for s in stages:
        cur_text = s.get("text", "")
        if prev_text is not None and cur_text != prev_text:
            changed_stages.append(s["stage"])
        prev_text = cur_text

    report = {
        "final_mode": final_mode,
        "rewrite_attempts": rewrite_attempts,
        "detected_terms": detected_terms,
        "dropped_count": len(dropped_details),
        "changed_stages": changed_stages,
        "raw_len": raw_len,
        "final_len": final_len,
    }
    if dropped_details:
        report["dropped_details"] = dropped_details
    logger.debug(f"[답변필터상세] {json.dumps(report, ensure_ascii=False)}")


def _is_reasoning_paragraph(paragraph: str, korean_present_in_response: bool = False) -> bool:
    text = (paragraph or "").strip()
    if not text:
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False

    if any(_looks_like_reasoning_line(line) for line in lines):
        return True

    has_korean = _line_has_korean(text)
    ascii_alpha_count = sum(1 for c in text if c.isascii() and c.isalpha())
    non_space_count = sum(1 for c in text if not c.isspace())
    ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0
    lowered = text.lower()

    # 한글 답변에 섞인 영문 reasoning block 제거를 우선한다.
    if korean_present_in_response and not has_korean and ascii_ratio >= 0.60:
        if any(keyword in lowered for keyword in ("sensor data", "relay statuses", "main points")):
            return True
        if len(text) >= 120:
            return True

    return False


def _strip_reasoning_paragraphs(text: str, dropped_details_out: Optional[List[str]] = None) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if not paragraphs:
        return raw

    korean_present = _line_has_korean(raw)
    kept: List[str] = []
    dropped_details: List[str] = []

    # 한글 단락이 존재하면, 그 이전의 영문 단락은 모두 제거한다.
    first_korean_idx = None
    for idx, paragraph in enumerate(paragraphs):
        if _line_has_korean(paragraph):
            first_korean_idx = idx
            break

    korean_paragraphs = [p for p in paragraphs if _line_has_korean(p)]

    for idx, paragraph in enumerate(paragraphs):
        if first_korean_idx is not None and idx < first_korean_idx and not _line_has_korean(paragraph):
            dropped_details.append(f"idx={idx} reason=pre_korean_english text={paragraph[:120]}")
            continue

        if korean_paragraphs and not _line_has_korean(paragraph):
            if any(_is_english_korean_overlap(paragraph, korean_paragraph) for korean_paragraph in korean_paragraphs):
                dropped_details.append(f"idx={idx} reason=english_korean_overlap text={paragraph[:120]}")
                continue

        # 응답 첫머리의 reasoning은 우선 제거한다.
        is_leading_reasoning = (idx == 0 and _is_reasoning_paragraph(paragraph, korean_present))
        is_mixed_reasoning = _is_reasoning_paragraph(paragraph, korean_present)

        if is_leading_reasoning or is_mixed_reasoning:
            matched_terms = ",".join(_find_reasoning_terms(paragraph)[:6]) or "pattern_match"
            dropped_details.append(
                f"idx={idx} reason=reasoning_block terms={matched_terms} text={paragraph[:120]}"
            )
            continue
        kept.append(paragraph)

    if dropped_details_out is not None and dropped_details:
        dropped_details_out.extend(dropped_details)

    if kept:
        if dropped_details and dropped_details_out is None:
            logger.debug(f"[필터] reasoning/중복 단락 {len(dropped_details)}개 제거")
            for detail in dropped_details:
                logger.debug(f"[필터] {detail}")
        return "\n\n".join(kept).strip()

    return raw


def _strip_non_korean_reasoning_for_korean_query(
    text: str,
    user_query: str,
    dropped_details_out: Optional[List[str]] = None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 한국어 질문에서는 최종 답변에서 영어 reasoning/메타 라인을 강제로 제거한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    if not _line_has_korean(user_query or ""):
        return raw

    lines = raw.splitlines()
    if not any(_line_has_korean(line) for line in lines):
        return raw

    first_korean_idx: Optional[int] = None
    for idx, line in enumerate(lines):
        if _count_korean_chars(line) >= 3:
            first_korean_idx = idx
            break

    kept: List[str] = []
    dropped_details: List[str] = []

    for idx, line in enumerate(lines):
        stripped = (line or "").strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue

        if first_korean_idx is not None and idx < first_korean_idx and not _line_has_korean(stripped):
            dropped_details.append(f"idx={idx} reason=korean_guard_pre_english text={stripped[:120]}")
            continue

        korean_count = _count_korean_chars(stripped)
        ascii_alpha_count = sum(1 for c in stripped if c.isascii() and c.isalpha())
        non_space_count = sum(1 for c in stripped if not c.isspace())
        ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0

        if korean_count == 0 and ascii_alpha_count >= 3:
            dropped_details.append(f"idx={idx} reason=korean_guard_english_only text={stripped[:120]}")
            continue

        # 영어 접두부 뒤에 한국어가 이어지는 혼합 라인은 한국어 시작 지점부터 보존
        first_korean_pos = None
        for char_pos, ch in enumerate(stripped):
            if _KOREAN_CHAR_RE.match(ch):
                first_korean_pos = char_pos
                break

        # 첫 한글 앞이 마크다운 서식(*, -, #, 숫자, ., 공백 등)으로만 구성되면 자르지 않음
        _prefix_is_markdown = False
        if first_korean_pos is not None and first_korean_pos > 0:
            prefix_before_korean = stripped[:first_korean_pos]
            _prefix_is_markdown = bool(re.fullmatch(r'[\s\*\-\#\d\.\)\(>\|\[\]]+', prefix_before_korean))

        if first_korean_pos is not None and first_korean_pos > 0 and ascii_ratio >= 0.35 and not _prefix_is_markdown:
            original = stripped
            stripped = stripped[first_korean_pos:].strip()
            if line.lstrip().startswith(("-", "*")) and not stripped.startswith(("-", "*")):
                stripped = f"- {stripped}"
            dropped_details.append(
                f"idx={idx} reason=korean_guard_trim_prefix text={original[:120]}"
            )
            korean_count = _count_korean_chars(stripped)
            ascii_alpha_count = sum(1 for c in stripped if c.isascii() and c.isalpha())
            non_space_count = sum(1 for c in stripped if not c.isspace())
            ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0

        lowered = stripped.lower()
        if ascii_ratio >= 0.60 and korean_count <= 3:
            dropped_details.append(f"idx={idx} reason=korean_guard_mixed_english_dominant text={stripped[:120]}")
            continue

        if any(
            lowered.startswith(prefix)
            for prefix in ("but the main instruction", "recommendation:", "so the core info", "today (")
        ):
            dropped_details.append(f"idx={idx} reason=korean_guard_meta_prefix text={stripped[:120]}")
            continue

        if ascii_ratio >= 0.35 and any(
            keyword in lowered
            for keyword in (
                "instruction says",
                "so even if",
                "the question is",
                "provide a practical tip",
                "the main points are",
                "i'll use",
                "let's see",
            )
        ):
            dropped_details.append(f"idx={idx} reason=korean_guard_meta_english text={stripped[:120]}")
            continue

        kept.append(stripped)

    result = "\n".join(kept).strip()
    if dropped_details_out is not None and dropped_details:
        dropped_details_out.extend(dropped_details)

    if result and _line_has_korean(result):
        return result
    return raw


def _force_korean_surface_for_korean_query(
    text: str,
    user_query: str,
    dropped_details_out: Optional[List[str]] = None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 한국어 질문의 최종 응답에서 혼합 영문 꼬리/번역 괄호를 제거해
# 사용자 노출 텍스트를 한국어 중심으로 강제 정리한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    if not _line_has_korean(user_query or ""):
        return raw
    if not _line_has_korean(raw):
        return raw

    lines = raw.splitlines()
    kept: List[str] = []
    dropped_details: List[str] = []

    for idx, line in enumerate(lines):
        stripped = (line or "").strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue

        # 한국어가 전혀 없는 라인은 제거
        if not _line_has_korean(stripped):
            dropped_details.append(f"idx={idx} reason=surface_guard_non_korean text={stripped[:120]}")
            continue

        normalized = stripped
        has_url = ("http://" in normalized) or ("https://" in normalized)

        # URL이 없는 경우, 영문 번역 괄호를 제거한다.
        # 단, 한글이 포함된 짧은 출처명은 보존 (예: MBC뉴스, KBS, SBS뉴스)
        if not has_url:
            before_paren = normalized

            def _should_remove_paren(m):
                inner = m.group(0)[1:-1]  # 괄호 안 내용
                korean_count = sum(1 for c in inner if '\uac00' <= c <= '\ud7a3')
                if korean_count > 0 and len(inner) <= 15:
                    return m.group(0)  # 한글 포함 짧은 괄호 → 보존
                return ""  # 영문만 또는 긴 괄호 → 삭제

            normalized = re.sub(
                r"\((?=[^)]*[A-Za-z])[^)]*\)",
                _should_remove_paren,
                normalized,
            ).strip()
            if normalized != before_paren:
                dropped_details.append(
                    f"idx={idx} reason=surface_guard_drop_english_parentheses text={before_paren[:120]}"
                )

        # 마지막 한글 뒤에 긴 영문 꼬리가 붙은 경우 절단
        if not has_url:
            korean_positions = [m.start() for m in _KOREAN_CHAR_RE.finditer(normalized)]
            if korean_positions:
                last_korean_pos = korean_positions[-1]
                tail = normalized[last_korean_pos + 1:]
                tail_ascii_alpha = sum(1 for c in tail if c.isascii() and c.isalpha())
                if tail_ascii_alpha >= 10 and len(tail.strip()) >= 12:
                    before_tail_trim = normalized
                    normalized = normalized[:last_korean_pos + 1].rstrip()
                    normalized = re.sub(r"[\"'`\)\]\}]+$", "", normalized).strip()
                    dropped_details.append(
                        f"idx={idx} reason=surface_guard_trim_english_tail text={before_tail_trim[:120]}"
                    )

        # 여전히 영어 비중이 과도하고 메타/설명형 라인이면 제거
        korean_count = _count_korean_chars(normalized)
        ascii_alpha_count = sum(1 for c in normalized if c.isascii() and c.isalpha())
        non_space_count = sum(1 for c in normalized if not c.isspace())
        ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0
        lowered = normalized.lower()
        if ascii_ratio >= 0.45 and any(
            marker in lowered
            for marker in (
                "result ",
                "title says",
                "search was done",
                "most recent news",
                "the date in the title",
                "can't be used",
                "news to report",
            )
        ):
            dropped_details.append(f"idx={idx} reason=surface_guard_meta_english text={normalized[:120]}")
            continue

        if korean_count == 0:
            dropped_details.append(f"idx={idx} reason=surface_guard_empty_korean text={normalized[:120]}")
            continue

        # 영어 꼬리 절단 후 남는 짧은 고아 단편(단어 1~2개)은 제거
        plain_no_punct = re.sub(r"[^\w가-힣\s]", "", normalized).strip()
        token_count = len([tok for tok in plain_no_punct.split() if tok])
        if (
            ascii_alpha_count == 0
            and token_count <= 2
            and _count_korean_chars(normalized) <= 8
            and not normalized.startswith(("-", "*"))
            and not normalized.startswith(("핵심 정보", "추천 조치", "주의", "요약"))
        ):
            dropped_details.append(f"idx={idx} reason=surface_guard_orphan_fragment text={normalized[:120]}")
            continue

        normalized = re.sub(r"\s{2,}", " ", normalized).strip()
        if not normalized:
            continue
        kept.append(normalized)

    result = "\n".join(kept).strip()
    if dropped_details_out is not None and dropped_details:
        dropped_details_out.extend(dropped_details)
    if result and _line_has_korean(result):
        return result
    return raw


def _contains_reasoning_trace(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate:
        return False

    lowered = candidate.lower()
    if "<think>" in lowered or "</think>" in lowered:
        return True

    lines = [line.strip() for line in candidate.splitlines() if line.strip()]
    if any(_looks_like_reasoning_line(line) for line in lines):
        return True

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", candidate) if p.strip()]
    korean_present = _line_has_korean(candidate)
    return any(_is_reasoning_paragraph(p, korean_present) for p in paragraphs)


def _rewrite_without_reasoning(
    model_name: str,
    user_query: str,
    draft_answer: str,
    farm_name: Optional[str] = None,
) -> str:
    farm_label = farm_name or "농장"
    rewrite_system = (
        "너는 답변 정리기다. 내부 추론/분석/독백을 절대 출력하지 마라. "
        "최종 사용자 응답만 한국어로 작성하라."
    )
    rewrite_user = (
        f"[질문]\n{user_query}\n\n"
        f"[농장]\n{farm_label}\n\n"
        "[규칙]\n"
        "1) 내부 생각(예: First, Hmm, Wait, So the main points...) 금지\n"
        "2) 오류 원인 분석 독백 금지\n"
        "3) 핵심 상태와 조치만 간결하게 제시\n\n"
        f"[후보 답변]\n{draft_answer}"
    )

    response = _ollama_chat(
        model=model_name,
        messages=[
            {"role": "system", "content": rewrite_system},
            {"role": "user", "content": rewrite_user},
        ],
        options={
            "temperature": 0.0,
            "top_p": 0.1,
            "top_k": 1,
            "num_predict": NUM_PREDICT,
        },
        keep_alive="1h",
    )
    return _extract_message_content(response) or ""


def _finalize_user_facing_answer(
    model_name: str,
    user_query: str,
    farm_name: Optional[str],
    raw_answer: str,
) -> str:
    _log_reasoning_terms_once()
    stage_snapshots: List[Dict[str, Any]] = []
    dropped_details: List[str] = []
    rewrite_attempts = 0

    # ── 필터링 전 원본 ──
    logger.info(f"[필터링전-원본] len={len(raw_answer or '')}자")
    logger.info(f"[필터링전-원본내용]\n{raw_answer}")

    stage_snapshots.append(_snapshot_answer_stage("raw", raw_answer))

    filtered = filter_llm_response(raw_answer, filter_type="general")
    stage_snapshots.append(_snapshot_answer_stage("after_filter", filtered))
    if filtered != raw_answer:
        logger.info(f"[필터단계:filter] {len(raw_answer)}자→{len(filtered)}자")
        logger.info(f"[필터단계:filter내용]\n{filtered}")

    cleaned = clean_llm_response(filtered)
    stage_snapshots.append(_snapshot_answer_stage("after_clean", cleaned))
    if cleaned != filtered:
        logger.info(f"[필터단계:clean] {len(filtered)}자→{len(cleaned)}자")
        logger.info(f"[필터단계:clean내용]\n{cleaned}")

    candidate = _strip_reasoning_paragraphs(cleaned, dropped_details_out=dropped_details)
    stage_snapshots.append(_snapshot_answer_stage("after_overlap_term_strip", candidate))

    candidate = _strip_non_korean_reasoning_for_korean_query(
        candidate,
        user_query=user_query,
        dropped_details_out=dropped_details,
    )
    stage_snapshots.append(_snapshot_answer_stage("after_korean_guard", candidate))
    candidate = _force_korean_surface_for_korean_query(
        candidate,
        user_query=user_query,
        dropped_details_out=dropped_details,
    )
    stage_snapshots.append(_snapshot_answer_stage("after_korean_surface_guard", candidate))

    # ── 최종 결과 로깅 ──
    if dropped_details:
        logger.info(f"[필터링-삭제항목] {len(dropped_details)}건: {dropped_details}")

    if not _contains_reasoning_trace(candidate):
        candidate = _sanitize_markdown_links(candidate)
        diff = len(raw_answer) - len(candidate)
        logger.info(f"[필터링완료] {len(raw_answer)}자→{len(candidate)}자 ({diff}자 삭제)")
        logger.info(f"[최종답변내용]\n{candidate}")
        stage_snapshots.append(_snapshot_answer_stage("final", candidate))
        return candidate

    detected_terms = _find_reasoning_terms(candidate)
    logger.info(f"[필터링-reasoning잔존] reasoning흔적 감지 terms={detected_terms} → 재작성 시도")

    rewritten = candidate
    for attempt in range(2):
        rewrite_attempts = attempt + 1
        logger.info(f"[필터링-재작성] 시도 {attempt + 1}/2 입력길이={len(rewritten)}자")
        try:
            rewritten = _rewrite_without_reasoning(
                model_name=model_name,
                user_query=user_query,
                farm_name=farm_name,
                draft_answer=rewritten,
            )
        except Exception as rewrite_err:
            logger.warning(f"[필터] reasoning 제거 재작성 실패({attempt + 1}/2): {rewrite_err}")
            break

        stage_snapshots.append(_snapshot_answer_stage(f"rewrite_raw_{attempt + 1}", rewritten))

        before_rewrite_clean = rewritten
        rewritten = clean_llm_response(filter_llm_response(rewritten, filter_type="general"))
        rewritten = _strip_reasoning_paragraphs(rewritten, dropped_details_out=dropped_details)
        rewritten = _strip_non_korean_reasoning_for_korean_query(
            rewritten,
            user_query=user_query,
            dropped_details_out=dropped_details,
        )
        rewritten = _force_korean_surface_for_korean_query(
            rewritten,
            user_query=user_query,
            dropped_details_out=dropped_details,
        )
        stage_snapshots.append(_snapshot_answer_stage(f"rewrite_clean_{attempt + 1}", rewritten))

        if not _contains_reasoning_trace(rewritten):
            rewritten = _sanitize_markdown_links(rewritten)
            diff = len(raw_answer) - len(rewritten)
            logger.info(f"[필터링완료] {len(raw_answer)}자→{len(rewritten)}자 ({diff}자 삭제, 재작성{attempt + 1}회)")
            logger.info(f"[최종답변내용]\n{rewritten}")
            stage_snapshots.append(_snapshot_answer_stage("final", rewritten))
            return rewritten

    fallback = rewritten or candidate
    fallback = _strip_non_korean_reasoning_for_korean_query(
        fallback,
        user_query=user_query,
        dropped_details_out=dropped_details,
    )
    fallback = _force_korean_surface_for_korean_query(
        fallback,
        user_query=user_query,
        dropped_details_out=dropped_details,
    )
    fallback = _sanitize_markdown_links(fallback)
    diff = len(raw_answer) - len(fallback)
    logger.info(f"[필터링완료] {len(raw_answer)}자→{len(fallback)}자 ({diff}자 삭제, fallback)")
    logger.info(f"[최종답변내용]\n{fallback}")
    stage_snapshots.append(_snapshot_answer_stage("final", fallback))
    return fallback



# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 응답 필터링
# LLM 응답 필터링
#
# Args:
#     text: 응답 텍스트
#     filter_type: 필터 유형 ("general" 또는 "relay_control")
#     query_type: 질의 유형
#
# Returns:
#     str: 필터링된 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def filter_llm_response(text, filter_type="general", query_type=None):
    if not text or len(text.strip()) == 0:
        return text

    original_length = len(text)
    filtered_text = text

    # 1. Think 태그 제거 (공통)
    try:
        filtered_text = re.sub(r"<think>.*?</think>\s*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<thinking>.*?</thinking>\s*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<think>.*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
        filtered_text = re.sub(r"<thinking>.*", "", filtered_text, flags=re.DOTALL | re.IGNORECASE)
    except Exception as e:
        logger.warning(f"think 태그 제거 중 오류: {e}")

    # 2. 일반 필터링 (기본 타입에만 적용)
    if filter_type == "general":
        # 생각 과정 라인 제거 (공통 패턴 사용)
        lines = filtered_text.split('\n')
        cleaned_lines = []
        removed_count = 0

        for line in lines:
            line_stripped = line.strip()
            has_korean = _line_has_korean(line)

            # 한글이 포함되어 있으면 생각 과정이 아님
            if has_korean:
                cleaned_lines.append(line)
                continue

            # 생각 과정 패턴 체크 (정규식 사용)
            is_thinking = False
            for pattern in _THINKING_PATTERNS:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_thinking = True
                    removed_count += 1
                    if removed_count <= 3:  # 처음 3개만 로깅
                        logger.debug(f"[필터] 생각 과정 제거: {line_stripped[:80]}...")
                    break

            if not is_thinking:
                cleaned_lines.append(line)

        if removed_count > 0:
            logger.debug(f"[필터] 생각 과정 라인 {removed_count}개 제거")

        filtered_text = '\n'.join(cleaned_lines)

        # 마크다운 헤더 제거
        markdown_headers_to_remove = [
            r"^(### )?Final Answer:?\s*",
            r"^(### )?Final Output:?\s*",
            r"^(### )?Response:?\s*",
            r"^(### )?Answer:?\s*",
            r"^(### )?결론:?\s*"
        ]
        for pattern in markdown_headers_to_remove:
            try:
                filtered_text = re.sub(pattern, "", filtered_text, flags=re.MULTILINE | re.IGNORECASE)
            except Exception as e:
                logger.warning(f"헤더 제거 중 오류: {e}")

        # 코드 블록 마커 제거
        try:
            filtered_text = re.sub(r"^```[a-zA-Z]*\s*$", "", filtered_text, flags=re.MULTILINE)
            filtered_text = re.sub(r"^```\s*$", "", filtered_text, flags=re.MULTILINE)
        except Exception as e:
            logger.warning(f"코드 블럭 마커 제거 중 오류: {e}")

    # 3. 기본 정리 (공통) - 빈 줄 정리: 3개 이상 연속 줄바꿈 → 1개 빈 줄로 (1개 빈 줄은 유지)
    filtered_text = re.sub(r'(\n\s*){3,}', '\n\n', filtered_text)
    filtered_text = filtered_text.strip()
    final_length = len(filtered_text)

    # 4. 일반 필터링 후 과도한 제거 검사
    if filter_type == "general" and original_length > 0:
        removal_ratio = (original_length - final_length) / original_length
        if removal_ratio > 0.9:
            logger.warning(f"필터링으로 인해 응답의 {removal_ratio*100:.1f}%가 제거됨")
            if final_length < 10:
                fallback_text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
                if len(fallback_text.strip()) > final_length:
                    filtered_text = fallback_text.strip()
        elif removal_ratio > 0.1:
            removed_chars = original_length - final_length
            logger.debug(f"[필터] 응답 필터링: {removed_chars}자 제거 ({original_length} → {final_length})")

    return filtered_text


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 응답 정리
# LLM 응답에서 불필요한 내용 제거
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_llm_response(response_text):
    if not response_text:
        return response_text

    original_text = response_text
    removed_lines = []
    has_korean_any = _line_has_korean(response_text)

    # Think 태그 제거
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)
    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    lines = response_text.split('\n')
    cleaned_lines = []

    meta_reasoning_keywords = [
        "user", "tools", "tool", "respond", "response", "answer", "final answer",
        "language", "markdown", "check if", "make sure", "keep it", "need to",
        "i need to", "i should", "let me", "let's", "reasoning", "analysis",
        "the user said", "might be asking", "direct query", "call any tools",
        "tools are for", "statement, not a question", "as the ai",
        "that means", "decimal", "json serializable", "converted to json",
    ]
    meta_reasoning_starts = [
        "check if", "make sure", "keep it", "need to", "i need to", "i should",
        "let me", "let's", "respond", "answer", "use the", "given", "since",
        "okay,", "wait,", "well,", "so,", "now,", "hmm,",
    ]

    for line in lines:
        line_stripped = line.strip()
        has_korean = _line_has_korean(line)

        # 생각 과정 패턴 체크 (공통 패턴 사용)
        is_thinking = False
        if not has_korean:
            for pattern in _THINKING_PATTERNS:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_thinking = True
                    removed_lines.append(line_stripped[:100])
                    break

        # 한글이 섞여 있어도 영문 메타 추론(독백) 문장 제거
        if not is_thinking and has_korean_any and line_stripped:
            lower_line = line_stripped.lower()
            has_meta_keyword = any(keyword in lower_line for keyword in meta_reasoning_keywords)
            starts_as_meta = any(lower_line.startswith(prefix) for prefix in meta_reasoning_starts)
            ascii_alpha_count = sum(1 for c in line_stripped if c.isascii() and c.isalpha())
            non_space_count = sum(1 for c in line_stripped if not c.isspace())
            ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0

            # 영문 비중이 높고(독백 패턴) 메타 키워드/시작 패턴에 해당하면 제거
            if has_meta_keyword and (starts_as_meta or ascii_ratio >= 0.20):
                is_thinking = True
                removed_lines.append(line_stripped[:100])

        if not is_thinking:
            cleaned_lines.append(line)

    # 제거된 라인 로깅
    if removed_lines:
        logger.debug(f"[필터] 생각 과정 라인 {len(removed_lines)}개 제거:")
        for removed in removed_lines[:5]:  # 최대 5개만 로깅
            logger.debug(f"  - {removed}...")
        if len(removed_lines) > 5:
            logger.debug(f"  ... 외 {len(removed_lines) - 5}개")

    response_text = '\n'.join(cleaned_lines)
    # 빈 줄 정리: 3개 이상 연속 줄바꿈 → 1개 빈 줄로 (1개 빈 줄은 유지)
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = re.sub(r'[ \t]{2,}(?!\n)', ' ', response_text)
    response_text = response_text.strip()

    # 추가 필터링: 마침표로 구분된 짧은 영문 검증/판단 문장 제거
    # (사용자 요청: "Double-check the numbers. Temperature 25.3°C is comfortable..." 같은 패턴)
    if has_korean_any:
        # 한글이 포함된 응답에서 영문 검증 문장만 제거
        sentence_removed_count = 0
        for line in response_text.split('\n'):
            if _line_has_korean(line):
                continue  # 한글이 있는 줄은 건너뜀

            # 마침표로 분리된 문장들 검사
            sentences = [s.strip() for s in line.split('.') if s.strip()]
            filtered_sentences = []

            for sentence in sentences:
                # 짧은 영문 검증/판단 문장인지 확인
                is_verification = False
                if len(sentence) < 200 and not _line_has_korean(sentence):
                    for pattern in _THINKING_PATTERNS:
                        if re.match(pattern, sentence.strip(), re.IGNORECASE):
                            is_verification = True
                            sentence_removed_count += 1
                            break

                if not is_verification:
                    filtered_sentences.append(sentence)

            # 문장들을 다시 조립
            if filtered_sentences:
                new_line = '. '.join(filtered_sentences)
                if new_line and not new_line.endswith('.'):
                    new_line += '.'
                response_text = response_text.replace(line, new_line)
            else:
                response_text = response_text.replace(line, '')

        if sentence_removed_count > 0:
            logger.debug(f"[필터] 검증/판단 문장 {sentence_removed_count}개 추가 제거")

    # 빈 줄 정리: 3개 이상 연속 줄바꿈 → 1개 빈 줄로 (1개 빈 줄은 유지)
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = response_text.strip()

    # 필터링 결과 요약 로깅
    if len(original_text) > len(response_text):
        removed_chars = len(original_text) - len(response_text)
        logger.debug(f"[필터] LLM 응답 정리: {removed_chars}자 제거 ({len(original_text)} → {len(response_text)})")

    return response_text



# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use 지원 LLM 응답 생성
# Ollama Function Calling을 사용하여 도구를 자동으로 선택하고 실행
#
# Args:
#     user_query: 사용자 질문
#     farm_name: 농장명
#     temperature: 창의성 정도
#     max_tool_iterations: 최대 도구 호출 반복 횟수
#
# Returns:
#     str: 최종 응답 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _sanitize_markdown_links(text: str) -> str:
    """마크다운 링크 중 유효하지 않은 URL을 가진 링크를 텍스트로 변환한다."""
    import re
    def _replace_bad_link(match):
        label = match.group(1)
        url = match.group(2).strip()
        # http:// 또는 https:// 로 시작하고, 도메인에 .이 포함된 경우만 유효
        if re.match(r'^https?://[^\s]+\.[^\s]+', url):
            return match.group(0)  # 유효한 링크는 그대로
        return label  # 유효하지 않으면 라벨 텍스트만 반환
    return re.sub(r'\[([^\]]*)\]\(([^)]*)\)', _replace_bad_link, text)


def _append_source_urls(answer: str, sources: list) -> str:
    if not sources:
        return answer
    # 답변에 이미 URL이 포함되어 있으면 추가하지 않음
    if "http://" in answer or "https://" in answer:
        return answer
    lines = [f"- [{s['title']}]({s['url']})" for s in sources]
    return answer.rstrip() + "\n\n**출처:**\n" + "\n".join(lines)


def get_llm_response_with_tools(
    user_query: str,
    farm_name: str = None,
    temperature: float = 0.7,
    max_tool_iterations: int = 8,
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use를 지원하는 LLM 응답 생성
# LLM이 필요한 도구를 자동으로 선택하고 호출하여 최종 답변 생성
# Args: user_query: 사용자 질문
#       farm_name: 농장명
#       temperature: 창의성 정도
#       max_tool_iterations: 최대 도구 호출 반복 횟수
#       default_tool_args: 도구별 기본 인자
# Returns: str: 최종 응답
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> str:
    try:
        from agri_ai_core.src.ai.tools_definition import get_available_tools, get_system_prompt_with_tools
        from agri_ai_core.src.ai.tools_executor import execute_tool

        model_name = _get_model_name()
        tools = get_available_tools()

        # 농장명이 있으면 농장 시스템 프롬프트, 없으면 일반 프롬프트
        if farm_name:
            system_prompt = get_system_prompt_with_tools(farm_name)
        else:
            system_prompt = (
                "당신은 다양한 분야의 지식을 갖춘 친근한 AI 어시스턴트입니다.\n\n"
                "**대화 원칙:**\n"
                "- 한글로 자연스럽고 친근하게 대화합니다.\n"
                "- 인사나 일상 대화에는 따뜻하고 다정하게 응대하며, 대화를 이어갈 수 있는 질문이나 화제를 제안합니다.\n"
                "- 질문에는 구체적이고 실용적인 정보를 포함하여 충분히 답변합니다.\n"
                "- 정보가 부족하면 솔직하게 말하되, 관련된 유용한 내용을 추가로 안내합니다.\n"
                "- 사용자의 의도를 파악하여 맥락에 맞는 풍부한 답변을 제공합니다.\n\n"
                "**출력 형식:**\n"
                "- 내부 추론/독백/분석 과정을 절대 출력하지 않습니다.\n"
                "- 최종 사용자에게 보여줄 순수 답변 본문만 출력합니다."
            )

        _emit_question_log_once(
            user_query=user_query,
            farm_name=farm_name,
            max_tool_iterations=max_tool_iterations,
            tools_count=len(tools or []),
        )

        # 메시지 히스토리
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": user_query})

        # 웹 검색 출처 URL 수집용
        _collected_sources = []

        logger.info(
            f"[Tool Use] 시작 model={model_name} tools={len(tools)}개 "
            f"messages={len(messages)}개 max_iterations={max_tool_iterations}"
        )

        # 도구 호출 반복 (최대 max_tool_iterations회)
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] --- 반복 {iteration + 1}/{max_tool_iterations} ---")

            # LLM 호출 (도구 포함)
            t_iter = time.time()
            response = _ollama_chat(
                model=model_name,
                messages=messages,
                tools=tools,
                options={
                    "temperature": temperature,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_predict": NUM_PREDICT
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
                return "죄송합니다. 응답을 생성할 수 없습니다."

            assistant_message = _normalize_assistant_message(assistant_message_raw)

            # 메시지 히스토리에 추가
            messages.append(assistant_message)

            # 도구 호출이 없으면 최종 답변 반환
            tool_calls = _extract_tool_calls(assistant_message)
            iter_elapsed = time.time() - t_iter
            if not tool_calls:
                final_answer = assistant_message.get("content", "")
                logger.info(
                    f"[Tool Use] 도구호출 없음 → 최종답변 반환 (반복{iteration + 1}, {iter_elapsed:.1f}s) "
                    f"답변길이={len(final_answer)}자"
                )
                finalized = _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=final_answer,
                )
                return _append_source_urls(finalized, _collected_sources)

            # 도구 호출 처리
            logger.info(f"[Tool Use] 도구호출 {len(tool_calls)}건 감지 (반복{iteration + 1})")
            for tc_idx, tool_call in enumerate(tool_calls, start=1):
                tool_name = _extract_tool_name(tool_call)
                tool_args = _extract_tool_arguments(tool_call)
                if not tool_name:
                    logger.warning(f"[Tool Use] 도구 이름 파싱 실패: {tool_call}")
                    continue

                tool_args = _normalize_tool_arguments(
                    tool_name,
                    tool_args,
                    default_tool_args=default_tool_args,
                )
                logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name}({tool_args})")

                # 도구 실행
                t_tool = time.time()
                tool_result = execute_tool(tool_name, tool_args)
                tool_elapsed = time.time() - t_tool
                result_len = len(tool_result or "")
                logger.info(f"[도구결과] [{tc_idx}/{len(tool_calls)}] {tool_name} ({tool_elapsed:.1f}s) 결과길이={result_len}자")
                logger.info(f"[도구결과데이터] {tool_name}:\n{tool_result}")

                # 도구 결과를 메시지에 추가
                messages.append({
                    "role": "tool",
                    "content": tool_result
                })

                # search_web 결과에서 출처 URL 수집
                if tool_name == "search_web" and tool_result:
                    try:
                        parsed_result = json.loads(tool_result)
                        for item in parsed_result.get("results", []):
                            title = (item.get("title") or "").strip()
                            url = (item.get("url") or "").strip()
                            if title and url:
                                _collected_sources.append({"title": title, "url": url})
                    except (json.JSONDecodeError, TypeError):
                        pass

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
                return _append_source_urls(finalized, _collected_sources)
            elif hasattr(msg, 'content') and hasattr(msg, 'role'):
                if msg.role == "assistant":
                    finalized = _finalize_user_facing_answer(
                        model_name=model_name,
                        user_query=user_query,
                        farm_name=farm_name,
                        raw_answer=msg.content,
                    )
                    return _append_source_urls(finalized, _collected_sources)

        return "죄송합니다. 응답을 생성할 수 없습니다."

    except Exception as e:
        if _is_connection_related_error(e):
            logger.warning(f"Tool Use LLM 응답 생성 실패(연결/환경): {e}")
            return "죄송합니다. 현재 LLM 서버 연결이 불안정합니다. 잠시 후 다시 시도해 주세요."
        else:
            logger.error(f"Tool Use LLM 응답 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
        return f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}"
