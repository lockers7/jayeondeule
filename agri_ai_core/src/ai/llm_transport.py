# ═══════════════════════════════════════════════════════════════════════
# LLM 전송 계층 — Ollama 모델 선택, GPU 비율 산출, 3가지 전송 방식.
# llm_client.py에서 분리. package/direct-HTTP/MCP 3가지 Ollama 전송을 관리한다.
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


def _get_model_gpu_ratio(model_name: str) -> float:
    """Ollama /api/ps에서 GPU 탑재 비율 조회 (TTL 캐시 60초)."""
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


def _get_free_vram_mib() -> int:
    """nvidia-smi로 여유 VRAM(MiB) 반환. 실패 시 0."""
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
    """num_ctx 고정(16384) — GPU 100% 유지."""
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
    payload["keep_alive"] = keep_alive or "-1"
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


def _pkg_ollama_chat(model, messages, options=None, tools=None, keep_alive=None, think=None) -> Any:
    if not _use_ollama_package():
        raise RuntimeError("ollama package unavailable")
    return ollama.chat(**_build_chat_payload(model, messages, options, tools, keep_alive, think))


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
def _get_available_models() -> List[str]:
    """사용 가능한 Ollama 전송에서 모델 목록 조회."""
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


def _get_model_name() -> str:
    """현재 사용할 모델명 결정 (캐시 + 설정 + 자동 선택).
    스레드 안전: _model_cache_lock으로 보호.
    """
    global _cached_model_name
    preferred = _config_get_model_name()

    with _model_cache_lock:
        if _cached_model_name:
            return _cached_model_name

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
