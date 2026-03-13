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
# _extract_tool_calls: Ollama 응답에서 도구 호출 추출 (tool_calls 필드 우선, content에 JSON 도구 호출이 텍스트로 출력된 경우도 파싱)
# _extract_tool_name: 도구 호출에서 도구명 추출
# _extract_tool_arguments: 도구 호출에서 인자 추출
# _normalize_tool_arguments: 도구 인자 정규화
# _get_available_models: Ollama에서 사용 가능한 모델 목록 가져오기
# _get_model_name: 환경 설정에서 모델명을 가져오거나 기본값을 반환
# _perform_llm_warmup: LLM 워밍업 수행
# initialize_background_warmup: 백그라운드 워밍업 초기화
# _emit_question_log_once: 질문 로그 1회 출력
# _clean_page_content: 페이지 본문에서 노이즈 제거 후 도입부 추출
# _refine_search_web: search_web 결과를 구조적으로 정제 + LLM이 보는 결과와 동일한 출처 목록 반환 (tuple: 정제텍스트, 출처리스트)
# _refine_fetch_url: fetch_url_content 결과를 구조적으로 정제
# _refine_farm_knowledge: search_farm_knowledge 결과를 경량화 (개별 content 500자 + 전체 1500자 제한, num_ctx 포화 방지). 메타 질문(파일/학습/목록) 시 file_list 보존하여 LLM이 학습 자료 리스트 답변 가능
# _refine_realtime_data: get_farm_realtime_data 결과를 컴팩트 텍스트로 변환 (센서+릴레이+적정범위+AI알고리즘권장 포함)
# _refine_tool_result: 도구 결과를 LLM 메시지에 넣기 전에 도구별 지능형 정제
# 도구 호출 중복 제거: 같은 반복 내 동일 함수+동일 인자 호출은 캐시 사용하여 1번만 실행 (num_ctx 낭비 방지)
# _finalize_user_facing_answer: 최종 사용자 응답 생성 (think 태그 제거 + 기본 정리)
# _align_markdown_tables: LLM 응답 내 마크다운 표의 컬럼 구분자(|)를 정렬 (한글 너비 고려)
# clean_llm_response: LLM 응답 기본 정리 + 표 정렬
# _determine_response_type: 사용된 도구 목록으로 응답 유형 결정.
# _build_structured_result: 구조화된 응답 결과 생성 (출처 URL 중복 제거 포함).
# _filter_greeting_turns: 인사/잡담만으로 구성된 턴 쌍(user+assistant)을 제외한다.
# get_llm_response_with_tools 내 턴 주입: 이전 대화를 system role 대화 연속성 참고용 맥락으로 주입 (user/assistant role 직접 주입 시 LLM이 이전 질문도 답변하는 오염 방지). "그럼/그래서/또" 등 연결어 시 맥락 이어가기 허용. 중복 user 턴 제거 시 대응 assistant 턴도 함께 제거. 유사 assistant 답변 중복 제거: 앞 150자 기준 80% 이상 유사하면 이전 Q&A 제거하고 최신만 유지. 파일 목록 포함 답변 또는 "N번" 참조 질문 시 assistant truncation 800자로 확대. 릴레이 제어 맥락 경고: 이전 대화에 릴레이 제어 답변이 있어도 새 요청 시 반드시 control_relay 도구 재호출 필수.
# get_llm_response_with_tools 내 출처 수집: _refine_search_web 정제 후 LLM이 보는 결과와 동일한 출처만 수집 (별도 키워드 필터 없음)
# _coerce_numeric_id: LLM이 비정수 값을 ID로 넣는 경우 기본값(정수)으로 교정
# get_llm_response_with_tools: Tool Use 지원 LLM 응답 생성 (LLM이 도구 자율 선택, 1차 반복 토큰한도 도달 시 도구 호출 강제 재시도, JSON 텍스트/짧은 대기문구 답변 감지 시 자연어 재생성 유도, 릴레이 제어 답변인데 control_relay 미호출 시 강제 재시도)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import re
import time
import json
import threading
import traceback
import unicodedata
from typing import Any, Dict, List, Optional
from queue import Queue as ThreadQueue
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import ollama
except Exception:
    ollama = None

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import settings, NUM_PREDICT, NUM_CTX, get_ollama_url, get_model_name
from agri_ai_core.src.utils.validators import is_true
from agri_ai_core.src.ai.utils import GREETING_RE as _GREETING_RE

logger = setup_logger(__name__)

