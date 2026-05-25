# ══════════════════════════════════════════════════════════════════════════════
# llm_backend_vllm — vLLM OpenAI 호환 backend (Ollama 대체용) [2026-05-25]
#
# 활성화: 환경변수 LLM_BACKEND=vllm  (default 'ollama' — 본 모듈 미사용)
# 엔드포인트: VLLM_URL  (기본 http://127.0.0.1:8001)
#
# 본 모듈은 _ollama_chat 의 *동일 시그니처* 를 제공하여 llm_transport 에서
# backend switch 만으로 교체 가능. embedder/vision 등 다른 ollama 호출 위치는
# 영향 받지 않는다 (단계적 마이그레이션).
#
# OpenAI Chat Completions API 매핑:
#   Ollama options                vLLM/OpenAI 필드
#   ───────────────────────       ─────────────────
#   num_predict                   max_tokens
#   num_ctx                       (서버에서 model max_model_len 으로 설정)
#   temperature                   temperature
#   top_p                         top_p
#   top_k                         top_k (OpenAI 표준 외, vLLM extra)
#   format='json'                 response_format={"type":"json_object"}
#   format=<schema dict>          response_format={"type":"json_schema", "json_schema":...}
#   tools=[...]                   tools=[...] (OpenAI 함수 호출 호환)
#   keep_alive=-1                 (vLLM 항상 상주 — 무시)
#   think=True/False              extra_body={"chat_template_kwargs": {"enable_thinking": ...}}
#
# 파일 시작 함수 목록:
#   is_enabled            : LLM_BACKEND=vllm 여부
#   _vllm_base_url        : VLLM_URL env (default localhost:8001)
#   _convert_options      : ollama options → openai 필드
#   _convert_format       : ollama format → openai response_format
#   _convert_response     : openai response → ollama-호환 dict (호출자 호환)
#   vllm_chat             : ollama_chat 와 동일 시그니처. messages 기반.
#   vllm_generate         : single prompt 기반 (ai_control 의 /api/generate 대체)
#   vllm_list_models      : /v1/models
#   health                : /health 또는 /v1/models 핑
# ══════════════════════════════════════════════════════════════════════════════
import json
import os
import time
from typing import Any, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from agri_ai_core.logs import setup_logger
from agri_ai_core.src.utils.validators import is_true

logger = setup_logger(__name__)

_VLLM_TIMEOUT_SEC = 300


# ────────────────────────────────────────────────────────────────────
# Backend 활성화 / endpoint
# ────────────────────────────────────────────────────────────────────
def is_enabled() -> bool:
    """LLM_BACKEND=vllm 일 때만 True. default 'ollama' → 본 모듈 안 씀."""
    return os.getenv("LLM_BACKEND", "ollama").strip().lower() == "vllm"


def _vllm_base_url() -> str:
    return os.getenv("VLLM_URL", "http://127.0.0.1:8001").rstrip("/")


