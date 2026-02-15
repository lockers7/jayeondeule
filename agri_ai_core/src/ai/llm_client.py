# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 클라이언트 핵심 모듈
# OpenAI, Anthropic 등 다양한 LLM API와 통신하며,
# 프롬프트 전송, 응답 수신, 스트리밍 처리 등을 담당합니다.
# --->
# _get_available_models: Ollama에서 사용 가능한 모델 목록 가져오기
# _get_model_name: 환경 설정에서 모델명을 가져오거나 기본값을 반환
# _perform_llm_warmup: LLM 워밍업 수행
# initialize_background_warmup: 백그라운드 워밍업 초기화
# get_llm_response: LLM 응답 생성 (기존)
# get_llm_response_with_tools: Tool Use 지원 LLM 응답 생성 (신규)
# get_llm_streaming_response: LLM 스트리밍 응답 생성
# clean_streaming_chunk: 스트리밍 청크 정리
# filter_llm_response: LLM 응답 필터링
# clean_llm_response: LLM 응답 정리
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import time
import json
import html
import hashlib
import threading
import traceback
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

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


def _pkg_ollama_generate_text(
    model: str,
    prompt: str,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
) -> str:
    if not _use_ollama_package():
        raise RuntimeError("ollama package unavailable")

    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if keep_alive:
        payload["keep_alive"] = keep_alive

    result = ollama.generate(**payload)
    if isinstance(result, dict):
        if isinstance(result.get("response"), str):
            return result.get("response", "")
        message = result.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message.get("content", "")

    if hasattr(result, "response"):
        response_text = getattr(result, "response", "")
        if isinstance(response_text, str):
            return response_text

    message = getattr(result, "message", None)
    if message and hasattr(message, "content"):
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content

    return ""


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


def _direct_ollama_generate_text(
    model: str,
    prompt: str,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
    timeout: int = 120,
) -> str:
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if keep_alive:
        payload["keep_alive"] = keep_alive

    data = _direct_ollama_json(path="/api/generate", method="POST", json_body=payload, timeout=timeout)
    if isinstance(data.get("response"), str):
        return data.get("response", "")
    message = data.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message.get("content", "")
    return ""


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


def _mcp_ollama_generate_text(
    model: str,
    prompt: str,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
    timeout: int = 120,
) -> str:
    from agri_ai_core.src.ai.mcp_client import mcp_fetch_json

    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if keep_alive:
        payload["keep_alive"] = keep_alive

    result = mcp_fetch_json(
        url=f"{_get_ollama_url()}/api/generate",
        method="POST",
        json_body=payload,
        timeout=timeout,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "MCP generate call failed")

    data = result.get("data")
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("response"), str):
        return data.get("response", "")
    message = data.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message.get("content", "")
    return ""


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


def _ollama_generate_text(
    model: str,
    prompt: str,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
) -> str:
    errors: List[str] = []

    if _use_ollama_package():
        try:
            return _pkg_ollama_generate_text(
                model=model,
                prompt=prompt,
                options=options,
                keep_alive=keep_alive,
            )
        except Exception as pkg_err:
            logger.warning(f"Ollama generate 호출 실패(package) -> MCP/direct fallback: {pkg_err}")
            errors.append(str(pkg_err))

    if _use_mcp_fetch():
        try:
            return _mcp_ollama_generate_text(
                model=model,
                prompt=prompt,
                options=options,
                keep_alive=keep_alive,
            )
        except Exception as mcp_err:
            logger.warning(f"Ollama generate 호출 실패(MCP) -> direct fallback: {mcp_err}")
            errors.append(str(mcp_err))

    if _is_direct_ollama_enabled():
        try:
            return _direct_ollama_generate_text(
                model=model,
                prompt=prompt,
                options=options,
                keep_alive=keep_alive,
            )
        except Exception as direct_err:
            errors.append(str(direct_err))
            raise

    error_tail = errors[-1] if errors else "all transports unavailable"
    raise RuntimeError(f"No available Ollama transport: {error_tail}")


