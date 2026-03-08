# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# LLM 클라이언트 핵심 모듈
# Ollama LLM API와 통신하며, Tool Use(Function Calling)를 통한 응답 생성을 담당합니다.
# --->
# _use_mcp_fetch: MCP fetch 사용 여부
# _use_ollama_package: ollama 패키지 사용 여부
# _use_direct_ollama_http: Ollama 직접 HTTP 모드 사용 여부
# _is_direct_ollama_enabled: Ollama 직접 HTTP 모드 활성 여부
# _disable_direct_ollama_http: Ollama 직접 HTTP 모드 비활성화
# _is_connection_related_error: 연결 관련 에러 여부 판단
# _extract_model_names: 모델 목록(dict 리스트)에서 이름을 추출하는 공통 헬퍼
# _pkg_ollama_list_models: ollama 패키지로 모델 목록 조회
# _pkg_ollama_chat: ollama 패키지 채팅 호출
# _build_ollama_url: Ollama API URL 생성
# _direct_ollama_json: Ollama 직접 HTTP JSON 모드 호출
# _direct_ollama_list_models: Ollama 직접 HTTP로 모델 목록 조회
# _direct_ollama_chat: Ollama 직접 HTTP 채팅 호출
# _mcp_ollama_list_models: MCP 경유 Ollama 모델 목록 조회
# _mcp_ollama_chat: MCP 경유 Ollama 채팅 호출
# _serialize_for_log: 로그용 JSON 직렬화
# _log_llm_request_json: LLM 요청 JSON 로깅
# _log_llm_response_json: LLM 응답 JSON 로깅
# _ollama_chat: Ollama 채팅 통합 함수 (직접/MCP/패키지 자동 선택)
# _extract_message_content: Ollama 응답에서 메시지 내용 추출
# _normalize_assistant_message: 어시스턴트 메시지 정규화
# _extract_tool_calls: Ollama 응답에서 도구 호출 추출
# _extract_tool_name: 도구 호출에서 도구명 추출
# _extract_tool_arguments: 도구 호출에서 인자 추출
# _normalize_tool_arguments: 도구 인자 정규화
# _get_available_models: Ollama에서 사용 가능한 모델 목록 가져오기
# _get_model_name: 환경 설정에서 모델명을 가져오거나 기본값을 반환
# _perform_llm_warmup: LLM 워밍업 수행
# initialize_background_warmup: 백그라운드 워밍업 초기화
# _load_reasoning_terms: reasoning/독백 탐지용 용어 목록.
# _find_reasoning_terms: 텍스트에서 추론 용어 탐색
# _line_has_korean: 한국어 포함 라인 여부
# _count_korean_chars: 한국어 문자 수 카운트
# _looks_like_reasoning_line: 추론 라인 패턴 판단
# _extract_measure_tokens: 측정값 토큰 추출
# _extract_sensor_concepts: 센서 관련 개념 추출
# _is_english_korean_overlap: 영한 혼합 여부 판단
# _snapshot_answer_stage: 응답 단계별 스냅샷 로깅
# _emit_question_log_once: 질문 로그 1회 출력
# _is_reasoning_paragraph: 추론 단락 여부 판단
# _strip_reasoning_paragraphs: 추론 단락 제거
# _strip_non_korean_reasoning_for_korean_query: 한국어 질문에 대한 비한국어 추론 제거
# _force_korean_surface_for_korean_query: 한국어 질문에 대한 한국어 표면 강제
# _contains_reasoning_trace: 추론 흔적 포함 여부 판단
# _rewrite_without_reasoning: 추론 제거 후 텍스트 재작성
# _force_honorific_response_enabled: 존댓말 강제 변환 활성 여부
# _rewrite_to_honorific: 존댓말로 변환
# _clean_page_content: 페이지 본문에서 노이즈 제거 후 도입부 추출 (키워드 불필요, LLM이 관련성 판단).
# _refine_search_web: search_web 결과를 구조적으로 정제하여 간결한 텍스트로 변환한다 (LLM이 관련성 판단).
# _refine_fetch_url: fetch_url_content 결과를 구조적으로 정제한다 (LLM이 관련성 판단).
# _refine_tool_result: 도구 결과를 LLM 메시지에 넣기 전에 도구별 지능형 정제를 수행한다.
# _needs_honorific_rewrite: 반말이 감지되면 True, 산문 문장이 모두 존댓말이면 False
# _enforce_honorific_response: 존댓말 응답 강제 적용
# _finalize_user_facing_answer: 최종 사용자 응답 생성
# filter_llm_response: LLM 응답 필터링
# clean_llm_response: LLM 응답 정리
# _sanitize_markdown_links: Tool Use 지원 LLM 응답 생성
# _append_source_urls: 출처 URL 추가
# _determine_response_type: 사용된 도구 목록으로 응답 유형 결정.
# _build_structured_result: 구조화된 응답 결과 생성.
# _filter_greeting_turns: 인사/잡담만으로 구성된 턴 쌍(user+assistant)을 제외한다.
# _coerce_numeric_id: LLM이 비정수 값을 ID로 넣는 경우 기본값(정수)으로 교정
# get_llm_response_with_tools: Tool Use 지원 LLM 응답 생성 (LLM이 도구 자율 선택)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import time
import json
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
from agri_ai_core.config import settings, NUM_PREDICT, NUM_PREDICT_REWRITE, get_ollama_url
from agri_ai_core.src.utils.validators import is_true

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
_SEARCH_WEB_REFINE_MAX_RESULTS = max(1, int(os.getenv("SEARCH_WEB_REFINE_MAX_RESULTS", "5")))
_SEARCH_WEB_REFINE_DESC_CHARS = max(80, int(os.getenv("SEARCH_WEB_REFINE_DESC_CHARS", "200")))
_SEARCH_WEB_REFINE_CONTENT_CHARS = max(120, int(os.getenv("SEARCH_WEB_REFINE_CONTENT_CHARS", "400")))
_SEARCH_WEB_REFINE_TOTAL_CHARS = max(1000, int(os.getenv("SEARCH_WEB_REFINE_TOTAL_CHARS", "3200")))


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


