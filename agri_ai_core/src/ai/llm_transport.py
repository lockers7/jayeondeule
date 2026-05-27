# ═══════════════════════════════════════════════════════════════════════
# LLM 전송 계층 — Ollama 모델 선택, GPU 비율 산출, 3가지 전송 방식.
# package/direct-HTTP/MCP 3가지 Ollama 전송을 관리한다.
# --->
# _get_model_gpu_ratio: Ollama /api/ps에서 GPU 탑재 비율 조회 (TTL 캐시)
# _get_free_vram_mib: nvidia-smi로 여유 VRAM 조회
# _get_model_ctx_options: num_ctx 고정 옵션 빌더
# _use_mcp_fetch / _use_ollama_package / _use_direct_ollama_http: 전송 방식 활성화 여부
# _is_direct_ollama_enabled: direct HTTP 활성화 상태 (disabled_reason 미포함)
# _disable_direct_ollama_http: direct HTTP를 런타임에 비활성화
# _is_connection_related_error: 연결 관련 에러 판별
# _extract_model_names: 모델 목록에서 이름 추출
# _pkg_ollama_list_models / _direct_ollama_list_models / _mcp_ollama_list_models: 전송별 모델 목록
# _build_chat_payload: Ollama chat API 공통 payload 빌더
# _pkg_ollama_chat / _direct_ollama_chat / _mcp_ollama_chat: 전송별 chat 호출
# _build_ollama_url / _direct_ollama_json: 저수준 HTTP 통신
# _get_available_models: 3개 전송 중 가용한 것으로 모델 목록 조회
# _get_model_name: 현재 사용할 모델명 결정 (캐시 + 자동 선택)
# ═══════════════════════════════════════════════════════════════════════
import json
import os
import time
import threading
from typing import Any, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import ollama
except Exception:
    ollama = None

from agri_ai_core.logs import setup_logger
from agri_ai_core.config import NUM_PREDICT, NUM_CTX, get_ollama_url, get_model_name as _config_get_model_name
from agri_ai_core.src.ai.llm_runtime_guard import llm_activity
from agri_ai_core.src.utils.validators import is_true

logger = setup_logger(__name__)

# ═════════════════════
# 전역 상태 (전송 계층)
# ═════════════════════
_cached_model_name: Optional[str] = None
_model_cache_lock = threading.Lock()
_direct_ollama_disabled_reason: Optional[str] = None

# GPU 비율 캐시: {model_name: (gpu_ratio, cached_at)}
_gpu_ratio_cache: Dict[str, tuple] = {}
_GPU_RATIO_CACHE_TTL = 60

# Ollama 환경 설정 (프로세스 수명)
os.environ['OLLAMA_MAX_LOADED_MODELS'] = '1'
os.environ['OLLAMA_NUM_PARALLEL'] = '2'
os.environ['OLLAMA_KEEP_ALIVE'] = '-1'


# ────────────────────────────────────────────────────────────────────
# Ollama /api/ps에서 GPU 탑재 비율 조회 (TTL 캐시 60초).
# ────────────────────────────────────────────────────────────────────
def _get_model_gpu_ratio(model_name: str) -> float:
    now = time.time()
    if model_name in _gpu_ratio_cache:
        ratio, cached_at = _gpu_ratio_cache[model_name]
        if now - cached_at < _GPU_RATIO_CACHE_TTL:
            return ratio
    _boost = 1.2 if "mistral" in model_name.lower() else 1.0
    try:
        ollama_url = get_ollama_url().rstrip("/")
        req = urlrequest.Request(f"{ollama_url}/api/ps")
        with urlrequest.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        for m in data.get("models", []):
            if m.get("name", "").startswith(model_name.split(":")[0]):
                total = m.get("size", 0)
                vram = m.get("size_vram", 0)
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


# ────────────────────────────────────────────────────────────────────
# nvidia-smi로 여유 VRAM(MiB) 반환. 실패 시 0.
# ────────────────────────────────────────────────────────────────────
def _get_free_vram_mib() -> int:
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


# ────────────────────────────────────────────────────────────────────
# num_ctx 고정(16384) — GPU 100% 유지.
# ────────────────────────────────────────────────────────────────────
def _get_model_ctx_options(model_name: str, num_predict: int) -> dict:
    return {"num_ctx": NUM_CTX, "num_predict": num_predict}