# 도구 한국어 표시명 매핑
_TOOL_DISPLAY_NAMES = {
    "get_farm_realtime_data": "센서/릴레이 데이터 조회",
    "search_farm_knowledge": "농장 지식 검색",
    "search_web": "웹 검색",
    "fetch_url_content": "웹페이지 내용 수집",
    "control_relay": "장치 제어",
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
# 출처 목록은 LLM이 보는 결과와 동일하게 구성 (별도 키워드 필터 없음).
# Returns: tuple(정제된 텍스트, 출처 리스트[{title, url}])
# ============================================================
def _refine_search_web(tool_result: str, user_query: str) -> tuple:
    empty_sources = []
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result, empty_sources

    results = data.get("results", [])
    if not results:
        return tool_result, empty_sources

    selected_results = results[:_SEARCH_WEB_REFINE_MAX_RESULTS]

    # 출처 목록 = LLM이 보는 selected_results와 동일 (별도 키워드 필터 없음)
    filtered_sources = []
    for item in selected_results:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if title and url:
            filtered_sources.append({"title": title, "url": url})

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
        "지시: 위 검색 결과를 종합하여 사용자의 원래 질문에 정확히 맞는 답변을 작성하세요. "
        "사용자가 'N곳/N개' 등 구체적 개수를 요청했다면 반드시 해당 개수만큼 번호를 매겨 리스트로 답변하세요. "
        "검색 결과에서 핵심 수치, 날짜, 사실 정보를 추출하여 답변에 반드시 포함하세요."
    )

    refined_text = "\n".join(lines)
    if len(refined_text) > _SEARCH_WEB_REFINE_TOTAL_CHARS:
        refined_text = refined_text[:_SEARCH_WEB_REFINE_TOTAL_CHARS].rstrip() + "\n...(중략)..."
    return refined_text, filtered_sources


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
    ~1.5KB JSON → 압축하여 LLM 컨텍스트 절감.
    - 조회시각 생략 (모든 재배사 동일하므로 중복 제거)
    - OFF 장치 목록 생략 (ON만 표시, 나머지는 OFF로 추론 가능)
    - environment_thresholds: 환경 제어 임계값 (적정 범위) 보존
    - ai_environment_judgment: AI 알고리즘 권장 릴레이 상태 보존
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

    # 환경 제어 임계값 (적정 범위) — LLM이 센서값 적정 여부 판단에 필수
    # ※ 적정범위는 모든 재배사 공통이므로 병합 시 중복 제거 가능하도록 고정 접두어 사용
    thresholds = data.get("environment_thresholds")
    if thresholds and isinstance(thresholds, dict):
        th_items = []
        for key, th in thresholds.items():
            if isinstance(th, dict):
                label = _SENSOR_SHORT.get(key, key)
                unit = th.get("unit", "")
                th_items.append(f"{label}: 적정{th.get('low','')}{unit}~{th.get('high','')}{unit}, 비상저{th.get('critical_low','')}{unit}/비상고{th.get('critical_high','')}{unit}")
        if th_items:
            parts.append("적정범위(공통): " + ", ".join(th_items))

    # 릴레이 데이터 압축 (relay_mapping 사용 → ON/OFF 장치명)
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
        on_pins = [k for k, v in data["relay"].items()
                   if k.startswith("relay_") and k.endswith("_flag") and v]
        off_pins = [k for k, v in data["relay"].items()
                    if k.startswith("relay_") and k.endswith("_flag") and not v]
        if on_pins:
            parts.append(f"ON: {', '.join(on_pins)}")
        if off_pins:
            parts.append(f"OFF: {', '.join(off_pins)}")

    # AI 환경 판단 (알고리즘 권장 릴레이 상태) — 제어값 비교용
    ai_judgment = data.get("ai_environment_judgment")
    if ai_judgment and isinstance(ai_judgment, dict):
        reason = ai_judgment.get("reason", "")
        device_summary = ai_judgment.get("device_summary", "")
        circulation = ai_judgment.get("circulation", "")
        judge_parts = []
        if reason:
            judge_parts.append(f"판단: {reason}")
        if device_summary:
            judge_parts.append(f"권장장치: {device_summary}")
        if circulation:
            judge_parts.append(f"순환모드: {circulation}")
        if judge_parts:
            parts.append("AI알고리즘권장: " + ", ".join(judge_parts))

    return " | ".join(parts)