# ============================================================
# 모델 목록(dict 리스트)에서 이름을 추출하는 공통 헬퍼
# ============================================================
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
    if tool_name == "search_farm_knowledge":
        return {
            "query": _pick("query"),
            "n_results": _pick("n_results", 3),
            "file_name": _pick("file_name"),
            "farm_id": _pick("farm_id"),
            "house_id": _pick("house_id"),
        }
    if tool_name == "get_farm_realtime_data":
        farm_id = _pick("farm_id")
        house_id = _pick("house_id")
        default_farm_id = default_args.get("farm_id")
        default_house_id = default_args.get("house_id")

        # LLM이 farm_name 같은 비정수 값을 farm_id로 넣는 경우를 방지한다.
        farm_id = _coerce_numeric_id(farm_id, default_farm_id)
        house_id = _coerce_numeric_id(house_id, default_house_id)

        return {
            "house_id": house_id,
            "farm_id": farm_id,
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

_DEFAULT_REASONING_TERMS = [
    "first,", "second,", "third,", "hmm,", "wait,", "so,",
    "that means", "so the main points", "putting it all together",
    "here's the answer", "in a clear, concise", "in korean sentence",
    "let me think", "based on",
    "relay statuses", "sensor data",
    "advise checking", "the system expects",
    "can't be converted to json", "json serializable",
    "maybe it's", "might be a problem",
]
# 하위 호환 별칭
_REASONING_HINT_KEYWORDS = _DEFAULT_REASONING_TERMS

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


def _find_reasoning_terms(text: str) -> List[str]:
    lowered = (text or "").lower()
    return [term for term in _REASONING_TERMS if term in lowered]


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


def _emit_question_log_once(
    user_query: str,
    farm_name: Optional[str],
    max_tool_iterations: int,
    tools_count: int,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 질문 상세 로그는 호출당 1회만 출력한다.
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> None:
    if not is_true(os.getenv("LLM_VERBOSE_QUESTION_LOG", "true")):
        return

    raw_query = user_query or ""
    logger.debug(
        f"[질문상세] tools={tools_count} max_iter={max_tool_iterations} "
        f"farm={farm_name or '-'} query_len={len(raw_query)}"
    )


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

        # 한국어가 전혀 없는 라인은 제거 (단, 마크다운 구조 요소는 보존)
        if not _line_has_korean(stripped):
            # 마크다운 수평선 (---, ***, ___) 보존
            if re.match(r'^[-*_]{3,}\s*$', stripped):
                kept.append(line)
                continue
            # 마크다운 테이블 구분선 (|---|---|) 보존
            if re.match(r'^\|[-:\s|]+\|$', stripped):
                kept.append(line)
                continue
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
            and not re.match(r'^#{1,6}\s', normalized)
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
        "최종 사용자 응답만 한국어 존댓말로 작성하라."
    )
    rewrite_user = (
        f"[질문]\n{user_query}\n\n"
        f"[농장]\n{farm_label}\n\n"
        "[규칙]\n"
        "1) 내부 생각(예: First, Hmm, Wait, So the main points...) 금지\n"
        "2) 오류 원인 분석 독백 금지\n"
        "3) 핵심 상태와 조치만 간결하게 제시\n"
        "4) 모든 문장을 공손한 존댓말로 작성 (반말 금지)\n\n"
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
            "num_predict": NUM_PREDICT_REWRITE,
            "think": False,
        },
        keep_alive="1h",
    )
    return _extract_message_content(response) or ""


def _force_honorific_response_enabled() -> bool:
    return is_true(os.getenv("FORCE_HONORIFIC_RESPONSE", "true"))


def _rewrite_to_honorific(
    model_name: str,
    user_query: str,
    draft_answer: str,
    farm_name: Optional[str] = None,
) -> str:
    farm_label = farm_name or "농장"
    rewrite_system = (
        "너는 문체 교정기다. 의미/수치/단위/URL/목록 순서를 유지하면서 "
        "최종 답변을 공손한 한국어 존댓말로만 바꿔라. "
        "내부 추론/독백은 절대 출력하지 마라."
    )
    rewrite_user = (
        f"[질문]\n{user_query}\n\n"
        f"[농장]\n{farm_label}\n\n"
        "[규칙]\n"
        "1) 모든 문장을 존댓말(해요체 또는 하십시오체)로 변환\n"
        "2) 반말, 친구 말투, 명령조 표현 금지\n"
        "3) 사실/수치/링크/항목 구조는 유지\n\n"
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
            "num_predict": NUM_PREDICT_REWRITE,
            "think": False,
        },
        keep_alive="1h",
    )
    return _extract_message_content(response) or ""


# ============================================================================
# 도구 결과 정제 (tool_result → LLM 메시지 추가 전 지능형 축약)
# ============================================================================

_NOISE_LINE_RE = re.compile(
    r"^(검색|로그인|회원가입|메뉴|홈|공유|댓글|구독|광고|쿠키|Copyright|All rights)"
)


# ============================================================
# 페이지 본문에서 노이즈 제거 후 도입부 추출 (키워드 불필요, LLM이 관련성 판단).
# ============================================================
def _clean_page_content(text: str, max_chars: int) -> str:
    if not text or not text.strip():
        return ""
    paragraphs = re.split(r"\n{2,}", text)
    if len(paragraphs) <= 1:
        paragraphs = text.split("\n")
    clean = [p.strip() for p in paragraphs
             if len(p.strip()) >= 10 and not _NOISE_LINE_RE.match(p.strip())]
    if not clean:
        return text[:max_chars].strip()
    result, total = [], 0
    for p in clean:
        if total + len(p) > max_chars:
            remaining = max_chars - total
            if remaining > 50:
                result.append(p[:remaining].strip())
            break
        result.append(p)
        total += len(p) + 1
    return "\n".join(result)