# ═════════════════════
# 전송 방식 토글
# ═════════════════════
def _use_mcp_fetch() -> bool:
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
    return any(kw in message for kw in (
        "failed to connect to ollama", "ollama connection error",
        "operation not permitted", "connection refused", "timed out", "timeout",
        "mcp server disabled at runtime: fetch", "mcp timeout: fetch",
        "direct http is unavailable", "no available ollama transport",
    ))


# ═════════════════════
# 모델 이름 추출
# ═════════════════════
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


# ═════════════════════
# chat payload 빌더
# ═════════════════════
# ────────────────────────────────────────────────────────────────────
# Ollama chat API용 공통 payload 빌드.
# ────────────────────────────────────────────────────────────────────
def _build_chat_payload(
    model: str,
    messages: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Optional[str] = None,
    think: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    # ollama 는 정수 -1 을 무한 keep_alive 로 해석. 문자열 "-1" 은 default 5분으로 fallback.
    payload["keep_alive"] = keep_alive if keep_alive is not None else -1
    if think is not None:
        payload["think"] = think
    return payload


# ═══════════════════════════
# package / direct / MCP 전송
# ═══════════════════════════
def _pkg_ollama_list_models() -> List[str]:
    if not _use_ollama_package():
        return []
    result = ollama.list()
    models = getattr(result, "models", None)
    if models is None and isinstance(result, dict):
        models = result.get("models", [])
    return _extract_model_names(models or [])


_LLM_TIMEOUT_SEC = 300  # 최장 5분 — hang 방지

# ────────────────────────────────────────────────────────────────────
# ollama 패키지 chat 호출 (기본 300초). hang 시 자동 RuntimeError.
# timeout_sec: 호출별 타임아웃(초). None이면 _LLM_TIMEOUT_SEC 사용.
# ────────────────────────────────────────────────────────────────────
def _pkg_ollama_chat(model, messages, options=None, tools=None, keep_alive=None,
                     think=None, timeout_sec=None) -> Any:
    if not _use_ollama_package():
        raise RuntimeError("ollama package unavailable")
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    _t = timeout_sec if timeout_sec is not None else _LLM_TIMEOUT_SEC
    payload = _build_chat_payload(model, messages, options, tools, keep_alive, think)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ollama.chat, **payload)
        try:
            return future.result(timeout=_t)
        except FuturesTimeout:
            logger.error(f"[Ollama] ollama.chat timeout ({_t}s) — model={model}")
            raise RuntimeError(f"Ollama chat timeout ({_t}s)")


def _build_ollama_url(path: str) -> str:
    base = get_ollama_url().rstrip("/")
    return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"


def _direct_ollama_json(path: str, method: str = "GET",
                        json_body: Optional[Dict[str, Any]] = None,
                        timeout: int = 600) -> Dict[str, Any]:
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


def _direct_ollama_chat(model, messages, options=None, tools=None,
                        keep_alive=None, timeout=600, think=None) -> Dict[str, Any]:
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


def _mcp_ollama_chat(model, messages, options=None, tools=None,
                     keep_alive=None, timeout=120, think=None) -> Dict[str, Any]:
    from agri_ai_core.src.ai.mcp_client import mcp_fetch_json
    payload = _build_chat_payload(model, messages, options, tools, keep_alive, think)
    result = mcp_fetch_json(
        url=f"{get_ollama_url()}/api/chat", method="POST",
        json_body=payload, timeout=timeout,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "MCP chat call failed")
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Ollama chat 응답 파싱 실패")
    return data


# ═══════════════════════════
# 모델 목록 + 모델 선택
# ═══════════════════════════
# ────────────────────────────────────────────────────────────────────
# 사용 가능한 Ollama 전송에서 모델 목록 조회.
# ────────────────────────────────────────────────────────────────────
def _get_available_models() -> List[str]:
    if _use_ollama_package():
        try:
            return _pkg_ollama_list_models()
        except Exception:
            pass
    if _use_mcp_fetch():
        try:
            return _mcp_ollama_list_models()
        except Exception:
            pass
    if _is_direct_ollama_enabled():
        try:
            return _direct_ollama_list_models()
        except Exception:
            pass
    return []


