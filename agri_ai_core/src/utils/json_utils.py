# ════════════════════════════════════════════════════════════
# JSON 유틸 — 예외 안전한 JSON 직렬화/역직렬화
# LLM 응답 파싱, API payload 구성 등 67곳 이상에서 사용되는
# try/except json.loads 패턴을 표준화한다.
# --->
# safe_json_load: 문자열 → dict/list (실패 시 default 반환)
# safe_json_dump: 객체 → 문자열 (실패 시 default 반환)
# extract_json_block: 텍스트에서 JSON 객체 블록 추출 (```json 제거 포함)
# ════════════════════════════════════════════════════════════
import json
import re
from typing import Any, Optional


def safe_json_load(text: Optional[str], default: Any = None) -> Any:
    """문자열을 JSON 파싱. None/빈문자열/파싱실패 시 default 반환.
    Args:
        text: JSON 문자열 (None/bytes 허용)
        default: 실패 시 반환할 기본값 (기본 None)
    """
    if text is None:
        return default
    if isinstance(text, (bytes, bytearray)):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            return default
    if not isinstance(text, str) or not text.strip():
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def safe_json_dump(obj: Any, default: str = "{}", **kwargs) -> str:
    """객체를 JSON 문자열로. 실패 시 default 반환.
    기본 ensure_ascii=False (한글 보존).
    """
    kwargs.setdefault("ensure_ascii", False)
    try:
        return json.dumps(obj, **kwargs)
    except (TypeError, ValueError):
        return default


_JSON_CODEBLOCK_RE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_block(text: Optional[str]) -> Optional[dict]:
    """LLM 응답 텍스트에서 JSON 객체 하나를 추출 + 파싱.
    - <think>...</think> 태그 제거
    - ```json ... ``` 코드펜스 제거
    - 가장 바깥 { ... } 매칭 후 파싱
    실패 시 None 반환.
    """
    if not text:
        return None
    # think 태그 제거
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # 코드펜스 제거
    text = _JSON_CODEBLOCK_RE.sub("", text).replace("```", "")
    # JSON 객체 매칭
    m = _JSON_OBJECT_RE.search(text)
    if not m:
        return None
    return safe_json_load(m.group(0))