# ============================================================
# search_web 결과를 구조적으로 정제하여 간결한 텍스트로 변환한다 (LLM이 관련성 판단).
# ============================================================
def _refine_search_web(tool_result: str, user_query: str) -> str:
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result

    results = data.get("results", [])
    if not results:
        return tool_result

    selected_results = results[:_SEARCH_WEB_REFINE_MAX_RESULTS]
    lines = [f"[웹검색 결과 {len(results)}건 중 상위 {len(selected_results)}건]", ""]

    for idx, item in enumerate(selected_results, 1):
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        description = (item.get("description") or "").strip()
        page_content = (item.get("page_content") or "").strip()

        lines.append(f"{idx}. 제목: {title}")
        if url:
            lines.append(f"   URL: {url}")
        if description:
            lines.append(f"   요약: {description[:_SEARCH_WEB_REFINE_DESC_CHARS]}")
        if page_content:
            cleaned = _clean_page_content(page_content, _SEARCH_WEB_REFINE_CONTENT_CHARS)
            if cleaned:
                lines.append(f"   본문: {cleaned}")
        lines.append("")

    lines.append(
        "지시: 위 검색 결과의 본문 내용을 종합하여 구체적이고 자세한 답변을 작성하세요. "
        "핵심 요약 + 세부 항목 정리 + 출처 링크 형식으로 답변하세요."
    )

    refined_text = "\n".join(lines)
    if len(refined_text) > _SEARCH_WEB_REFINE_TOTAL_CHARS:
        refined_text = refined_text[:_SEARCH_WEB_REFINE_TOTAL_CHARS].rstrip() + "\n...(중략)..."
    return refined_text


# ============================================================
# fetch_url_content 결과를 구조적으로 정제한다 (LLM이 관련성 판단).
# ============================================================
def _refine_fetch_url(tool_result: str, user_query: str) -> str:
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result

    content = (data.get("content") or "").strip()
    if not content or len(content) <= 2000:
        return tool_result

    refined = _clean_page_content(content, 2000)

    url = data.get("url", "")
    lines = [
        "[URL 본문 정제]",
        f"URL: {url}",
        "본문:",
        refined,
    ]
    return "\n".join(lines)


# 센서 필드 한글 약어 매핑 (토큰 절감)
_SENSOR_SHORT = {
    "indoor_temperature": "실내온도",
    "indoor_humidity": "실내습도",
    "outdoor_temperature": "외부온도",
    "outdoor_humidity": "외부습도",
    "co2": "CO2",
    "water_temperature": "수온",
    "light_level": "조도",
    "water_level": "수위",
}


def _refine_realtime_data(tool_result: str) -> str:
    """get_farm_realtime_data 결과를 컴팩트 텍스트로 변환.
    ~1.5KB JSON → ~200~400자 텍스트로 압축하여 LLM 컨텍스트 절감.
    """
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result

    if not data.get("success"):
        return tool_result

    house_id = data.get("house_id", "?")
    parts = [f"[{house_id}호재배사]"]

    # 센서 데이터 압축
    sensor = data.get("sensor")
    if sensor and isinstance(sensor, dict):
        sensor_items = []
        for key, label in _SENSOR_SHORT.items():
            val = sensor.get(key)
            if val is not None:
                sensor_items.append(f"{label}={val}")
        if sensor_items:
            parts.append("센서: " + ", ".join(sensor_items))

    # 릴레이 데이터 압축 (relay_mapping 사용 → ON/OFF 장치명만)
    relay_mapping = data.get("relay_mapping")
    if relay_mapping and isinstance(relay_mapping, dict):
        on_devices = []
        off_devices = []
        for pin_key, info in relay_mapping.items():
            if isinstance(info, dict):
                label = info.get("name", info.get("device", pin_key))
                if info.get("value"):
                    on_devices.append(label)
                else:
                    off_devices.append(label)
        if on_devices:
            parts.append("ON: " + ", ".join(on_devices))
        if off_devices:
            parts.append("OFF: " + ", ".join(off_devices))
    elif data.get("relay") and isinstance(data["relay"], dict):
        # relay_mapping이 없는 경우 raw relay fallback
        on_pins = [k for k, v in data["relay"].items()
                   if k.startswith("relay_") and k.endswith("_flag") and v]
        off_pins = [k for k, v in data["relay"].items()
                    if k.startswith("relay_") and k.endswith("_flag") and not v]
        if on_pins:
            parts.append(f"ON: {', '.join(on_pins)}")
        if off_pins:
            parts.append(f"OFF: {', '.join(off_pins)}")

    timestamp = data.get("data_retrieved_at", "")
    if timestamp:
        parts.append(f"조회시각: {timestamp}")

    return " | ".join(parts)


# ============================================================
# 도구 결과를 LLM 메시지에 넣기 전에 도구별 지능형 정제를 수행한다.
# ============================================================
def _refine_tool_result(tool_name: str, tool_result: str, user_query: str) -> str:
    if not tool_result:
        return tool_result or ""
    if tool_name == "search_web":
        return _refine_search_web(tool_result, user_query)
    if tool_name == "fetch_url_content":
        return _refine_fetch_url(tool_result, user_query)
    if tool_name == "search_farm_knowledge":
        return _refine_farm_knowledge(tool_result)
    if tool_name == "get_farm_realtime_data":
        return _refine_realtime_data(tool_result)
    return tool_result


# 네비게이션 잡음 패턴 (웹 스크래핑 아티팩트)
_NAV_NOISE_RE = re.compile(
    r"(본문\s*바로가기|주메뉴\s*바로가기|태극기\s*이\s*누리집|국가상징\s*알아보기"
    r"|화면크기\s*작게|통합로그인|전체메뉴|로그인\s*로그아웃|로그인\s*회원가입"
    r"|내\s*검색\s*검색\s*관리\s*글쓰기|메뉴\s*홈\s*태그\s*방명록"
    r"|반응형\s*&nbsp;|본문\s*바로가기\s*글루타민)"
)


def _strip_nav_noise(text: str) -> str:
    """웹 스크래핑 네비게이션 잡음을 제거한다."""
    if not text:
        return text
    # 네비게이션 패턴 이후 텍스트를 잘라냄
    parts = _NAV_NOISE_RE.split(text)
    if len(parts) <= 1:
        return text
    # 네비게이션 시작 전까지만 유지
    cleaned = parts[0].rstrip()
    return cleaned if len(cleaned) > 30 else text