# ────────────────────────────────────────────────────────────────────
# 현재 사용할 모델명 결정 (캐시 + 설정 + 자동 선택).
# 스레드 안전: _model_cache_lock으로 보호.
# preferred 가 변경되면 _cached_model_name 자동 invalidate.
# .env MODEL_NAME 변경(웹 UI 의 change_model API 등) 이 모든 프로세스에 즉시
# 반영되도록 — config.get_model_name() 이 .env 매번 read + mtime 캐시.
# ────────────────────────────────────────────────────────────────────
def _get_model_name() -> str:
    global _cached_model_name
    preferred = _config_get_model_name()

    with _model_cache_lock:
        # 캐시가 현재 선호 모델과 동일한 경우만 재사용 — preferred 가 바뀌면 invalidate.
        if _cached_model_name == preferred:
            return _cached_model_name
        if _cached_model_name and _cached_model_name != preferred:
            logger.info(
                f"[모델선택] 선호 모델 변경 감지: 캐시={_cached_model_name} → 새 선호={preferred}"
            )
            _cached_model_name = None

    available = _get_available_models()
    if not available:
        logger.warning("[모델선택] 사용 가능한 모델 없음, 설정값 사용")
        return preferred

    logger.info(f"[모델선택] 설정 모델: {preferred}, 폴백 모델: {_config_get_model_name()}")
    logger.info(f"[모델선택] 사용 가능 모델: {available}")

    if preferred in available:
        with _model_cache_lock:
            _cached_model_name = preferred
        logger.info(f"[모델선택] 선호 모델 '{preferred}' 사용")
        return preferred

    prefix = preferred.split(":")[0]
    for m in available:
        if m.startswith(prefix):
            with _model_cache_lock:
                _cached_model_name = m
            logger.info(f"[모델선택] 접두사 매칭 '{m}' 사용")
            return m

    fallback = available[0]
    with _model_cache_lock:
        _cached_model_name = fallback
    logger.warning(f"[모델선택] 폴백 '{fallback}' 사용")
    return fallback


# ═══════════════════════════════════
# LLM 로깅 + Ollama Chat 실행기
# ═══════════════════════════════════
from agri_ai_core.src.ai.llm_message_utils import (
    serialize_for_log as _serialize_for_log,
    extract_message_content as _extract_message_content,
    normalize_assistant_message as _normalize_assistant_message,
    extract_tool_calls as _extract_tool_calls_fn,
)


# ────────────────────────────────────────────────────────────────────
# LLM 호출 전 요청 payload JSON 로그.
# ────────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────
# LLM 응답 JSON 로그 + 성능 메트릭.
# ────────────────────────────────────────────────────────────────────
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
            transport, elapsed,
            json.dumps(response_json, ensure_ascii=False, indent=2, default=str),
        )
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


# ────────────────────────────────────────────────────────────────────
# 3가지 전송(package/MCP/direct) 중 가용한 것으로 Ollama chat 호출.
# 전송 실패 시 다음 전송으로 폴백. 모두 실패 시 RuntimeError.
# ────────────────────────────────────────────────────────────────────
# Ollama "server busy / 503" 일시 자원 부족 에러 감지 헬퍼.
#   대화 LLM 호출 시 제어 LLM 또는 임베딩이 슬롯을 점유 중이면 503 발생.
#   짧은 backoff 후 재시도하면 슬롯 확보되어 정상 응답 받을 가능성 높음.
#   Ollama crash 방어: connection refused / server disconnected 도 재시도 대상.
#   두 transport 가 모두 같은 Ollama 포트를 사용하므로 transport fallback 이 아니라
#   동일 transport 내 backoff 재시도로 Ollama 재시작(5-20초)을 기다려야 한다.
def _is_ollama_busy_error(err: Exception) -> bool:
    s = str(err).lower()
    return (
        "server busy" in s
        or "maximum pending requests" in s
        or "503" in s
        or "connection refused" in s
        or "server disconnected" in s
        or ("connection error" in s and "ollama" in s)
    )


