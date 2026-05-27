# ════════════════════════════════════════════════════════════════
# LLM 메시지/응답 유틸 — pure helper 함수 모음
# Ollama 패키지 응답 객체와 dict 응답을 통일된 방식으로 파싱.
# 순수 유틸 모듈 — 외부 상태/통신 없음.
# --->
# serialize_for_log: 로그용 안전 직렬화 (재귀적 model_dump / __dict__)
# extract_message_content: 응답에서 assistant content 추출
# normalize_assistant_message: 객체/dict 응답을 dict로 표준화
# extract_tool_name: tool_call에서 함수명 추출
# extract_tool_arguments: tool_call에서 arguments dict 추출 (JSON 문자열 파싱 포함)
# coerce_numeric_id: LLM의 비정수 ID를 기본값(정수)으로 교정
# ════════════════════════════════════════════════════════════════
from typing import Any, Dict, List, Optional

from agri_ai_core.src.utils.json_utils import safe_json_load


# ────────────────────────────────────────────────────────────────────
# LLM 요청/응답 로그 기록용 안전 직렬화 (재귀적).
# - 기본 타입은 그대로
# - dict/list는 요소별 재귀
# - Pydantic 모델은 model_dump()
# - 일반 객체는 __dict__ (언더스코어 속성 제외)
# - 그 외는 str()
# ────────────────────────────────────────────────────────────────────
def serialize_for_log(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_for_log(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_for_log(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: serialize_for_log(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


# ────────────────────────────────────────────────────────────────────
# LLM 응답에서 assistant 메시지 content(str)를 추출.
# ollama 패키지 객체(response.message.content)와 dict 응답 모두 처리.
# ────────────────────────────────────────────────────────────────────
def extract_message_content(response: Any) -> str:
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


# ────────────────────────────────────────────────────────────────────
# 응답 객체/dict를 표준 dict로 변환. role/content/tool_calls 보존.
# ────────────────────────────────────────────────────────────────────
def normalize_assistant_message(assistant_message: Any) -> Dict[str, Any]:
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


# ────────────────────────────────────────────────────────────────────
# tool_call에서 함수명 추출 (dict와 객체 모두 지원).
# ────────────────────────────────────────────────────────────────────
def extract_tool_name(tool_call: Any) -> Optional[str]:
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


# ────────────────────────────────────────────────────────────────────
# tool_call에서 arguments dict를 추출. str이면 JSON 파싱. 실패 시 빈 dict.
# ────────────────────────────────────────────────────────────────────
def extract_tool_arguments(tool_call: Any) -> Dict[str, Any]:
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
        parsed = safe_json_load(raw_args)
        if isinstance(parsed, dict):
            return parsed
    return {}


# ────────────────────────────────────────────────────────────────────
# LLM이 비정수 값을 ID로 넣은 경우 기본값(정수)으로 교정.
# (예: 농장명 문자열 → 실제 숫자 farm_id)
# ────────────────────────────────────────────────────────────────────
def coerce_numeric_id(provided_id, default_id):
    if provided_id in (None, "") or default_id in (None, ""):
        return provided_id
    provided_text = str(provided_id).strip()
    default_text = str(default_id).strip()
    if default_text.isdigit() and not provided_text.isdigit():
        return default_text
    return provided_id


# ────────────────────────────────────────────────────────────────────
# tool_calls 필드 우선, content에 JSON 도구 호출이 텍스트로 출력된 경우도 파싱.
# ────────────────────────────────────────────────────────────────────
def extract_tool_calls(assistant_message: dict, logger=None) -> list:
    tool_calls = assistant_message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        return tool_calls

    content = assistant_message.get("content", "").strip()
    if content.startswith("{") and content.endswith("}"):
        parsed = safe_json_load(content)
        if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
            tool_call = {"function": {"name": parsed["name"], "arguments": parsed["arguments"]}}
            assistant_message["content"] = ""
            assistant_message["tool_calls"] = [tool_call]
            if logger:
                logger.warning(
                    f"[Tool Use] content에서 도구호출 JSON 감지 → tool_calls로 변환: {parsed['name']}"
                )
            return [tool_call]

    return []