# LLM 답변 생성에 불필요한 metadata 키 (출처 표시에 필요한 title, url은 유지)
_UNNECESSARY_META_KEYS = {
    "record_datetime", "data_kind", "distance", "collection", "query",
    "learning_date", "chunk_id", "file_size", "total_chunks",
    "is_learned_flag", "processing_time", "processing_date", "farm_id",
    "file_extension", "document_type", "crop_name",
}


def _refine_farm_knowledge(tool_result: str) -> str:
    """search_farm_knowledge 결과를 경량화한다.
    - description이 content와 중복이면 제거
    - 불필요한 metadata 키 제거
    - 네비게이션 잡음 제거
    """
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result

    results = data.get("results")
    if not results or not isinstance(results, list):
        return tool_result

    for item in results:
        # 1) 네비게이션 잡음 제거
        content = item.get("content", "")
        if content:
            item["content"] = _strip_nav_noise(content)

        # 2) description이 content와 중복이면 제거
        meta = item.get("metadata", {})
        desc = meta.get("description", "")
        if desc and content and desc[:50] in content:
            del meta["description"]

        # 3) 불필요한 metadata 키 제거
        for key in _UNNECESSARY_META_KEYS:
            meta.pop(key, None)

    return json.dumps(data, ensure_ascii=False)


_HONORIFIC_ENDINGS = re.compile(
    r"(합니다|습니다|세요|해요|드립니다|주세요|겠습니다|됩니다|입니다|바랍니다|있습니다|없습니다"
    r"|하세요|보세요|으세요|십시오|시오|십니다|랍니다|옵니다|나요|인가요|을까요|ㅂ니다)"
    r"[.!?\s~]*$",
    re.MULTILINE,
)
_BANMAL_ENDINGS = re.compile(
    r"(한다|된다|이다|있다|없다|했다|봐라|해라|하자|할게|할거야|거야|인데|는데|건데"
    r"|잖아|거든|는걸|할까|일까|였다|됐다|갔다|왔다|나온다|들어간다)"
    r"[.!?\s~]*$",
    re.MULTILINE,
)

# 마크다운 비산문(non-prose) 라인 패턴
_NON_PROSE_LINE = re.compile(
    r"^\s*("
    r"#{1,6}\s"          # 마크다운 헤더
    r"|[-*+]\s"          # 불릿 리스트
    r"|\d+[.)]\s"        # 번호 리스트
    r"|```"              # 코드 블록
    r"|\|"               # 테이블 행
    r"|>"                # 인용 블록
    r"|\[출처\]"         # 출처 링크
    r")"
)
# _KOREAN_CHAR_RE는 801행에서 이미 정의됨 (중복 제거)


# ============================================================
# 반말이 감지되면 True, 산문 문장이 모두 존댓말이면 False
# ============================================================
def _needs_honorific_rewrite(text: str) -> bool:
    # 라인 단위로 분리하여 마크다운 구조 요소 필터링
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 3]

    prose_sentences = []
    for line in lines:
        # 마크다운 구조 요소 제외
        if _NON_PROSE_LINE.match(line):
            continue
        # 한국어가 없는 라인(영문/숫자/기호만) 제외
        if not _KOREAN_CHAR_RE.search(line):
            continue
        # 산문 문장 분리
        for seg in re.split(r'[.!?\n]', line):
            seg = seg.strip()
            if len(seg) > 5 and _KOREAN_CHAR_RE.search(seg):
                prose_sentences.append(seg)

    if not prose_sentences:
        return False

    # 반말이 하나라도 있으면 재작성 필요
    banmal_count = sum(1 for s in prose_sentences if _BANMAL_ENDINGS.search(s))
    if banmal_count > 0:
        logger.debug(f"[존댓말검사] 반말 감지={banmal_count}건 → 재작성 필요")
        return True

    # 존댓말이 1개 이상이고 반말이 없으면 OK
    honorific_count = sum(1 for s in prose_sentences if _HONORIFIC_ENDINGS.search(s))
    if honorific_count > 0:
        logger.debug(f"[존댓말검사] 존댓말={honorific_count}/{len(prose_sentences)}건, 반말=0 → 스킵")
        return False

    # 존댓말도 반말도 없는 경우 (명사형 종결 등) → 재작성하지 않음
    logger.debug(f"[존댓말검사] 존댓말·반말 모두 미감지 ({len(prose_sentences)}건) → 스킵")
    return False


def _enforce_honorific_response(
    model_name: str,
    user_query: str,
    farm_name: Optional[str],
    answer_text: str,
) -> str:
    candidate = (answer_text or "").strip()
    if not candidate:
        return candidate
    if not _force_honorific_response_enabled():
        return candidate

    if not _needs_honorific_rewrite(candidate):
        logger.info("[존댓말교정] 이미 존댓말 → LLM 교정 스킵")
        return candidate

    try:
        _t_hon_llm = time.time()
        logger.debug(f"[PERF:대화] 존댓말교정-LLM호출 시작 (입력={len(candidate)}자)")
        rewritten = _rewrite_to_honorific(
            model_name=model_name,
            user_query=user_query,
            farm_name=farm_name,
            draft_answer=candidate,
        )
        _hon_llm_s = time.time() - _t_hon_llm
        logger.debug(f"[PERF:대화] 존댓말교정-LLM호출={_hon_llm_s:.1f}s (출력={len(rewritten or '')}자)")
        if rewritten and rewritten.strip():
            candidate = rewritten.strip()
    except Exception as err:
        logger.warning(f"[존댓말교정] 교정 실패: {err}")

    candidate = clean_llm_response(candidate)
    candidate = _strip_reasoning_paragraphs(candidate)
    candidate = _strip_non_korean_reasoning_for_korean_query(
        candidate,
        user_query=user_query,
    )
    candidate = _force_korean_surface_for_korean_query(
        candidate,
        user_query=user_query,
    )
    return _sanitize_markdown_links(candidate)