_OLLAMA_BUSY_BACKOFFS = (5.0, 15.0, 30.0)  # Ollama crash 재시작 대기: 총 50초


def _ollama_chat(
    model: str,
    messages: list,
    options: dict = None,
    tools: list = None,
    keep_alive: str = None,
    timeout_sec: int = None,
):
    # LLM backend 은 Ollama 단일. vLLM 대체는 16GB VRAM 한계로 무의미하여 제거됨
    # (엔진이 아니라 VRAM 이 병목 — 상세: docs/dev/vllm_infeasible.md). ⛔재착수금지.
    think_value = None
    if options and "think" in options:
        think_value = options.pop("think")

    errors = []
    msg_count = len(messages or [])
    tool_count = len(tools or [])
    t_start = time.time()

    logger.info(
        f"[Ollama요청] model={model} messages={msg_count} tools={tool_count} "
        f"options={{{', '.join(f'{k}={v}' for k, v in (options or {}).items())}}}"
    )
    _log_llm_request_json(model, messages, options, tools, keep_alive)

    _TRANSPORTS = [
        ("package", _use_ollama_package, _pkg_ollama_chat),
        ("MCP",     _use_mcp_fetch,      _mcp_ollama_chat),
        ("direct",  _is_direct_ollama_enabled, _direct_ollama_chat),
    ]

    for label, check_fn, call_fn in _TRANSPORTS:
        if not check_fn():
            continue
        # 동일 transport 내 503/busy 재시도 (_OLLAMA_BUSY_BACKOFFS 단계 backoff)
        last_err = None
        for attempt in range(len(_OLLAMA_BUSY_BACKOFFS) + 1):
            try:
                _extra = {"timeout_sec": timeout_sec} if (label == "package" and timeout_sec is not None) else {}
                # 제어(ai_control)/agent 와 동일한 상호배제 — 채팅이 제어/agent 와
                # 동시에 Ollama 를 점유해 fallback/충돌을 유발하지 않도록
                # 실제 호출 순간에만 락 점유(chat_llm_gate 는 그 앞단 우선순위 양보 담당).
                from agri_ai_core.src.ai.llm_runtime_guard import llm_call_lock as _chat_llm_call_lock
                _chat_wait = timeout_sec or _LLM_TIMEOUT_SEC
                with _chat_llm_call_lock("chat", wait_sec=_chat_wait):
                    with llm_activity(f"llm_transport:{label}", timeout_sec or _LLM_TIMEOUT_SEC):
                        result = call_fn(
                            model=model, messages=messages, options=options,
                            tools=tools, keep_alive=keep_alive, think=think_value,
                            **_extra,
                        )
                elapsed = time.time() - t_start
                _log_llm_response_json(result, label, elapsed)
                resp_content = _extract_message_content(result)
                log_msg = (
                    f"[Ollama응답] transport={label} ({elapsed:.1f}s) "
                    f"답변길이={len(resp_content)}자"
                )
                if label == "package":
                    resp_tool_calls = _extract_tool_calls_fn(
                        _normalize_assistant_message(
                            result.message if hasattr(result, 'message')
                            else (result.get('message', {}) if isinstance(result, dict) else {})
                        ),
                        logger=logger,
                    )
                    log_msg += f" tool_calls={len(resp_tool_calls)}개"
                logger.info(log_msg)
                return result
            except Exception as err:
                last_err = err
                if _is_ollama_busy_error(err) and attempt < len(_OLLAMA_BUSY_BACKOFFS):
                    backoff = _OLLAMA_BUSY_BACKOFFS[attempt]
                    logger.warning(
                        f"Ollama chat busy({label}, 시도 {attempt + 1}) "
                        f"→ {backoff}s 후 재시도: {str(err)[:120]}"
                    )
                    time.sleep(backoff)
                    continue
                # busy 아닌 에러이거나 최대 재시도 도달 → transport fallback
                break
        # 이 transport 의 모든 재시도 실패 → 다음 transport 시도
        errors.append(str(last_err))
        if label == "direct":
            raise last_err
        logger.warning(f"Ollama chat 호출 실패({label}) -> fallback: {last_err}")

    error_tail = errors[-1] if errors else "all transports unavailable"
    raise RuntimeError(f"No available Ollama transport: {error_tail}")