def _ollama_generate_stream(
    model: str,
    prompt: str,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[str] = None,
) -> Iterable[Dict[str, Any]]:
    text = _ollama_generate_text(
        model=model,
        prompt=prompt,
        options=options,
        keep_alive=keep_alive,
    )
    return [{"response": text}]


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

    # 사용 가능한 모델 목록 조회
    available_models = _get_available_models()

    # 선호 모델이 있는지 확인
    if preferred_model in available_models:
        logger.debug(f"사용 중인 모델: {preferred_model}")
        with _model_cache_lock:
            _cached_model_name = preferred_model
        return preferred_model

    # 선호 모델이 없으면 폴백 모델 확인
    if fallback_model in available_models:
        logger.warning(f"선호 모델 '{preferred_model}'을 찾을 수 없어 '{fallback_model}' 사용")
        with _model_cache_lock:
            _cached_model_name = fallback_model
        return fallback_model

    # 둘 다 없으면 선호 모델 반환 (Ollama가 자동 다운로드 시도)
    logger.debug(f"모델 '{preferred_model}'을 사용합니다 (필요시 자동 다운로드)")
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
# LLM 응답 생성
# LLM 응답 생성
#
# Args:
#     system_prompt: 시스템 프롬프트
#     user_prompt: 사용자 프롬프트
#     temperature: 창의성 정도 (0=결정적, 1=창의적)
#     top_p: 누적 확률 기반 샘플링
#     top_k: 상위 K개 단어 중 선택
#     num_predict: 최대 출력 토큰 수
#     query_type: 질의 유형
#     llm_options: LLM 옵션 딕셔너리
#
# Returns:
#     str: LLM 응답 텍스트
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def get_llm_response(system_prompt=None, user_prompt=None, temperature=0.7,
                     top_p=0.9, top_k=40, num_predict=NUM_PREDICT,
                     query_type=None, llm_options=None):
    try:
        max_retries = 2
        retry_count = 0
        model_name = _get_model_name()
        t_start = time.time()
        prompt_preview = (user_prompt or "")[:80]
        logger.info(f"[LLM응답] 시작 model={model_name} query_type={query_type} prompt=\"{prompt_preview}\"")

        while retry_count <= max_retries:
            try:
                message_payload = []
                if system_prompt:
                    message_payload.append({"role": "system", "content": system_prompt})
                message_payload.append({"role": "user", "content": user_prompt})

                options_payload = llm_options or {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "num_predict": num_predict
                }

                response = _ollama_chat(
                    model=model_name,
                    messages=message_payload,
                    options=options_payload,
                    keep_alive='1h'
                )
                break
            except Exception as retry_err:
                retry_count += 1
                if retry_count > max_retries:
                    raise retry_err
                logger.error(f"LLM 응답 생성 중 오류, 재시도 {retry_count}/{max_retries}: {retry_err}")
                time.sleep(1)

        response_text = _extract_message_content(response) or "응답을 생성할 수 없습니다."
        llm_elapsed = time.time() - t_start

        if not response_text or len(response_text.strip()) == 0:
            logger.error("빈 응답 텍스트")
            response_text = "LLM이 빈 응답을 반환했습니다."

        logger.info(f"[LLM응답] 완료 ({llm_elapsed:.1f}s) 원본길이={len(response_text)}자")
        logger.info(f"[LLM응답-원본내용]\n{response_text}")

        # 응답 필터링
        if query_type == "relay_llm_control":
            filtered_response = filter_llm_response(response_text, filter_type="relay_control")
        else:
            filtered_response = filter_llm_response(response_text, filter_type="general")
        cleaned_response = clean_llm_response(filtered_response)
        cleaned_response = _strip_reasoning_paragraphs(cleaned_response)
        cleaned_response = _strip_non_korean_reasoning_for_korean_query(cleaned_response, user_prompt or "")
        logger.info(f"[LLM응답] 필터링 후 길이={len(cleaned_response)}자")
        if cleaned_response != response_text:
            logger.info(f"[LLM응답-필터후내용]\n{cleaned_response}")
        return cleaned_response

    except Exception as e:
        if _is_connection_related_error(e):
            logger.warning(f"LLM 응답 생성 실패(연결/환경): {e}")
        else:
            logger.error(f"LLM 응답 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
        return "죄송합니다. 현재 응답을 생성할 수 없습니다."


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 스트리밍 응답 생성
# LLM 스트리밍 응답 생성
#
# Args:
#     prompt: 사용자 프롬프트
#     temperature: 창의성 정도
#     top_p: 누적 확률 기반 샘플링
#     top_k: 상위 K개 단어 중 선택
#     num_predict: 최대 출력 토큰 수
#
# Yields:
#     str: 응답 청크
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
async def get_llm_streaming_response(prompt, temperature=0.7, top_p=0.9,
                                      top_k=40, num_predict=NUM_PREDICT):
    try:
        buffer = ""
        inside_think_tag = False
        model_name = _get_model_name()

        for response_chunk in _ollama_generate_stream(
            model=model_name,
            prompt=prompt,
            keep_alive='1h',  # 모델을 1시간 동안 메모리에 유지
            options={
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "num_predict": num_predict
            },
        ):
            chunk_text = response_chunk.get("response", "")
            if not chunk_text:
                continue

            buffer += chunk_text
            output_parts = []
            pos = 0

            while pos < len(buffer):
                lowered = buffer.lower()

                if inside_think_tag:
                    end_idx = lowered.find("</think>", pos)
                    if end_idx == -1:
                        buffer = buffer[pos:]
                        pos = len(buffer)
                        break

                    pos = end_idx + len("</think>")
                    inside_think_tag = False
                    continue

                start_idx = lowered.find("<think", pos)
                if start_idx == -1:
                    emit_candidate = buffer[pos:]
                    buffer = ""
                    if emit_candidate:
                        tail_candidate = emit_candidate[-6:]
                        tail_lower = tail_candidate.lower()
                        if tail_lower.startswith("<thi") or tail_lower.startswith("</thi"):
                            buffer = tail_candidate
                            emit_candidate = emit_candidate[:-len(tail_candidate)]
                    if emit_candidate:
                        output_parts.append(emit_candidate)
                    pos = len(buffer)
                    break

                output_parts.append(buffer[pos:start_idx])
                tag_close_idx = buffer.find(">", start_idx)
                if tag_close_idx == -1:
                    buffer = buffer[start_idx:]
                    pos = len(buffer)
                    inside_think_tag = True
                    break

                pos = tag_close_idx + 1
                inside_think_tag = True
                if pos >= len(buffer):
                    buffer = ""
                    break

            if output_parts:
                emit_text = ''.join(output_parts)
                filtered_chunk = clean_streaming_chunk(emit_text)
                if filtered_chunk:
                    yield filtered_chunk

        if buffer and not inside_think_tag:
            filtered_chunk = clean_streaming_chunk(buffer)
            if filtered_chunk:
                yield filtered_chunk

    except Exception as e:
        if _is_connection_related_error(e):
            logger.warning(f"LLM 스트리밍 응답 생성 실패(연결/환경): {e}")
        else:
            logger.error(f"LLM 스트리밍 응답 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
        yield "죄송합니다. 현재 응답을 생성할 수 없습니다."


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 생각 과정 패턴 감지 (공통 헬퍼 함수)
# 텍스트가 LLM의 생각 과정인지 판단
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _is_thinking_text(text):
    """
    텍스트가 LLM의 생각 과정인지 판단하는 공통 헬퍼 함수

    Args:
        text: 검사할 텍스트

    Returns:
        bool: 생각 과정이면 True
    """
    if not text or not text.strip():
        return False

    # 한글이 포함되어 있으면 생각 과정이 아님
    if _line_has_korean(text):
        return False

    text_lower = text.strip().lower()

    # 생각 과정 시작 패턴
    thinking_starts = [
        'okay,', 'well,', 'so,', 'now,',
        'let me', 'let\'s', 'first,', 'hmm,', 'wait,',
        'i need to', 'i should', 'i\'ll', 'i will'
    ]

    # 생각 과정 키워드
    thinking_keywords = [
        'user said', 'user is asking', 'user provided', 'user wants',
        'user mentioned', 'user asked', 'user needs', 'user has',
        'the user', 'need to', 'should', 'looking at', 'based on',
        'let me think', 'let\'s see', 'figure out', 'understand',
        'that means', 'decimal', 'json serializable', 'converted to json'
    ]

    # 시작 패턴 체크
    starts_with_thinking = any(text_lower.startswith(pattern) for pattern in thinking_starts)

    # 키워드 체크
    has_thinking_keyword = any(keyword in text_lower for keyword in thinking_keywords)

    return starts_with_thinking and has_thinking_keyword


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


def _load_reasoning_terms() -> List[str]:
    """
    reasoning/독백 탐지용 용어 목록.
    환경변수 LLM_REASONING_EXTRA_TERMS로 추가 term을 주입할 수 있다.
    """
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
    url_context_entries: int,
    recent_web_results: int,
) -> None:
    """
    질문 상세 로그는 호출당 1회만 출력한다.
    """
    if not _is_true(os.getenv("LLM_VERBOSE_QUESTION_LOG", "true")):
        return

    raw_query = user_query or ""
    logger.debug(
        f"[질문상세] tools={tools_count} max_iter={max_tool_iterations} "
        f"url_ctx={url_context_entries} web_ctx={recent_web_results} "
        f"farm={farm_name or '-'} query_len={len(raw_query)}"
    )


def _emit_answer_log_once(
    user_query: str,
    final_mode: str,
    stages: List[Dict[str, Any]],
    dropped_details: List[str],
    detected_terms: List[str],
    rewrite_attempts: int,
) -> None:
    """답변 필터링 상세 로그 (DEBUG 레벨). INFO 로깅은 _finalize_user_facing_answer에서 직접 수행."""
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
) -> str:
    """
    한국어 질문에서는 최종 답변에서 영어 reasoning/메타 라인을 강제로 제거한다.
    """
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

        if first_korean_pos is not None and first_korean_pos > 0 and ascii_ratio >= 0.35:
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
) -> str:
    """
    한국어 질문의 최종 응답에서 혼합 영문 꼬리/번역 괄호를 제거해
    사용자 노출 텍스트를 한국어 중심으로 강제 정리한다.
    """
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
        if not has_url:
            before_paren = normalized
            normalized = re.sub(
                r"\((?=[^)]*[A-Za-z])[^)]*\)",
                "",
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
    detected_terms: List[str] = []
    rewrite_attempts = 0

    # ── 필터링 전 원본 데이터 전체 로깅 ──
    logger.info(f"[필터링전-원본] len={len(raw_answer or '')}자")
    logger.info(f"[필터링전-원본내용]\n{raw_answer}")

    stage_snapshots.append(_snapshot_answer_stage("raw", raw_answer))
    _last_logged_text = raw_answer  # 마지막으로 내용을 로깅한 텍스트 추적

    filtered = filter_llm_response(raw_answer, filter_type="general")
    stage_snapshots.append(_snapshot_answer_stage("after_filter", filtered))
    if filtered != raw_answer:
        logger.info(f"[필터단계:filter] {len(raw_answer)}자→{len(filtered)}자 (차이={len(raw_answer) - len(filtered)}자)")
        logger.info(f"[필터단계:filter내용]\n{filtered}")
        _last_logged_text = filtered

    cleaned = clean_llm_response(filtered)
    stage_snapshots.append(_snapshot_answer_stage("after_clean", cleaned))
    if cleaned != filtered:
        logger.info(f"[필터단계:clean] {len(filtered)}자→{len(cleaned)}자 (차이={len(filtered) - len(cleaned)}자)")
        logger.info(f"[필터단계:clean내용]\n{cleaned}")
        _last_logged_text = cleaned

    # 방법 1 + 2: 영/한 중복 제거 + term 체크 기반 reasoning 제거
    candidate = _strip_reasoning_paragraphs(cleaned, dropped_details_out=dropped_details)
    stage_snapshots.append(_snapshot_answer_stage("after_overlap_term_strip", candidate))
    if candidate != cleaned:
        logger.info(f"[필터단계:reasoning제거] {len(cleaned)}자→{len(candidate)}자 (차이={len(cleaned) - len(candidate)}자)")
        logger.info(f"[필터단계:reasoning제거내용]\n{candidate}")
        _last_logged_text = candidate

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

    # ── 최종 결과 로깅 (이전 단계와 다를 때만 내용 출력) ──
    if dropped_details:
        logger.info(f"[필터링-삭제항목] {len(dropped_details)}건: {dropped_details}")

    if not _contains_reasoning_trace(candidate):
        logger.info(f"[필터링후-최종] len={len(candidate)}자 mode=direct_strip 원본대비={len(raw_answer) - len(candidate)}자 삭제")
        if candidate != _last_logged_text:
            logger.info(f"[필터링후-최종내용]\n{candidate}")
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

        logger.info(f"[필터링-재작성원본] 시도{attempt + 1} len={len(rewritten)}자")
        logger.info(f"[필터링-재작성원본내용]\n{rewritten}")

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

        if rewritten != before_rewrite_clean:
            logger.info(f"[필터링-재작성정리후] 시도{attempt + 1} {len(before_rewrite_clean)}자→{len(rewritten)}자")
            logger.info(f"[필터링-재작성정리후내용]\n{rewritten}")

        if not _contains_reasoning_trace(rewritten):
            logger.info(f"[필터링후-최종] len={len(rewritten)}자 mode=rewrite_success_{attempt + 1} 원본대비={len(raw_answer) - len(rewritten)}자 삭제")
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
    logger.info(f"[필터링후-최종] len={len(fallback)}자 mode=fallback_reasoning_possible 원본대비={len(raw_answer) - len(fallback)}자 삭제")
    if fallback != _last_logged_text:
        logger.info(f"[필터링후-최종내용]\n{fallback}")
    stage_snapshots.append(_snapshot_answer_stage("final", fallback))
    return fallback


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 스트리밍 청크 정리
# 스트리밍 청크에서 불필요한 내용 제거
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def clean_streaming_chunk(chunk):
    if not chunk:
        return chunk

    # Think 태그 제거
    if '<think>' in chunk.lower() or '</think>' in chunk.lower():
        logger.debug(f"[필터] Think 태그 청크 제거: {chunk[:100]}...")
        return ''

    # 생각 과정 패턴 감지 (공통 헬퍼 사용)
    if _is_thinking_text(chunk):
        logger.debug(f"[필터] 생각 과정 청크 제거: {chunk[:100]}...")
        return ''

    # 마크다운 헤더 제거
    chunk = re.sub(r"^(### )?(Final Answer|Response|Answer):?\s*", "", chunk, flags=re.IGNORECASE)

    return chunk


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

    # 3. 기본 정리 (공통)
    filtered_text = re.sub(r'\n\s*\n\s*\n', '\n\n', filtered_text)
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
    response_text = re.sub(r'\n\s*\n\s*\n', '\n\n', response_text)
    response_text = re.sub(r'[ \t]+', ' ', response_text)
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

    response_text = re.sub(r'\n\s*\n\s*\n', '\n\n', response_text)
    response_text = response_text.strip()

    # 필터링 결과 요약 로깅
    if len(original_text) > len(response_text):
        removed_chars = len(original_text) - len(response_text)
        logger.debug(f"[필터] LLM 응답 정리: {removed_chars}자 제거 ({len(original_text)} → {len(response_text)})")

    return response_text


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 최신 정보 자동 검색(선제 MCP 조회) 관련 헬퍼
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_URL_PATTERN = re.compile(r"(https?://[^\s<>'\"`]+)", re.IGNORECASE)


def _extract_urls_from_query(user_query: str) -> List[str]:
    raw_query = user_query or ""
    matches = _URL_PATTERN.findall(raw_query)
    normalized_urls: List[str] = []
    seen = set()
    for url in matches:
        cleaned = url.strip().rstrip(").,!?;\"'")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_urls.append(cleaned)
    return normalized_urls


def _sanitize_url_content_text(raw_text: str) -> str:
    text = raw_text or ""
    if not text:
        return ""

    # HTML 문서인 경우 주요 노이즈 제거 후 텍스트 추출
    if "<html" in text.lower() or "<body" in text.lower() or "<div" in text.lower():
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
        text = re.sub(r"(?is)<!--.*?-->", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)

    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _collect_url_context_from_query(user_query: str) -> Optional[Dict[str, Any]]:
    if not _is_true(os.getenv("LLM_AUTO_URL_CONTEXT", "true")):
        logger.debug("[URL컨텍스트] 자동 URL 본문 수집 비활성화(LLM_AUTO_URL_CONTEXT=false)")
        return None

    urls = _extract_urls_from_query(user_query)
    if not urls:
        return None

    from agri_ai_core.src.ai.mcp_client import mcp_fetch_request

    try:
        max_urls = max(1, min(int(os.getenv("LLM_AUTO_URL_MAX_LINKS", "2")), 5))
    except Exception:
        max_urls = 2
    try:
        timeout = max(3, min(int(os.getenv("LLM_AUTO_URL_FETCH_TIMEOUT", "20")), 60))
    except Exception:
        timeout = 20
    try:
        max_chars = max(300, min(int(os.getenv("LLM_AUTO_URL_MAX_CHARS", "6000")), 30000))
    except Exception:
        max_chars = 6000

    selected_urls = urls[:max_urls]
    logger.info(
        f"[URL컨텍스트] URL 추출={len(urls)}개 선택={len(selected_urls)}개 timeout={timeout}s max_chars={max_chars}"
    )
    for idx, selected_url in enumerate(selected_urls, start=1):
        logger.info(f"[URL컨텍스트] 대상[{idx}]={selected_url}")

    entries: List[Dict[str, Any]] = []
    failures: List[str] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json,text/plain,*/*",
    }

    for idx, url in enumerate(selected_urls, start=1):
        started_at = time.time()
        try:
            result = mcp_fetch_request(
                url=url,
                method="GET",
                headers=headers,
                timeout=timeout,
            )
        except Exception as fetch_err:
            elapsed = time.time() - started_at
            error_text = f"url={url} error={fetch_err}"
            failures.append(error_text)
            logger.warning(f"[URL컨텍스트] fetch 예외 {idx}/{len(selected_urls)} ({elapsed:.2f}s): {error_text}")
            continue

        elapsed = time.time() - started_at
        if not result.get("success"):
            error_text = str(result.get("text") or "unknown fetch failure")
            failures.append(f"url={url} error={error_text}")
            logger.warning(f"[URL컨텍스트] fetch 실패 {idx}/{len(selected_urls)} ({elapsed:.2f}s): {error_text}")
            continue

        status_code = int(result.get("status_code", 200) or 200)
        raw_text = ""
        json_data = result.get("json")
        if json_data is not None:
            try:
                raw_text = json.dumps(json_data, ensure_ascii=False)
            except Exception:
                raw_text = str(json_data)
        if not raw_text:
            raw_text = str(result.get("text", "") or "")

        cleaned = _sanitize_url_content_text(raw_text)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + " ...(truncated)"

        if not cleaned:
            failures.append(f"url={url} error=empty_content")
            logger.warning(f"[URL컨텍스트] fetch 성공 but empty content {idx}/{len(selected_urls)} ({elapsed:.2f}s): {url}")
            continue

        entry = {
            "url": url,
            "domain": _extract_domain(url),
            "status_code": status_code,
            "content": cleaned,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        entries.append(entry)

        logger.info(
            f"[URL컨텍스트] fetch 성공 {idx}/{len(selected_urls)} ({elapsed:.1f}s) status={status_code} chars={len(cleaned)} domain={entry['domain']}"
        )

    context = {
        "query": user_query,
        "urls": selected_urls,
        "entries": entries,
        "failures": failures,
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.info(
        f"[URL컨텍스트] 요약 성공={len(entries)}건 실패={len(failures)}건"
    )
    for idx, entry in enumerate(entries, start=1):
        logger.info(
            f"[URL컨텍스트] 본문[{idx}] domain={entry.get('domain')} status={entry.get('status_code')} chars={len(entry.get('content', ''))}"
        )
    if failures:
        logger.info(f"[URL컨텍스트] 실패 상세: {failures}")

    return context


def _format_url_context_for_prompt(context: Dict[str, Any]) -> str:
    if not context:
        return ""

    lines = [
        "다음은 사용자가 제공한 URL에서 직접 수집한 본문입니다.",
        "URL 본문 근거를 최우선으로 반영하고, 본문에 없는 사실은 추측하지 마세요.",
        f"- 사용자 질문: {context.get('query', '')}",
        f"- 수집 시각: {context.get('collected_at', '')}",
        f"- 대상 URL: {', '.join(context.get('urls', [])[:5])}",
        "[URL 본문 근거]",
    ]

    entries = context.get("entries") or []
    if not entries:
        lines.append("- 본문 수집 결과가 없습니다. 필요 시 일반 검색 또는 도구를 사용하세요.")
    else:
        for idx, entry in enumerate(entries, start=1):
            lines.append(
                f"{idx}. URL: {entry.get('url')} (domain={entry.get('domain')}, status={entry.get('status_code')})"
            )
            lines.append(f"   내용: {entry.get('content', '')}")

    return "\n".join(lines).strip()



def _extract_search_focused_query(user_query: str) -> str:
    """
    최신 웹검색용으로 사용자 질문의 핵심 문장만 추출한다.
    첨부파일 본문이 합쳐진 프롬프트(=== 첨부된 파일 내용 ===)를 제거해
    포털 검색 질의가 오염되지 않도록 한다.
    """
    raw = str(user_query or "").strip()
    if not raw:
        return ""

    marker_match = re.search(r"\n\s*===\s*첨부된 파일 내용\s*===", raw, flags=re.IGNORECASE)
    if marker_match:
        raw = raw[:marker_match.start()]

    # 첨부파일 메타 문구 제거
    raw = re.sub(r"\[첨부 파일:[^\]]+\]", " ", raw)
    raw = re.sub(r"===\s*첨부 파일 끝\s*===", " ", raw, flags=re.IGNORECASE)
    raw = raw.replace("=== 첨부된 파일 내용 ===", " ")

    lines = [line.strip() for line in raw.splitlines() if line and line.strip()]
    if not lines:
        return ""

    # 실제 질문은 보통 첫 줄에 존재하며, 보조 문장은 최대 2줄까지만 유지
    focused = " ".join(lines[:3]).strip()
    focused = re.sub(r"\s+", " ", focused).strip()
    if len(focused) > 220:
        focused = focused[:220].rstrip()
    return focused




def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
        return parsed.netloc.lower() or "unknown"
    except Exception:
        return "unknown"


def _normalize_url_for_dedupe(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "").lower()
        netloc = (parsed.netloc or "").lower()
        path = (parsed.path or "").rstrip("/")
        query = parsed.query or ""
        return f"{scheme}://{netloc}{path}?{query}"
    except Exception:
        return url.strip().lower()


def _collect_recent_web_context(user_query: str) -> Optional[Dict[str, Any]]:
    if not _is_true(os.getenv("LLM_AUTO_RECENT_WEB_CONTEXT", "true")):
        logger.debug("[최신정보] 자동 웹검색 비활성화(LLM_AUTO_RECENT_WEB_CONTEXT=false)")
        return None

    focused_query = _extract_search_focused_query(user_query)
    if not focused_query:
        logger.debug("[최신정보] 웹검색 대상 질의가 비어 자동 검색을 건너뜁니다.")
        return None

    logger.info("[최신정보] 라우터 결정에 따라 웹검색 실행 query=%s", focused_query[:160])

    from agri_ai_core.src.ai.mcp_client import search_web as mcp_search

    queries = [focused_query]

    try:
        max_queries = max(1, min(int(os.getenv("LLM_AUTO_RECENT_WEB_MAX_QUERIES", "3")), 5))
    except Exception:
        max_queries = 3

    try:
        per_query_limit = max(1, min(int(os.getenv("LLM_AUTO_RECENT_WEB_PER_QUERY_LIMIT", "3")), 5))
    except Exception:
        per_query_limit = 3

    try:
        max_total_results = max(1, min(int(os.getenv("LLM_AUTO_RECENT_WEB_MAX_RESULTS", "8")), 12))
    except Exception:
        max_total_results = 8

    selected_queries = queries[:max_queries]
    logger.info(
        f"[최신정보] MCP 웹검색 시작 query_count={len(selected_queries)} per_query_limit={per_query_limit} queries={selected_queries}"
    )

    merged_results: List[Dict[str, Any]] = []
    seen_urls = set()
    failures: List[str] = []

    for idx, query in enumerate(selected_queries, start=1):
        started_at = time.time()
        try:
            result = mcp_search(query, max_results=per_query_limit)
        except Exception as search_err:
            elapsed = time.time() - started_at
            error_text = f"query={query} error={search_err}"
            failures.append(error_text)
            logger.warning(f"[최신정보] MCP 검색 예외 {idx}/{len(selected_queries)} ({elapsed:.2f}s): {error_text}")
            continue

        elapsed = time.time() - started_at
        if not result.get("success"):
            error_text = result.get("error", "unknown error")
            failures.append(f"query={query} error={error_text}")
            logger.warning(f"[최신정보] MCP 검색 실패 {idx}/{len(selected_queries)} ({elapsed:.2f}s): {error_text}")
            continue

        raw_items = result.get("results", [])
        if not isinstance(raw_items, list):
            raw_items = []

        logger.info(f"[최신정보] MCP 검색 성공 {idx}/{len(selected_queries)} ({elapsed:.1f}s) {len(raw_items)}건")

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip() or query
            snippet = str(item.get("snippet", "")).strip()
            url = str(item.get("url", "")).strip()
            normalized_url = _normalize_url_for_dedupe(url)
            dedupe_key = normalized_url or f"{title}|{snippet[:120]}".lower()
            if dedupe_key in seen_urls:
                continue
            seen_urls.add(dedupe_key)

            merged_results.append(
                {
                    "title": title[:220],
                    "snippet": snippet[:420],
                    "url": url or "#",
                    "domain": _extract_domain(url),
                    "source_query": query,
                }
            )
            if len(merged_results) >= max_total_results:
                break
        if len(merged_results) >= max_total_results:
            break

    context = {
        "user_query": focused_query,
        "raw_user_query": user_query,
        "searched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "category": "general",
        "reason": "router_decision",
        "queries": selected_queries,
        "results": merged_results,
        "failures": failures,
    }

    logger.info(
        f"[최신정보] MCP 웹검색 요약 성공={len(merged_results)}건 실패={len(failures)}건"
    )
    for idx, item in enumerate(merged_results, start=1):
        logger.info(
            f"[최신정보] 결과[{idx}] domain={item.get('domain')} title={item.get('title','')[:60]}"
        )
    if failures:
        logger.info(f"[최신정보] 실패 상세: {failures}")

    return context


def _format_recent_web_context_for_prompt(context: Dict[str, Any]) -> str:
    if not context:
        return ""

    lines = [
        "다음은 시스템이 자동 수집한 최신 웹 검색 근거입니다.",
        "반드시 아래 근거를 우선 반영하고, 근거가 부족하면 추측하지 말고 부족하다고 명시하세요.",
        f"- 사용자 질문: {context.get('user_query', '')}",
        f"- 검색 시각: {context.get('searched_at', '')}",
        f"- 검색 분류: {context.get('category', 'general')}",
        f"- 사용 쿼리: {', '.join(context.get('queries', [])[:5])}",
        "[검색 결과]",
    ]

    results = context.get("results") or []
    failures = context.get("failures") or []
    if not results:
        lines.append("- 수집된 결과가 없습니다. 필요 시 search_web 도구를 다시 호출하세요.")
    else:
        for idx, item in enumerate(results, start=1):
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            domain = str(item.get("domain", "")).strip() or "unknown"
            url = str(item.get("url", "")).strip() or "#"
            lines.append(f"{idx}. 제목: {title}")
            lines.append(f"   요약: {snippet}")
            lines.append(f"   출처: {domain}")
            lines.append(f"   링크: {url}")

    if failures:
        lines.append("[검색 실패 정보]")
        for idx, failure in enumerate(failures[:5], start=1):
            lines.append(f"{idx}. {failure}")

    return "\n".join(lines).strip()


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
def get_llm_response_with_tools(
    user_query: str,
    farm_name: str = None,
    temperature: float = 0.7,
    max_tool_iterations: int = 5,
    allowed_tool_names: Optional[List[str]] = None,
    route_system_prompt: Optional[str] = None,
    enable_recent_web_context: Optional[bool] = None,
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """
    Tool Use를 지원하는 LLM 응답 생성
    LLM이 필요한 도구를 자동으로 선택하고 호출하여 최종 답변 생성

    Args:
        user_query: 사용자 질문
        farm_name: 농장명
        temperature: 창의성 정도
        max_tool_iterations: 최대 도구 호출 반복 횟수
        allowed_tool_names: 사용 허용 도구명 목록 (None이면 전체 허용)
        route_system_prompt: 자동 라우팅 정책 시스템 프롬프트
        enable_recent_web_context: 최신 웹 컨텍스트 자동 수집 여부 (None이면 기존 기본 동작)
        default_tool_args: 도구별 기본 인자

    Returns:
        str: 최종 응답
    """
    try:
        from agri_ai_core.src.ai.tools_definition import get_available_tools, get_system_prompt_with_tools
        from agri_ai_core.src.ai.tools_executor import execute_tool

        model_name = _get_model_name()
        tools = get_available_tools()
        if allowed_tool_names is not None:
            allowed_set = {
                str(name).strip()
                for name in (allowed_tool_names or [])
                if str(name).strip()
            }
            tools = [
                tool
                for tool in (tools or [])
                if str(((tool or {}).get("function") or {}).get("name", "")).strip() in allowed_set
            ]
        # 농장 전용 도구가 포함된 경우에만 농장 시스템 프롬프트 사용
        _farm_tool_names = {"search_farm_knowledge", "get_farm_realtime_data"}
        actual_tool_names = {
            str(((t or {}).get("function") or {}).get("name", "")).strip()
            for t in (tools or [])
        }
        if farm_name and (_farm_tool_names & actual_tool_names):
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
        # URL 컨텍스트 수집
        t_url_ctx = time.time()
        url_context = _collect_url_context_from_query(user_query)
        url_ctx_elapsed = time.time() - t_url_ctx
        url_ctx_count = len((url_context or {}).get("entries", []))
        if url_context:
            logger.info(f"[URL컨텍스트] 수집완료 entries={url_ctx_count} ({url_ctx_elapsed:.1f}s)")
        elif url_ctx_elapsed > 0.1:
            logger.info(f"[URL컨텍스트] 해당없음 ({url_ctx_elapsed:.1f}s)")

        # 최신 웹 검색 컨텍스트 수집
        t_web_ctx = time.time()
        if enable_recent_web_context is None:
            recent_web_context = _collect_recent_web_context(user_query)
        elif enable_recent_web_context:
            recent_web_context = _collect_recent_web_context(user_query)
        else:
            recent_web_context = None
        web_ctx_elapsed = time.time() - t_web_ctx
        web_ctx_count = len((recent_web_context or {}).get("results", []))
        if recent_web_context:
            logger.info(f"[웹검색컨텍스트] 수집완료 results={web_ctx_count} ({web_ctx_elapsed:.1f}s)")
        elif enable_recent_web_context is False:
            logger.info("[웹검색컨텍스트] 비활성화(라우터 결정)")

        if allowed_tool_names is not None:
            logger.info(
                f"[Tool Use] 허용도구={allowed_tool_names} 실제도구={[((t or {}).get('function') or {}).get('name') for t in tools]}"
            )

        _emit_question_log_once(
            user_query=user_query,
            farm_name=farm_name,
            max_tool_iterations=max_tool_iterations,
            tools_count=len(tools or []),
            url_context_entries=len((url_context or {}).get("entries", [])),
            recent_web_results=len((recent_web_context or {}).get("results", [])),
        )
        query_digest = _short_text_digest(user_query)

        # 메시지 히스토리
        messages = [{"role": "system", "content": system_prompt}]
        if route_system_prompt:
            messages.append({"role": "system", "content": route_system_prompt})
        if url_context:
            url_context_prompt = _format_url_context_for_prompt(url_context)
            if url_context_prompt:
                messages.append({"role": "system", "content": url_context_prompt})
                logger.debug(
                    f"[URL컨텍스트] 프롬프트 주입 완료 entries={len(url_context.get('entries', []))} prompt_len={len(url_context_prompt)}"
                )
        if recent_web_context:
            context_prompt = _format_recent_web_context_for_prompt(recent_web_context)
            if context_prompt:
                messages.append({"role": "system", "content": context_prompt})
                logger.debug(
                    f"[최신정보] 웹검색 컨텍스트 주입 완료 results={len(recent_web_context.get('results', []))} prompt_len={len(context_prompt)}"
                )
        messages.append({"role": "user", "content": user_query})

        logger.info(
            f"[Tool Use] 시작 model={model_name} tools={len(tools)}개 "
            f"messages={len(messages)}개 max_iterations={max_tool_iterations}"
        )

        # 도구 호출 반복 (최대 max_tool_iterations회)
        tools_supported = True  # 모델이 tools를 지원하는지 여부
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] --- 반복 {iteration + 1}/{max_tool_iterations} ---")

            # LLM 호출 (도구 포함)
            t_iter = time.time()
            current_tools = tools if tools_supported else None
            try:
                response = _ollama_chat(
                    model=model_name,
                    messages=messages,
                    tools=current_tools,
                    options={
                        "temperature": temperature,
                        "top_p": 0.9,
                        "top_k": 40,
                        "num_predict": NUM_PREDICT
                    },
                    keep_alive='1h'
                )
            except Exception as chat_err:
                err_msg = str(chat_err).lower()
                if "does not support tools" in err_msg or "not support tools" in err_msg:
                    logger.warning(
                        f"[Tool Use] 모델({model_name})이 tools를 지원하지 않음 → tools 없이 재시도"
                    )
                    tools_supported = False
                    response = _ollama_chat(
                        model=model_name,
                        messages=messages,
                        tools=None,
                        options={
                            "temperature": temperature,
                            "top_p": 0.9,
                            "top_k": 40,
                            "num_predict": NUM_PREDICT
                        },
                        keep_alive='1h'
                    )
                else:
                    raise

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
                return _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=final_answer,
                )

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

        # 최대 반복 횟수 도달
        logger.warning(f"[Tool Use] 최대 반복 횟수({max_tool_iterations}) 도달")

        # 마지막 메시지가 assistant 메시지면 그것을 반환
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=msg.get("content", "죄송합니다. 응답을 완료할 수 없습니다."),
                )
            elif hasattr(msg, 'content') and hasattr(msg, 'role'):
                if msg.role == "assistant":
                    return _finalize_user_facing_answer(
                        model_name=model_name,
                        user_query=user_query,
                        farm_name=farm_name,
                        raw_answer=msg.content,
                    )

        return "죄송합니다. 응답을 생성할 수 없습니다."

    except Exception as e:
        if _is_connection_related_error(e):
            logger.warning(f"Tool Use LLM 응답 생성 실패(연결/환경): {e}")
            return "죄송합니다. 현재 LLM 서버 연결이 불안정합니다. 잠시 후 다시 시도해 주세요."
        else:
            logger.error(f"Tool Use LLM 응답 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
        return f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}"