def _finalize_user_facing_answer(
    model_name: str,
    user_query: str,
    farm_name: Optional[str],
    raw_answer: str,
) -> str:
    _t_finalize_start = time.time()
    stage_snapshots: List[Dict[str, Any]] = []
    dropped_details: List[str] = []
    rewrite_attempts = 0

    # ── 필터링 전 원본 ──
    logger.info(f"[필터링전-원본] len={len(raw_answer or '')}자")
    logger.info(f"[필터링전-원본내용]\n{raw_answer}")

    stage_snapshots.append(_snapshot_answer_stage("raw", raw_answer))

    _t_clean = time.time()
    cleaned = clean_llm_response(raw_answer)
    stage_snapshots.append(_snapshot_answer_stage("after_clean", cleaned))
    _clean_ms = (time.time() - _t_clean) * 1000
    if cleaned != raw_answer:
        logger.info(f"[필터단계:clean] {len(raw_answer)}자→{len(cleaned)}자")
        logger.info(f"[필터단계:clean내용]\n{cleaned}")

    _t_strip = time.time()
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

    _strip_ms = (time.time() - _t_strip) * 1000
    logger.debug(
        f"[PERF:대화] 후처리-텍스트필터={_filter_ms:.0f}ms, "
        f"클린={_clean_ms:.0f}ms, 추론제거={_strip_ms:.0f}ms"
    )

    if not _contains_reasoning_trace(candidate):
        _t_honorific = time.time()
        candidate = _enforce_honorific_response(
            model_name=model_name,
            user_query=user_query,
            farm_name=farm_name,
            answer_text=candidate,
        )
        _honorific_s = time.time() - _t_honorific
        _finalize_total_s = time.time() - _t_finalize_start
        diff = len(raw_answer) - len(candidate)
        logger.info(f"[필터링완료] {len(raw_answer)}자→{len(candidate)}자 ({diff}자 삭제)")
        logger.info(f"[최종답변내용]\n{candidate}")
        logger.debug(
            f"[PERF:대화] 후처리-존댓말교정={_honorific_s:.1f}s, "
            f"후처리-전체={_finalize_total_s:.1f}s"
        )
        stage_snapshots.append(_snapshot_answer_stage("final", candidate))
        return candidate

    detected_terms = _find_reasoning_terms(candidate)
    logger.info(f"[필터링-reasoning잔존] reasoning흔적 감지 terms={detected_terms} → 재작성 시도")

    rewritten = candidate
    for attempt in range(1):
        rewrite_attempts = attempt + 1
        _t_rewrite = time.time()
        logger.info(f"[필터링-재작성] 시도 {attempt + 1}/1 입력길이={len(rewritten)}자")
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

        _rewrite_s = time.time() - _t_rewrite
        logger.debug(f"[PERF:대화] 후처리-reasoning재작성LLM={_rewrite_s:.1f}s (시도{attempt + 1})")
        stage_snapshots.append(_snapshot_answer_stage(f"rewrite_raw_{attempt + 1}", rewritten))

        before_rewrite_clean = rewritten
        rewritten = clean_llm_response(rewritten)
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
            _t_hon2 = time.time()
            rewritten = _enforce_honorific_response(
                model_name=model_name,
                user_query=user_query,
                farm_name=farm_name,
                answer_text=rewritten,
            )
            _hon2_s = time.time() - _t_hon2
            _finalize_total_s = time.time() - _t_finalize_start
            diff = len(raw_answer) - len(rewritten)
            logger.info(f"[필터링완료] {len(raw_answer)}자→{len(rewritten)}자 ({diff}자 삭제, 재작성{attempt + 1}회)")
            logger.info(f"[최종답변내용]\n{rewritten}")
            logger.debug(
                f"[PERF:대화] 후처리-재작성후존댓말={_hon2_s:.1f}s, "
                f"후처리-전체={_finalize_total_s:.1f}s"
            )
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
    _t_hon3 = time.time()
    fallback = _enforce_honorific_response(
        model_name=model_name,
        user_query=user_query,
        farm_name=farm_name,
        answer_text=fallback,
    )
    _hon3_s = time.time() - _t_hon3
    _finalize_total_s = time.time() - _t_finalize_start
    diff = len(raw_answer) - len(fallback)
    logger.info(f"[필터링완료] {len(raw_answer)}자→{len(fallback)}자 ({diff}자 삭제, fallback)")
    logger.info(f"[최종답변내용]\n{fallback}")
    logger.debug(
        f"[PERF:대화] 후처리-fallback존댓말={_hon3_s:.1f}s, "
        f"후처리-전체={_finalize_total_s:.1f}s"
    )
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
def clean_llm_response(response_text):
    """LLM 응답 필터링 + 정리 통합 함수.
    Think 태그 제거, 생각 과정 라인 제거, 마크다운 헤더/코드블록 제거, 메타 추론 제거, 빈 줄 정리."""
    if not response_text:
        return response_text

    original_text = response_text
    original_length = len(response_text)
    removed_lines = []
    has_korean_any = _line_has_korean(response_text)

    # 1. Think 태그 제거
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<thinking>.*?</thinking>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<think>.*', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<thinking>.*', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)
    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    # 2. 생각 과정 라인 제거 + 영문 메타 추론 제거
    _meta_reasoning_keywords = (
        "user", "tools", "tool", "respond", "response", "answer", "final answer",
        "language", "markdown", "check if", "make sure", "keep it", "need to",
        "i need to", "i should", "let me", "let's", "reasoning", "analysis",
        "the user said", "might be asking", "direct query", "call any tools",
        "tools are for", "statement, not a question", "as the ai",
        "that means", "decimal", "json serializable", "converted to json",
    )
    _meta_reasoning_starts = (
        "check if", "make sure", "keep it", "need to", "i need to", "i should",
        "let me", "let's", "respond", "answer", "use the", "given", "since",
        "okay,", "wait,", "well,", "so,", "now,", "hmm,",
    )

    lines = response_text.split('\n')
    cleaned_lines = []
    for line in lines:
        line_stripped = line.strip()
        has_korean = _line_has_korean(line)

        is_thinking = False
        if not has_korean:
            for pattern in _THINKING_PATTERNS:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_thinking = True
                    removed_lines.append(line_stripped[:100])
                    break

        if not is_thinking and has_korean_any and line_stripped:
            lower_line = line_stripped.lower()
            has_meta_keyword = any(kw in lower_line for kw in _meta_reasoning_keywords)
            starts_as_meta = any(lower_line.startswith(p) for p in _meta_reasoning_starts)
            ascii_alpha_count = sum(1 for c in line_stripped if c.isascii() and c.isalpha())
            non_space_count = sum(1 for c in line_stripped if not c.isspace())
            ascii_ratio = (ascii_alpha_count / non_space_count) if non_space_count else 0.0
            if has_meta_keyword and (starts_as_meta or ascii_ratio >= 0.20):
                is_thinking = True
                removed_lines.append(line_stripped[:100])

        if not is_thinking:
            cleaned_lines.append(line)

    if removed_lines:
        logger.debug(f"[필터] 생각 과정 라인 {len(removed_lines)}개 제거:")
        for removed in removed_lines[:5]:
            logger.debug(f"  - {removed}...")
        if len(removed_lines) > 5:
            logger.debug(f"  ... 외 {len(removed_lines) - 5}개")

    response_text = '\n'.join(cleaned_lines)

    # 3. 마크다운 헤더 제거
    for hdr in (r"^(### )?Final Answer:?\s*", r"^(### )?Final Output:?\s*",
                r"^(### )?Response:?\s*", r"^(### )?Answer:?\s*", r"^(### )?결론:?\s*"):
        response_text = re.sub(hdr, "", response_text, flags=re.MULTILINE | re.IGNORECASE)

    # 4. 코드 블록 마커 제거
    response_text = re.sub(r"^```[a-zA-Z]*\s*$", "", response_text, flags=re.MULTILINE)
    response_text = re.sub(r"^```\s*$", "", response_text, flags=re.MULTILINE)

    # 5. 빈 줄 정리 + 다중 공백 축소
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = re.sub(r'[ \t]{2,}(?!\n)', ' ', response_text)
    response_text = response_text.strip()

    # 6. 영문 검증/판단 문장 제거 (한글 응답 내)
    if has_korean_any:
        sentence_removed_count = 0
        for line in response_text.split('\n'):
            if _line_has_korean(line):
                continue
            sentences = [s.strip() for s in line.split('.') if s.strip()]
            filtered_sentences = []
            for sentence in sentences:
                is_verification = False
                if len(sentence) < 200 and not _line_has_korean(sentence):
                    for pattern in _THINKING_PATTERNS:
                        if re.match(pattern, sentence.strip(), re.IGNORECASE):
                            is_verification = True
                            sentence_removed_count += 1
                            break
                if not is_verification:
                    filtered_sentences.append(sentence)
            if filtered_sentences:
                new_line = '. '.join(filtered_sentences)
                if new_line and not new_line.endswith('.'):
                    new_line += '.'
                response_text = response_text.replace(line, new_line)
            else:
                response_text = response_text.replace(line, '')
        if sentence_removed_count > 0:
            logger.debug(f"[필터] 검증/판단 문장 {sentence_removed_count}개 추가 제거")

    # 7. 최종 빈 줄 정리
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = response_text.strip()

    # 8. 과도한 제거 검사 (90% 이상 제거 시 폴백)
    final_length = len(response_text)
    if original_length > 0:
        removal_ratio = (original_length - final_length) / original_length
        if removal_ratio > 0.9:
            logger.warning(f"필터링으로 인해 응답의 {removal_ratio*100:.1f}%가 제거됨")
            if final_length < 10:
                fallback = re.sub(r"<think>.*?</think>\s*", "", original_text, flags=re.DOTALL | re.IGNORECASE)
                if len(fallback.strip()) > final_length:
                    response_text = fallback.strip()
        elif removal_ratio > 0.1:
            removed_chars = original_length - final_length
            logger.debug(f"[필터] LLM 응답 정리: {removed_chars}자 제거 ({original_length} → {final_length})")

    return response_text