# ────────────────────────────────────────────────────────────────────
# 옵션 / format 변환
# ────────────────────────────────────────────────────────────────────
def _convert_options(options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ollama options dict → OpenAI 필드 매핑."""
    if not options:
        return {}
    out: Dict[str, Any] = {}
    extra_body: Dict[str, Any] = {}

    if "num_predict" in options and options["num_predict"] is not None:
        out["max_tokens"] = int(options["num_predict"])
    if "temperature" in options and options["temperature"] is not None:
        out["temperature"] = float(options["temperature"])
    if "top_p" in options and options["top_p"] is not None:
        out["top_p"] = float(options["top_p"])
    if "top_k" in options and options["top_k"] is not None:
        # OpenAI 표준엔 없으나 vLLM extra 로 받음
        extra_body["top_k"] = int(options["top_k"])
    if "stop" in options:
        out["stop"] = options["stop"]

    # think → enable_thinking (vLLM gemma3 chat_template_kwargs)
    think_val = options.get("think")
    if think_val is not None:
        extra_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = bool(think_val)

    # format 변환 (top-level 인자로 들어올 수도 있음)
    fmt = options.get("format")
    if fmt:
        out["response_format"] = _convert_format(fmt)

    if extra_body:
        out["extra_body"] = extra_body
    return out


def _convert_format(fmt: Any) -> Dict[str, Any]:
    """Ollama format='json' / format=<schema dict> → OpenAI response_format."""
    if fmt == "json" or fmt is True:
        return {"type": "json_object"}
    if isinstance(fmt, dict):
        # schema 강제 — OpenAI structured outputs
        return {"type": "json_schema",
                "json_schema": {"name": "schema", "schema": fmt, "strict": True}}
    return {"type": "json_object"}


# ────────────────────────────────────────────────────────────────────
# 응답 변환 — OpenAI response → ollama-호환 dict
# 호출자 (_extract_message_content 등) 가 동일 패턴 사용 가능하도록
# {'message': {'role':'assistant', 'content':..., 'tool_calls':...}} 형식.
# ────────────────────────────────────────────────────────────────────
def _convert_response(openai_resp: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(openai_resp, dict):
        return {"message": {"role": "assistant", "content": str(openai_resp)}}

    choices = openai_resp.get("choices") or []
    if not choices:
        return {"message": {"role": "assistant", "content": ""}}

    first = choices[0]
    msg = first.get("message") or {}
    content = msg.get("content") or ""
    tool_calls_oa = msg.get("tool_calls") or []

    # OpenAI tool_calls → Ollama tool_calls 형식
    tool_calls = []
    for tc in tool_calls_oa:
        fn = tc.get("function") or {}
        name = fn.get("name")
        args = fn.get("arguments")
        # OpenAI 는 arguments 가 string (JSON) — Ollama 는 dict
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except Exception:
                pass
        tool_calls.append({"function": {"name": name, "arguments": args}})

    out_msg = {"role": "assistant", "content": content}
    if tool_calls:
        out_msg["tool_calls"] = tool_calls

    return {
        "model": openai_resp.get("model"),
        "message": out_msg,
        "done": True,
        "total_duration": int((openai_resp.get("usage", {}).get("total_tokens") or 0) * 1_000_000),
    }


# ────────────────────────────────────────────────────────────────────
# 저수준 HTTP POST
# ────────────────────────────────────────────────────────────────────
def _http_post_json(path: str, payload: Dict[str, Any],
                    timeout: int = _VLLM_TIMEOUT_SEC) -> Dict[str, Any]:
    url = f"{_vllm_base_url()}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url, data=data, method="POST",
                             headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"vLLM 응답 JSON parse 실패: {e} body={body[:200]!r}")


# ────────────────────────────────────────────────────────────────────
# Public — chat (_ollama_chat 호환 시그니처)
# ────────────────────────────────────────────────────────────────────
def vllm_chat(
    *,
    model: str,
    messages: List[Dict[str, str]],
    options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    keep_alive: Any = None,   # vLLM 무관, 인자 호환용
    think: Any = None,
) -> Dict[str, Any]:
    """OpenAI 호환 /v1/chat/completions 호출."""
    converted = _convert_options(options) if options else {}
    if think is not None:
        # 별도 think 인자도 처리
        converted.setdefault("extra_body", {})\
                 .setdefault("chat_template_kwargs", {})["enable_thinking"] = bool(think)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    payload.update(converted)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    t_start = time.time()
    logger.info(
        f"[vLLM요청] chat model={model} messages={len(messages)} tools={len(tools or [])} "
        f"max_tokens={payload.get('max_tokens')}"
    )
    try:
        resp = _http_post_json("/v1/chat/completions", payload)
    except Exception as e:
        logger.warning(f"[vLLM] chat 실패: {e}")
        raise
    elapsed = time.time() - t_start
    logger.info(f"[vLLM응답] chat ({elapsed:.1f}s)")
    return _convert_response(resp)


# ────────────────────────────────────────────────────────────────────
# Public — generate (legacy /v1/completions, ai_control 의 single-prompt 대체)
# 또는 messages=[{"role":"user","content":prompt}] 로 chat 변환.
# ────────────────────────────────────────────────────────────────────
def vllm_generate(
    *,
    model: str,
    prompt: str,
    options: Optional[Dict[str, Any]] = None,
    format: Any = None,
    keep_alive: Any = None,
    timeout: int = _VLLM_TIMEOUT_SEC,
) -> Dict[str, Any]:
    """Single-prompt 호출. messages 형태로 변환해 /v1/chat/completions 사용 (안정성)."""
    eff_options = dict(options or {})
    if format is not None:
        eff_options["format"] = format
    resp = vllm_chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options=eff_options,
    )
    # Ollama /api/generate 는 'response' 필드 사용 — 호환
    content = (resp.get("message") or {}).get("content", "")
    return {"model": model, "response": content, "done": True,
            "message": resp.get("message")}


# ────────────────────────────────────────────────────────────────────
# 모델 목록 / health
# ────────────────────────────────────────────────────────────────────
def vllm_list_models(timeout: int = 8) -> List[str]:
    url = f"{_vllm_base_url()}/v1/models"
    try:
        req = urlrequest.Request(url, method="GET")
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    except Exception as e:
        logger.warning(f"[vLLM] list_models 실패: {e}")
        return []


def health(timeout: int = 5) -> bool:
    try:
        req = urlrequest.Request(f"{_vllm_base_url()}/health", method="GET")
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        # /health 미지원 시 /v1/models 로 폴백
        return len(vllm_list_models(timeout=timeout)) > 0
