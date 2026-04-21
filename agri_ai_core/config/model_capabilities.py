# ════════════════════════════════════════════════════════════════════
# 모델 capability 메타 — 비전/도구/JSON 스키마 지원 여부를 단일 위치에서 선언.
# 새 모델 도입 시 본 파일 한 곳만 갱신하면 모든 호출 경로(메인 LLM, 비전,
# AI 제어, 채팅)가 자동 동조 — "LLM이 변경되어도 동일 처리" 원칙의 근간.
# --->
# get_caps             : 모델명 → capability dict (정확 일치 → prefix → 기본값)
# supports_vision      : 비전(이미지) 입력 지원 여부
# supports_tools       : 도구 호출 (function calling) 지원 여부
# supports_json_schema : Ollama format=<schema> 강제 지원 여부
# ════════════════════════════════════════════════════════════════════
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════
# 모델 → capability 매핑.
# 새 모델은 본 dict 또는 _PREFIX_CAPS 한 줄 추가만으로 전 시스템 반영.
# ════════════════════════════════════════════════════════════════════
MODEL_CAPS = {
    # gemma 계열
    "gemma3:27b":                          {"vision": True,  "tools": True,  "json_schema": True},
    "gemma4:31b":                          {"vision": False, "tools": True,  "json_schema": True},
    # qwen 계열
    "qwen2.5vl:32b":                       {"vision": True,  "tools": True,  "json_schema": True},
    "qwen2.5-vl:32b":                      {"vision": True,  "tools": True,  "json_schema": True},
    "qwen3:30b-a3b-instruct-2507-q4_K_M":  {"vision": False, "tools": True,  "json_schema": True},
    # 비전 전용 후보 — 도구 호출/스키마는 일반적으로 미지원
    "llava:13b":                           {"vision": True,  "tools": False, "json_schema": False},
    "llama3.2-vision:11b":                 {"vision": True,  "tools": False, "json_schema": False},
    "pixtral-12b":                         {"vision": True,  "tools": False, "json_schema": False},
}

# prefix → capability — 정확 매칭 실패 시 fallback. 위에서 아래로 첫 매칭 적용.
_PREFIX_CAPS = (
    ("gemma3",          {"vision": True,  "tools": True,  "json_schema": True}),
    ("gemma4",          {"vision": False, "tools": True,  "json_schema": True}),
    ("qwen2.5vl",       {"vision": True,  "tools": True,  "json_schema": True}),
    ("qwen2.5-vl",      {"vision": True,  "tools": True,  "json_schema": True}),
    ("qwen3-vl",        {"vision": True,  "tools": True,  "json_schema": True}),
    ("qwen",            {"vision": False, "tools": True,  "json_schema": True}),
    ("llava",           {"vision": True,  "tools": False, "json_schema": False}),
    ("llama3.2-vision", {"vision": True,  "tools": False, "json_schema": False}),
    ("pixtral",         {"vision": True,  "tools": False, "json_schema": False}),
    ("minicpm",         {"vision": True,  "tools": False, "json_schema": False}),
)

# 미식별 모델 보수적 기본값 — 비전은 안전하게 false, 도구·스키마는 ollama 표준 가정
_DEFAULT_CAPS = {"vision": False, "tools": True, "json_schema": True}


# ────────────────────────────────────────────────────────────────────
# 모델명에 해당하는 capability dict 반환.
# 정확 일치(원형/소문자) → prefix 매칭 → 기본값 순으로 결정.
# 반환은 항상 dict 복사본 — 호출자 변형이 메타 원본을 오염시키지 않도록.
# ────────────────────────────────────────────────────────────────────
def get_caps(model):
    if not model:
        return dict(_DEFAULT_CAPS)
    raw = model.strip()
    if raw in MODEL_CAPS:
        return dict(MODEL_CAPS[raw])
    name = raw.lower()
    if name in MODEL_CAPS:
        return dict(MODEL_CAPS[name])
    for prefix, caps in _PREFIX_CAPS:
        if name.startswith(prefix.lower()):
            return dict(caps)
    return dict(_DEFAULT_CAPS)


# ────────────────────────────────────────────────────────────────────
# 비전(이미지 입력) 지원 여부.
# ────────────────────────────────────────────────────────────────────
def supports_vision(model):
    return bool(get_caps(model).get("vision"))


# ────────────────────────────────────────────────────────────────────
# 도구 호출 (function calling) 지원 여부.
# ────────────────────────────────────────────────────────────────────
def supports_tools(model):
    return bool(get_caps(model).get("tools"))


# ────────────────────────────────────────────────────────────────────
# Ollama format=<schema> 강제 지원 여부.
# ────────────────────────────────────────────────────────────────────
def supports_json_schema(model):
    return bool(get_caps(model).get("json_schema"))