# filter_llm_response → clean_llm_response 호환 래퍼 (내부 호출 유지용)
def filter_llm_response(text, filter_type="general", query_type=None):
    return clean_llm_response(text)



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
# 마크다운 링크 중 유효하지 않은 URL을 가진 링크를 텍스트로 변환한다.
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _sanitize_markdown_links(text: str) -> str:
    def _replace_bad_link(match):
        label = match.group(1)
        url = match.group(2).strip()
        # http:// 또는 https:// 로 시작하고, 도메인에 .이 포함된 경우만 유효
        if re.match(r'^https?://[^\s]+\.[^\s]+', url):
            return match.group(0)  # 유효한 링크는 그대로
        return label  # 유효하지 않으면 라벨 텍스트만 반환
    return re.sub(r'\[([^\]]*)\]\(([^)]*)\)', _replace_bad_link, text)


_HALLUCINATED_URL_RE = re.compile(
    r'\[([^\]]*)\]\(https?://(?:example\.com|placeholder|dummy|fake|localhost)[^\)]*\)',
)
_MARKDOWN_URL_RE = re.compile(
    r'\[([^\]]*출처[^\]]*|[^\]]*)\]\(https?://[^\)]+\)',
)


def _strip_hallucinated_urls(answer: str, verified_urls: set) -> str:
    """LLM이 만든 가짜 URL을 제거. verified_urls는 도구가 반환한 실제 URL 집합."""
    if not answer or ("http://" not in answer and "https://" not in answer):
        return answer

    # 1단계: example.com 등 명백한 가짜 도메인 제거
    answer = _HALLUCINATED_URL_RE.sub(r'\1', answer)

    # 2단계: 모든 마크다운 링크를 검증된 URL과 대조
    def _check_url(match):
        full = match.group(0)
        url_match = re.search(r'\((https?://[^\)]+)\)', full)
        if url_match:
            url = url_match.group(1)
            # verified_urls가 있으면 도메인 일치 여부로 판단
            if verified_urls:
                for verified in verified_urls:
                    if url.split('/')[2] == verified.split('/')[2]:
                        return full  # 검증된 URL → 유지
            # verified_urls가 비어있으면 = 도구 호출 없이 LLM이 생성한 URL → 제거
        # 링크 텍스트만 남기고 URL 제거
        return match.group(1)
    answer = _MARKDOWN_URL_RE.sub(_check_url, answer)

    return answer