# ============================================================
# 도구 결과를 LLM 메시지에 넣기 전에 도구별 지능형 정제를 수행한다.
# ============================================================
def _refine_tool_result(tool_name: str, tool_result: str, user_query: str) -> str:
    if not tool_result:
        return tool_result or ""
    if tool_name == "search_web":
        refined_text, _ = _refine_search_web(tool_result, user_query)
        return refined_text
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
    - content 개별 항목 500자 제한 + 전체 결과 1500자 제한 (num_ctx 포화 방지)
    기존: 정제 후에도 ~5800자/건 → 다중 호출 시 num_ctx 초과로 다른 도구 결과 누락
    변경: 핵심 내용만 보존하여 1500자 이내로 제한, 다른 도구 결과와 공존 가능
    """
    _MAX_CONTENT_PER_ITEM = 500   # 개별 항목 content 최대 길이
    _MAX_TOTAL_REFINED = 1500     # 정제 결과 전체 최대 길이

    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result[:_MAX_TOTAL_REFINED] if len(tool_result or "") > _MAX_TOTAL_REFINED else (tool_result or "")

    results = data.get("results")
    if not results or not isinstance(results, list):
        return tool_result[:_MAX_TOTAL_REFINED] if len(tool_result or "") > _MAX_TOTAL_REFINED else (tool_result or "")

    for item in results:
        # 1) 네비게이션 잡음 제거
        content = item.get("content", "")
        if content:
            content = _strip_nav_noise(content)
            # 2) 개별 content 길이 제한
            if len(content) > _MAX_CONTENT_PER_ITEM:
                content = content[:_MAX_CONTENT_PER_ITEM] + "..."
            item["content"] = content

        # 3) description이 content와 중복이면 제거
        meta = item.get("metadata", {})
        desc = meta.get("description", "")
        if desc and content and desc[:50] in content:
            del meta["description"]

        # 4) 불필요한 metadata 키 제거
        for key in _UNNECESSARY_META_KEYS:
            meta.pop(key, None)

    # [FIX] file_list가 있으면 (메타 질문: 학습/파일/목록 등) 파일 목록을 우선 포함
    # → LLM이 학습 자료 리스트를 답변할 수 있도록 file_list 정보를 보존
    _file_list = data.get("file_list")
    if _file_list and isinstance(_file_list, list):
        _file_summary = "학습된 파일 목록:\n"
        for idx, f in enumerate(_file_list, 1):
            fn = f.get("file_name", "")
            dt = f.get("document_type", "")
            col = f.get("collection", "")
            _file_summary += f"{idx}. {fn} (유형: {dt}, 출처: {col})\n"
        # file_list가 있으면 파일 목록 + 축약된 결과를 합산
        refined = json.dumps(data, ensure_ascii=False)
        if len(refined) > _MAX_TOTAL_REFINED:
            # 파일 목록은 보존하고 results만 축약
            data["results"] = data.get("results", [])[:2]
            for item in data.get("results", []):
                c = item.get("content", "")
                if len(c) > 200:
                    item["content"] = c[:200] + "..."
            refined = json.dumps(data, ensure_ascii=False)
        return refined

    refined = json.dumps(data, ensure_ascii=False)
    # 전체 결과 길이 제한 (num_ctx 포화 방지)
    if len(refined) > _MAX_TOTAL_REFINED:
        refined = refined[:_MAX_TOTAL_REFINED] + "..."
    return refined


def _finalize_user_facing_answer(
    model_name: str,
    user_query: str,
    farm_name: Optional[str],
    raw_answer: str,
) -> str:
    """LLM 응답 후처리: think 태그 제거 + 기본 포맷 정리만 수행."""
    logger.info(f"[필터링전-원본] len={len(raw_answer or '')}자")
    logger.info(f"[필터링전-원본내용]\n{raw_answer}")

    candidate = clean_llm_response(raw_answer)

    diff = len(raw_answer or '') - len(candidate)
    logger.info(f"[필터링완료] {len(raw_answer or '')}자→{len(candidate)}자 ({diff}자 삭제)")
    logger.info(f"[최종답변내용]\n{candidate}")
    return candidate



# ============================================================
# 마크다운 표 정렬 유틸리티 (한글 너비 고려)
# ============================================================
def _display_width(text: str) -> int:
    """문자열의 터미널 표시 너비를 계산한다 (한글=2, 영문=1)."""
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ('W', 'F') else 1
    return width


def _pad_to_width(text: str, target_width: int) -> str:
    """문자열을 target_width 너비로 패딩한다."""
    current = _display_width(text)
    pad = target_width - current
    return text + (' ' * max(0, pad))


# ============================================================
# LLM 응답 내 마크다운 표의 컬럼 구분자(|)를 정렬한다 (한글 너비 고려).
# ============================================================
def _align_markdown_tables(text: str) -> str:
    """텍스트 내 모든 마크다운 표의 | 구분자 위치를 정렬한다."""
    if '|' not in text:
        return text

    lines = text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        if lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                table_lines.append(lines[i])
                i += 1

            if len(table_lines) < 2:
                result.extend(table_lines)
                continue

            parsed_rows = []
            separator_indices = []
            for row_idx, row in enumerate(table_lines):
                stripped = row.strip()
                inner = stripped[1:-1] if stripped.startswith('|') and stripped.endswith('|') else stripped
                cells = [c.strip() for c in inner.split('|')]

                is_sep = all(re.match(r'^:?-+:?$', c) for c in cells if c)
                if is_sep:
                    separator_indices.append(row_idx)

                parsed_rows.append(cells)

            if not parsed_rows:
                result.extend(table_lines)
                continue

            max_cols = max(len(row) for row in parsed_rows)
            for row in parsed_rows:
                while len(row) < max_cols:
                    row.append('')

            col_widths = [0] * max_cols
            for row_idx, row in enumerate(parsed_rows):
                if row_idx in separator_indices:
                    continue
                for col_idx, cell in enumerate(row):
                    w = _display_width(cell)
                    if w > col_widths[col_idx]:
                        col_widths[col_idx] = w

            col_widths = [max(w, 3) for w in col_widths]

            for row_idx, row in enumerate(parsed_rows):
                if row_idx in separator_indices:
                    sep_cells = ['-' * col_widths[c] for c in range(max_cols)]
                    result.append('| ' + ' | '.join(sep_cells) + ' |')
                else:
                    padded_cells = [_pad_to_width(row[c], col_widths[c]) for c in range(max_cols)]
                    result.append('| ' + ' | '.join(padded_cells) + ' |')
        else:
            result.append(lines[i])
            i += 1

    return '\n'.join(result)


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
    """LLM 응답 기본 정리: Think 태그 제거, 마크다운 헤더/코드블록 제거, 빈 줄 정리, 표 정렬."""
    if not response_text:
        return response_text

    original_text = response_text
    original_length = len(response_text)

    # 1. Think 태그 제거
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<thinking>.*?</thinking>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<think>.*', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'<thinking>.*', '', response_text, flags=re.DOTALL | re.IGNORECASE)
    response_text = re.sub(r'</?think[^>]*>', '', response_text, flags=re.IGNORECASE)
    response_text = re.sub(r'<meta[^>]*>', '', response_text, flags=re.IGNORECASE)

    # 2. 마크다운 헤더 제거
    for hdr in (r"^(### )?Final Answer:?\s*", r"^(### )?Final Output:?\s*",
                r"^(### )?Response:?\s*", r"^(### )?Answer:?\s*", r"^(### )?결론:?\s*"):
        response_text = re.sub(hdr, "", response_text, flags=re.MULTILINE | re.IGNORECASE)

    # 3. 코드 블록 마커 제거
    response_text = re.sub(r"^```[a-zA-Z]*\s*$", "", response_text, flags=re.MULTILINE)
    response_text = re.sub(r"^```\s*$", "", response_text, flags=re.MULTILINE)

    # 4. 출처/참고 섹션 제거 (LLM이 답변 끝에 출처를 붙이는 경우 — 시스템이 별도 표시)
    response_text = re.sub(
        r'\n+(?:#{1,4}\s*)?(?:\*{0,2})(?:출처(?:\s*링크)?|참고\s*(?:링크|자료|문헌)?|References?|Sources?)\s*[:：]?\s*(?:\*{0,2})\s*\n.*$',
        '', response_text, flags=re.DOTALL | re.IGNORECASE
    )

    # 5. 빈 줄 정리 + 다중 공백 축소
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = re.sub(r'[ \t]{2,}(?!\n)', ' ', response_text)
    response_text = response_text.strip()

    # 5-2. 최종 빈 줄 정리
    response_text = re.sub(r'(\n\s*){3,}', '\n\n', response_text)
    response_text = response_text.strip()

    # 6. 마크다운 표 정렬 (한글 너비 고려, | 위치 일치)
    response_text = _align_markdown_tables(response_text)

    # 7. 과도한 제거 검사 (90% 이상 제거 시 폴백)
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
    speech_style: str = None,
    progress_queue: Optional[ThreadQueue] = None,

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Tool Use를 지원하는 LLM 응답 생성
# LLM이 필요한 도구를 자동으로 선택하고 호출하여 최종 답변 생성
# Args: user_query: 사용자 질문
#       farm_name: 농장명
#       temperature: 창의성 정도
#       max_tool_iterations: 최대 도구 호출 반복 횟수
#       default_tool_args: 도구별 기본 인자
#       conversation_history: 이전 대화 히스토리 (멀티턴)
#       speech_style: 대화체 (male/female)
#       progress_queue: 진행 상태 이벤트 큐 (스트리밍용, thread-safe)
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
            # system 메시지(관련 과거 대화)와 실제 턴 분리
            system_context = [t for t in conversation_history if t.get("role") == "system"]
            actual_turns = [t for t in conversation_history if t.get("role") != "system"]

            # 실제 턴에서 인사/잡담 필터링
            filtered_turns = _filter_greeting_turns(actual_turns)
            skipped = len(actual_turns) - len(filtered_turns)

            # 관련 과거 대화 주입 (system role, 400자 제한, 참고용 명시)
            for ctx in system_context:
                content = ctx.get("content", "")
                if len(content) > 400:
                    content = content[:400] + "..."
                # LLM이 과거 대화를 현재 질문으로 혼동하지 않도록 명시적 구분
                formatted = f"[이전 대화 요약 - 참고용, 답변 근거로 사용 금지]\n{content}"
                messages.append({"role": "system", "content": formatted})

            # 최근 턴 주입 — system role로 참고용 맥락 주입
            # [FIX] 이전 대화를 user/assistant role로 넣으면 LLM이 이전 질문도 함께 답변하려 함
            # → 하나의 system 메시지로 묶어 "참고용 맥락"으로만 전달하여 데이터 오염 방지
            # [FIX] 유사 assistant 답변 중복 제거: 연속 대화에서 비슷한 답변이 반복 주입되는 문제 해결
            _user_query_stripped = (user_query or "").strip()
            # [FIX] 현재 질문에 "N번" 참조가 있으면 이전 답변의 목록을 보존해야 함
            _user_refs_number = bool(re.search(r'\d+번', _user_query_stripped))
            _context_parts = []
            _skip_next_assistant = False
            _prev_assistant_prefix = ""  # 직전 assistant 답변의 앞부분 (유사도 비교용)
            _dedup_count = 0  # 유사 중복으로 제거된 턴 수
            for turn in filtered_turns:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role == "assistant" and not content.strip():
                    _skip_next_assistant = False
                    continue
                # "확인이 필요합니다" 등 실패 패턴만 있는 짧은 assistant 응답 제거
                if role == "assistant" and len(content.strip()) < 30:
                    _stripped = content.strip().rstrip(".")
                    if _stripped in ("확인이 필요합니다", "확인이 필요해요", "정보가 없습니다"):
                        _skip_next_assistant = False
                        continue
                # [FIX] 중복 user 턴 제거 후 대응 assistant 턴도 함께 스킵
                if _skip_next_assistant and role == "assistant":
                    _skip_next_assistant = False
                    continue
                # 현재 질문과 동일한 과거 user 턴 제거 (중복 컨텍스트 방지)
                if role == "user" and content.strip() == _user_query_stripped:
                    _skip_next_assistant = True
                    continue
                # [FIX] 직전 대화 내 연속 동일 user 질문 제거 (도구 실패 재시도 시 같은 질문 2회 저장되는 경우)
                if role == "user" and _context_parts:
                    _last_user_part = None
                    for _cp in reversed(_context_parts):
                        if _cp.startswith("사용자: "):
                            _last_user_part = _cp[5:]  # "사용자: " 이후
                            break
                    if _last_user_part and _last_user_part.strip()[:60] == content.strip()[:60]:
                        _skip_next_assistant = True
                        _dedup_count += 1
                        logger.info(f"[멀티턴] 직전 대화 내 동일 질문 반복 제거: '{content.strip()[:40]}...'")
                        continue
                _skip_next_assistant = False
                # [FIX] 유사 assistant 답변 중복 제거: 이전 답변과 앞 150자가 80% 이상 겹치면
                # 이전 Q&A를 제거하고 최신 것만 유지 (연속 유사 질문 시 컨텍스트 낭비 방지)
                if role == "assistant" and len(content) > 80:
                    _current_prefix = content.strip()[:150]
                    if _prev_assistant_prefix and _current_prefix and _prev_assistant_prefix:
                        _common = sum(1 for a, b in zip(_prev_assistant_prefix, _current_prefix) if a == b)
                        _max_len = max(len(_prev_assistant_prefix), len(_current_prefix))
                        if _max_len > 0 and _common / _max_len > 0.8:
                            # 이전 user+assistant 쌍 제거, 현재(최신) 것만 유지
                            if len(_context_parts) >= 2:
                                _context_parts.pop()  # 이전 AI 답변 제거
                                _context_parts.pop()  # 이전 사용자 질문 제거
                                _dedup_count += 1
                                logger.info(f"[멀티턴] 유사 답변 중복 제거: 이전 Q&A 제거 (유사도={_common}/{_max_len})")
                            elif len(_context_parts) >= 1:
                                _context_parts.pop()  # 이전 AI 답변만 제거
                                _dedup_count += 1
                    _prev_assistant_prefix = _current_prefix
                # 길이 제한 (참고용이므로 핵심 주제만 보존)
                # [FIX] 파일 목록/번호가 포함된 답변은 800자까지 확대 (사용자가 "N번" 참조 시 필요)
                if role == "assistant":
                    # [FIX] 릴레이 제어 결과 답변 축약: LLM이 이전 제어 답변을 복사하여
                    # 도구 없이 거짓 응답하는 문제 방지. 상세 데이터를 제거하여
                    # LLM이 반드시 control_relay 도구를 호출하도록 유도
                    _relay_result_indicators = ("릴레이", "AI 환경 판단", "AI 권장", "반대로")
                    _relay_done_indicators = ("설정했어요", "변경했어요", "제어했어요", "반전했어요", "전환했어요",
                                              "설정했습니다", "변경했습니다", "제어했습니다")
                    _is_relay_result = (
                        any(ind in content for ind in _relay_result_indicators)
                        and any(ind in content for ind in _relay_done_indicators)
                    )
                    if _is_relay_result:
                        # 릴레이 제어 답변은 첫 줄만 보존 (상세 표/데이터 제거)
                        _first_line = content.split("\n")[0][:80]
                        content = f"{_first_line} (상세 생략 — 새 요청 시 control_relay 도구 호출 필수)"
                    else:
                        # 파일 목록 패턴 감지: "1. file.pdf" 또는 "| 1 | file.pdf |" 형식
                        _has_numbered_list = bool(
                            re.search(r'\d+[\.\)]\s*\*{0,2}\S+\.(pdf|txt|csv|json|md)', content)
                            or re.search(r'\|\s*\d+\s*\|.*\.(pdf|txt|csv|json|md)', content)
                        )
                        # "N번" 참조 질문 시 목록 보존을 위해 추가 확대
                        _max_assistant = 800 if (_has_numbered_list or _user_refs_number) else 350
                        if len(content) > _max_assistant:
                            content = content[:_max_assistant] + "..."
                elif role == "user" and len(content) > 400:
                    content = content[:400] + "..."
                label = "사용자" if role == "user" else "AI"
                _context_parts.append(f"{label}: {content}")
            if _dedup_count:
                logger.info(f"[멀티턴] 유사 답변 중복 {_dedup_count}건 제거 완료")

            if _context_parts:
                _prev_context = "\n".join(_context_parts)
                messages.append({
                    "role": "system",
                    "content": (
                        "[직전 대화 맥락 - 대화 연속성 참고용]\n"
                        "아래는 직전 대화예요. 현재 질문이 직전 대화와 자연스럽게 이어지는 경우(예: '그럼', '그래서', '또', '다른') 맥락을 이어서 답변하세요.\n"
                        "중요: 이 맥락은 참고용이며, 파일/학습/자료/문서/데이터 관련 질문에는 반드시 search_farm_knowledge 도구를 사용하세요.\n"
                        "이전 대화에서 비슷한 답변이 있더라도, 도구를 다시 호출하여 최신 정보를 검색하세요.\n"
                        "이전 답변을 그대로 복사하거나 반복하는 것은 금지합니다.\n"
                        "**장치 제어/릴레이 제어 관련 (절대 규칙)**: 이전 대화에서 릴레이 제어 성공 답변이 있더라도, 사용자가 다시 제어를 요청하면 반드시 control_relay 도구를 새로 호출하세요. 이전 제어 결과를 복사하여 도구 없이 답변하면 실제 하드웨어가 제어되지 않습니다.\n"
                        f"{_prev_context}"
                    )
                })

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
        _empty_response_count = 0  # 빈 응답 연속 횟수
        for iteration in range(max_tool_iterations):
            logger.info(f"[Tool Use] --- 반복 {iteration + 1}/{max_tool_iterations} ---")

            # 진행 상태 보고: LLM 호출 시작
            if iteration == 0:
                _report_progress(progress_queue, "질문을 분석하고 필요한 정보를 파악하고 있습니다...", "llm_analyzing",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)
            else:
                _report_progress(progress_queue, "수집된 정보를 바탕으로 답변을 작성하고 있습니다...", "llm_generating",
                                 iteration=iteration + 1, max_iterations=max_tool_iterations)

            # LLM 호출
            # 이전 반복에서 도구 호출이 있었으면 → 다음에도 도구 제공 (다단계 호출 지원)
            # 이전 반복에서 도구 호출이 없었으면 → 도구 제거 (최종 답변 생성)
            if _prev_had_tool_calls:
                # 첫 반복은 도구 호출 전용 (보통 50~100토큰) → 384로 제한하여 생성 시간 절약
                iter_num_predict = 384 if iteration == 0 else NUM_PREDICT
                iter_tools = tools
            else:
                iter_num_predict = NUM_PREDICT
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
                    "num_ctx": NUM_CTX,
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

                # 1차 반복에서 도구 호출 없이 토큰 한도 도달 → 도구 사용 강제 재시도
                # LLM이 도구 대신 직접 답변을 생성하다 num_predict(384) 한도에 걸린 경우
                if iteration == 0 and _done_reason == "length" and iter_tools is not None:
                    # 릴레이 제어 키워드가 있으면 control_relay 도구를 명시적으로 안내
                    _relay_hint_keywords = ("반대로", "반전", "셋팅", "설정", "제어", "켜", "꺼", "가동", "중지")
                    _is_relay_hint = any(kw in user_query for kw in _relay_hint_keywords)
                    if _is_relay_hint:
                        _retry_msg = (
                            f"릴레이 제어 요청은 반드시 control_relay 도구를 호출해야 합니다. "
                            f"이전 대화의 답변을 복사하지 마세요. "
                            f"먼저 get_farm_realtime_data(data_type='relay', house_id='1')로 현재 상태를 확인하고, "
                            f"control_relay(house_id='1', mode='reverse_all')로 실제 제어를 수행하세요."
                        )
                    else:
                        _retry_msg = (
                            f"위 요청을 처리하려면 반드시 도구를 호출해야 합니다. "
                            f"직접 답변하지 말고 get_farm_realtime_data, search_farm_knowledge, "
                            f"search_web, control_relay 등 적절한 도구를 호출하세요."
                        )
                    logger.warning(
                        f"[Tool Use] 1차 반복 토큰한도 도달(done_reason=length) → 도구 호출 강제 재시도"
                        f"{' (릴레이 제어 감지)' if _is_relay_hint else ''}"
                    )
                    messages.pop()  # 잘린 assistant 메시지 제거
                    messages.append({"role": "user", "content": _retry_msg})
                    _prev_had_tool_calls = True
                    continue

                # 릴레이 제어 답변인데 도구를 사용하지 않은 경우 로깅 (모니터링 전용)
                # 컨텍스트 절삭(Change 4)으로 근본 원인은 해결됨 — 여기서는 감지·기록만 수행
                _stripped = final_answer.strip()
                _relay_done_phrases = ("설정했어요", "설정했습니다", "제어했어요", "제어했습니다", "완료했어요", "완료했습니다", "변경했어요", "변경했습니다", "반전했어요", "반전했습니다", "전환했어요", "전환했습니다")
                _has_relay_done = any(phrase in _stripped for phrase in _relay_done_phrases)
                if _has_relay_done and "control_relay" not in _tools_used:
                    logger.warning(
                        f"[Tool Use] 릴레이 제어 답변인데 control_relay 미호출 감지 (반복{iteration + 1}) — "
                        f"모니터링 기록 (강제 재시도 없음)"
                    )

                # JSON 형식 응답 감지: LLM이 도구 결과 JSON을 그대로 텍스트로 출력한 경우
                # 예: {"content": "[생육 RAG] ..."} 또는 {"success": true, ...}
                if _stripped.startswith("{") and _stripped.endswith("}") and iteration < max_tool_iterations - 1:
                    try:
                        _parsed_json = json.loads(_stripped)
                        if isinstance(_parsed_json, dict):
                            logger.warning(
                                f"[Tool Use] JSON 형식 응답 감지 (반복{iteration + 1}) → "
                                f"자연어 답변 재생성 유도 (키: {list(_parsed_json.keys())[:3]})"
                            )
                            messages.pop()  # JSON 응답 assistant 메시지 제거
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"도구 결과를 사용자에게 자연어로 설명해 주세요. "
                                    f"JSON 형식이 아닌 한국어 문장으로 답변하세요. "
                                    f"사용자의 원래 요청: \"{user_query}\""
                                ),
                            })
                            _prev_had_tool_calls = True
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass

                # 도구 호출 후 짧은 답변 감지: 도구 결과를 종합하지 않고 대기/예고 문구만 출력한 경우
                # 예: "재배차이점을 분석하기 전에 먼저 관련 지식을 검색해볼게요." (도구 결과가 이미 있는데 종합하지 않음)
                if (
                    _tools_used  # 도구를 1개 이상 호출한 상태
                    and len(_stripped) < 80  # 짧은 답변
                    and iteration < max_tool_iterations - 1
                    and not _stripped.startswith("|")  # 마크다운 표 시작이 아닌 경우
                ):
                    logger.warning(
                        f"[Tool Use] 도구 호출 후 짧은 답변 감지 (반복{iteration + 1}, {len(_stripped)}자) → "
                        f"도구 결과 기반 답변 재생성 유도: \"{_stripped[:40]}...\""
                    )
                    messages.pop()  # 짧은 assistant 메시지 제거
                    messages.append({
                        "role": "user",
                        "content": (
                            f"도구 검색 결과가 이미 제공되었습니다. 대기/예고 문구 없이 "
                            f"수집된 정보를 종합하여 사용자의 질문에 바로 답변하세요. "
                            f"정보가 부족하면 search_web으로 추가 검색하세요. "
                            f"사용자의 원래 요청: \"{user_query}\""
                        ),
                    })
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

            # 도구 호출 처리 (같은 반복의 결과는 병합하여 1개 메시지로 추가)
            # 동일 반복 내 중복 도구 호출 제거: 같은 함수+같은 인자면 캐시된 결과 재사용 (num_ctx 낭비 방지)
            logger.info(f"[Tool Use] 도구호출 {len(tool_calls)}건 감지 (반복{iteration + 1})")
            _iteration_tool_results = []
            _dedup_cache: dict = {}  # key: (tool_name, args_json) → value: refined_result
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

                # 중복 도구 호출 감지: 같은 반복 내 동일 함수+동일 인자면 캐시 사용
                _dedup_key = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))
                if _dedup_key in _dedup_cache:
                    logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name}({tool_args}) → 중복 생략 (캐시 사용)")
                    continue

                logger.info(f"[도구호출] [{tc_idx}/{len(tool_calls)}] {tool_name}({tool_args})")

                # 진행 상태 보고: 도구 호출 시작 (상세 정보 포함)
                display_name = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                detail_msg = _build_tool_detail_message(tool_name, tool_args)
                _report_progress(
                    progress_queue,
                    f"{display_name} 중... ({tc_idx}/{len(tool_calls)})" + (f" — {detail_msg}" if detail_msg else ""),
                    "tool_calling",
                    tool_name=tool_name,
                    iteration=iteration + 1,
                    max_iterations=max_tool_iterations,
                )

                # 도구 사용 추적
                if tool_name not in _tools_used:
                    _tools_used.append(tool_name)

                # 도구 실행
                t_tool = time.time()
                tool_result = execute_tool(tool_name, tool_args)
                tool_elapsed = time.time() - t_tool
                result_len = len(tool_result or "")
                logger.info(f"[도구결과] [{tc_idx}/{len(tool_calls)}] {tool_name} ({tool_elapsed:.1f}s) 결과길이={result_len}자")

                # 진행 상태 보고: 도구 실행 완료
                _report_progress(
                    progress_queue,
                    f"{display_name} 완료 ({tool_elapsed:.1f}초)",
                    "tool_done",
                    tool_name=tool_name,
                )
                logger.info(f"[도구결과데이터] {tool_name}:\n{tool_result}")

                # 도구 결과에서 출처 수집 (search_web 전용: 정제 후 LLM이 보는 결과와 동일한 출처만 수집)
                # search_farm_knowledge는 내부 RAG 문서 검색이므로 외부 URL 출처 수집 안 함
                # (이전 대화에서 저장된 웹 검색 URL이 무관한 출처로 표시되는 문제 방지)
                if tool_result and tool_name == "search_web":
                    try:
                        _, _filtered_sources = _refine_search_web(tool_result, user_query)
                        _collected_sources.extend(_filtered_sources)
                    except (json.JSONDecodeError, TypeError):
                        pass

                # 도구 결과를 정제하여 수집 (반복 완료 후 병합하여 메시지 1건으로 추가)
                refined_result = _refine_tool_result(tool_name, tool_result, user_query)
                logger.info(
                    f"[도구정제] {tool_name} 원본={len(tool_result or '')}자 → 정제={len(refined_result)}자"
                )
                _iteration_tool_results.append(refined_result)
                _dedup_cache[_dedup_key] = True  # 중복 방지용 캐시 등록

            # 같은 반복의 모든 도구 결과를 하나의 tool 메시지로 병합 (메시지 수 절감 → 컨텍스트 절약)
            # 동일 도구(get_farm_realtime_data)의 적정범위(공통) 중복 제거: 첫 번째만 보존
            if _iteration_tool_results:
                _seen_common_prefix = set()
                _deduped_results = []
                for r in _iteration_tool_results:
                    lines = r.split(" | ")
                    filtered_lines = []
                    for line in lines:
                        if line.startswith("적정범위(공통):"):
                            if "적정범위(공통)" not in _seen_common_prefix:
                                _seen_common_prefix.add("적정범위(공통)")
                                filtered_lines.append(line)
                            # 이미 본 적정범위는 생략
                        else:
                            filtered_lines.append(line)
                    _deduped_results.append(" | ".join(filtered_lines))
                merged_result = "\n".join(_deduped_results)
                messages.append({
                    "role": "tool",
                    "content": merged_result
                })
                logger.info(f"[도구결과병합] {len(_iteration_tool_results)}건 → 1메시지 ({len(merged_result)}자)")

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