def _append_source_urls(answer: str, sources: list) -> str:
    if not sources:
        return answer
    # 답변에 이미 검증된 URL이 포함되어 있으면 추가하지 않음
    source_urls = {s.get("url", "") for s in sources if s.get("url")}
    if source_urls and any(url in answer for url in source_urls):
        return answer
    lines = [f"- [{s['title']}]({s['url']})" for s in sources]
    return answer.rstrip() + "\n\n**출처:**\n" + "\n".join(lines)


# ============================================================
# 사용된 도구 목록으로 응답 유형 결정.
# ============================================================
def _determine_response_type(tools_used: List[str]) -> str:
    if "search_web" in tools_used or "fetch_url_content" in tools_used:
        return "web_search"
    if "get_farm_realtime_data" in tools_used:
        return "farm_data"
    if "search_farm_knowledge" in tools_used:
        return "knowledge"
    return "general"


# ============================================================
# 구조화된 응답 결과 생성.
# ============================================================
def _build_structured_result(
    response_text: str,
    sources: list,
    tools_used: list,
) -> Dict[str, Any]:
    # LLM 답변 또는 _append_source_urls()가 이미 텍스트에 출처를 포함한 경우 메타데이터 sources를 비움 (프론트엔드 중복 표시 방지)
    if response_text and ("**출처:**" in response_text or "출처 링크" in response_text):
        return {
            "response": response_text,
            "sources": [],
            "tools_used": tools_used if tools_used else [],
            "response_type": _determine_response_type(tools_used),
        }

    # LLM이 실제 인용한 출처만 필터 (답변에 URL이 포함된 출처만 유지)
    cited_sources = sources
    if sources and response_text and ("http://" in response_text or "https://" in response_text):
        cited_sources = [s for s in sources if s.get("url") and s["url"] in response_text]
        if not cited_sources:
            cited_sources = sources  # 안전장치: 매칭 실패 시 원본 유지

    return {
        "response": response_text,
        "sources": cited_sources if cited_sources else [],
        "tools_used": tools_used if tools_used else [],
        "response_type": _determine_response_type(tools_used),
    }


# 인사/잡담 턴 판별용 패턴 (짧고 인사 키워드만 있는 메시지)
_GREETING_RE = re.compile(
    r"^(안녕|반가|잘\s*지내|하이|헬로|좋은\s*(아침|저녁|하루)|수고|얀녕|고마워|감사)",
)


# ============================================================
# 인사/잡담만으로 구성된 턴 쌍(user+assistant)을 제외한다.
# ============================================================
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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# 농장 기본 정보 텍스트 생성
# DB에서 농장/재배사 정보를 조회하여 system prompt에 삽입할 텍스트 생성
# Returns: str | None: 농장 정보 텍스트
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
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


def get_llm_response_with_tools(
    user_query: str,
    farm_name: str = None,
    temperature: float = 0.5,
    max_tool_iterations: int = 8,
    default_tool_args: Optional[Dict[str, Dict[str, Any]]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use를 지원하는 LLM 응답 생성
# LLM이 필요한 도구를 자동으로 선택하고 호출하여 최종 답변 생성
# Args: user_query: 사용자 질문
#       farm_name: 농장명
#       temperature: 창의성 정도
#       max_tool_iterations: 최대 도구 호출 반복 횟수
#       default_tool_args: 도구별 기본 인자
#       conversation_history: 이전 대화 히스토리 (멀티턴)
# Returns: dict: 구조화된 응답 {response, sources, tools_used, response_type}
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
) -> Dict[str, Any]:
    try:
        from agri_ai_core.src.ai.tools_definition import get_available_tools, get_system_prompt_with_tools
        from agri_ai_core.src.ai.tools_executor import execute_tool

        model_name = _get_model_name()
        tools = get_available_tools()

        # 농장명이 있으면 농장 시스템 프롬프트, 없으면 일반 프롬프트
        if farm_name:
            farm_info = _build_farm_info_text()
            system_prompt = get_system_prompt_with_tools(farm_name, farm_info)
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
            # system 메시지(관련 과거 대화)와 실제 턴 분리
            system_context = [t for t in conversation_history if t.get("role") == "system"]
            actual_turns = [t for t in conversation_history if t.get("role") != "system"]

            # 실제 턴에서 인사/잡담 필터링
            filtered_turns = _filter_greeting_turns(actual_turns)
            skipped = len(actual_turns) - len(filtered_turns)

            # 관련 과거 대화 주입 (system role, 800자 제한)
            for ctx in system_context:
                content = ctx.get("content", "")
                if len(content) > 800:
                    content = content[:800] + "..."
                messages.append({"role": "system", "content": content})

            # 최근 턴 주입 (user/assistant, 500자 제한)
            # 빈/실패 assistant 메시지는 LLM이 패턴을 따라 동일 응답을 반복하므로 제거
            for turn in filtered_turns:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role == "assistant" and not content.strip():
                    continue
                # "확인이 필요합니다" 등 실패 패턴만 있는 짧은 assistant 응답 제거
                if role == "assistant" and len(content.strip()) < 30:
                    _stripped = content.strip().rstrip(".")
                    if _stripped in ("확인이 필요합니다", "확인이 필요해요", "정보가 없습니다"):
                        continue
                if len(content) > 500:
                    content = content[:500] + "..."
                messages.append({"role": role, "content": content})

            logger.info(
                f"[멀티턴] 하이브리드 컨텍스트: 관련대화={len(system_context)}건, "
                f"최근턴={len(filtered_turns)}턴 (인사/잡담 {skipped}턴 제외, messages={len(messages)}개)"
            )

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
        _control_retry_count = 0  # 제어 재시도 횟수 (무한 루프 방지)
        _empty_response_count = 0  # 빈 응답 연속 횟수
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] --- 반복 {iteration + 1}/{max_tool_iterations} ---")

            # LLM 호출
            # 이전 반복에서 도구 호출이 있었으면 → 다음에도 도구 제공 (다단계 호출 지원)
            # 이전 반복에서 도구 호출이 없었으면 → 도구 제거 (최종 답변 생성)
            if _prev_had_tool_calls:
                iter_num_predict = 768 if iteration == 0 else min(NUM_PREDICT, 2048)
                iter_tools = tools
            else:
                iter_num_predict = min(NUM_PREDICT, 2048)
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
                    "think": False,
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
                    f"답변길이={len(final_answer)}자"
                )
                logger.debug(
                    f"[PERF:대화] ToolUse루프-LLM호출={iter_elapsed:.1f}s, "
                    f"ToolUse루프-전체={_tooluse_total_s:.1f}s (반복{iteration + 1})"
                )

                # 빈 응답 감지 (qwen3 thinking 모드에서 content="" 반환하는 경우)
                if not final_answer.strip():
                    _empty_response_count += 1
                    if _empty_response_count <= 1 and iteration < max_tool_iterations - 1:
                        logger.warning(
                            f"[Tool Use] 빈 응답 감지 (반복{iteration + 1}) → 도구 호출 재시도 "
                            f"(빈응답횟수={_empty_response_count})"
                        )
                        # 빈 응답 메시지 제거 후 도구 호출 유도
                        messages.pop()  # 빈 assistant 메시지 제거
                        messages.append({
                            "role": "user",
                            "content": (
                                "도구를 호출하여 요청을 처리하세요. "
                                "반드시 적절한 도구를 선택하고 호출해야 합니다."
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

                _t_final = time.time()
                finalized = _finalize_user_facing_answer(
                    model_name=model_name,
                    user_query=user_query,
                    farm_name=farm_name,
                    raw_answer=final_answer,
                )
                _final_s = time.time() - _t_final
                logger.debug(f"[PERF:대화] 후처리(_finalize)={_final_s:.1f}s")

                # 제어 키워드 검증: 제어 요청인데 control_relay가 호출되지 않은 경우
                _control_keywords = ("제어", "켜", "끄", "중지", "가동", "작동", "동작", "정지", "on", "off")
                # 파일/문서 관련 질문에서 제어 키워드가 파일명에 포함된 경우 오탐 방지
                _file_context_keywords = ("파일", "학습", "요약", "내용", "문서", ".csv", ".txt", ".pdf", ".xlsx")
                _is_file_query = any(fk in user_query for fk in _file_context_keywords)
                _control_tools = {"control_relay"}
                _has_control_intent = (
                    any(kw in user_query for kw in _control_keywords)
                    and not _is_file_query
                )
                _control_not_called = _has_control_intent and not _control_tools.intersection(_tools_used)

                # 제어 미호출 + 아직 반복 여유 있고 + 재시도 2회 미만이면 → 재시도 지시
                if _control_not_called and iteration < max_tool_iterations - 2 and _control_retry_count < 2:
                    _control_retry_count += 1
                    logger.warning(
                        f"[Tool Use] 제어 키워드 감지({user_query[:50]}...) "
                        f"그러나 control_relay 미호출 → 재시도 지시 (반복{iteration + 1}, "
                        f"재시도횟수={_control_retry_count}/2)"
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            "위 답변에서 장치 제어를 수행했다고 했지만, 실제로 control_relay 도구가 호출되지 않았습니다. "
                            "반드시 control_relay 또는 control_relays_batch 도구를 호출하여 실제로 장치를 제어하세요. "
                            "도구를 호출하지 않고 제어했다고 답변하는 것은 금지입니다."
                        ),
                    })
                    _prev_had_tool_calls = True  # 다음 반복에서 도구 제공
                    continue
                elif _control_not_called:
                    logger.warning(
                        f"[Tool Use] 제어 키워드 감지({user_query[:50]}...) "
                        f"그러나 control_relay 미호출 → 할루시네이션 가능성 "
                        f"(재시도 한도 초과: {_control_retry_count}회)"
                    )

                _verified_urls = {s.get("url", "") for s in _collected_sources if s.get("url")}
                finalized = _strip_hallucinated_urls(finalized, _verified_urls)
                text_with_sources = _append_source_urls(finalized, _collected_sources)
                return _build_structured_result(text_with_sources, _collected_sources, _tools_used)

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

                # 도구 사용 추적
                if tool_name not in _tools_used:
                    _tools_used.append(tool_name)

                # 도구 실행
                t_tool = time.time()
                tool_result = execute_tool(tool_name, tool_args)
                tool_elapsed = time.time() - t_tool
                result_len = len(tool_result or "")
                logger.info(f"[도구결과] [{tc_idx}/{len(tool_calls)}] {tool_name} ({tool_elapsed:.1f}s) 결과길이={result_len}자")
                logger.info(f"[도구결과데이터] {tool_name}:\n{tool_result}")

                # 도구 결과에서 출처 수집 (정제 전 원본 JSON에서 파싱)
                if tool_result:
                    try:
                        parsed_result = json.loads(tool_result)
                        if tool_name == "search_web":
                            for item in parsed_result.get("results", []):
                                title = (item.get("title") or "").strip()
                                url = (item.get("url") or "").strip()
                                if title and url:
                                    _collected_sources.append({"title": title, "url": url})
                        elif tool_name == "search_farm_knowledge":
                            for item in parsed_result.get("results", []):
                                meta = item.get("metadata", {})
                                src = (meta.get("source") or meta.get("title") or "").strip()
                                url = (meta.get("url") or "").strip()
                                if src and url:
                                    _collected_sources.append({"title": src, "url": url})
                    except (json.JSONDecodeError, TypeError):
                        pass

                # 도구 결과를 정제 후 메시지에 추가
                refined_result = _refine_tool_result(tool_name, tool_result, user_query)
                logger.info(
                    f"[도구정제] {tool_name} 원본={len(tool_result or '')}자 → 정제={len(refined_result)}자"
                )
                messages.append({
                    "role": "tool",
                    "content": refined_result
                })

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
                text_with_sources = _append_source_urls(finalized, _collected_sources)
                return _build_structured_result(text_with_sources, _collected_sources, _tools_used)
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
                    text_with_sources = _append_source_urls(finalized, _collected_sources)
                    return _build_structured_result(text_with_sources, _collected_sources, _tools_used)

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
