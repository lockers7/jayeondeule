# ══════════════════════════════════════════════════════════════════════════
# 신규 도구 등록 일관성 커버리지 테스트.
#
# LLM 제어 도구를 추가할 때 4곳을 모두 갱신해야 한다:
#   1. tools_definition.py       — LLM 에 노출되는 JSONSchema
#   2. tools_executor.py         — execute_tool dispatch 브랜치
#   3. pipeline/question_analyzer._VALID_TYPES / prompts ANALYZER_SYSTEM_PROMPT
#   4. tools_utils.TOOL_DEFAULT_CONTEXT (권한/컨텍스트 자동 주입이 필요한 경우)
#
# 이 테스트는 위 등록 누락을 CI 단계에서 자동 감지한다.
# ══════════════════════════════════════════════════════════════════════════
import re
from pathlib import Path

import pytest

from agri_ai_core.src.ai.tools_definition import get_available_tools
from agri_ai_core.src.ai.tools_utils import TOOL_DEFAULT_CONTEXT
from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS


REPO_ROOT = Path(__file__).resolve().parents[2]
_EXECUTOR_PATH = REPO_ROOT / "agri_ai_core" / "src" / "ai" / "tools_executor.py"


def _registered_tool_names() -> set:
    """tools_definition 의 get_available_tools 에서 노출된 도구명 집합."""
    return {t["function"]["name"] for t in get_available_tools()}


def _executor_dispatched_tool_names() -> set:
    """tools_executor.py 에서 `tool_name == "..."` 또는 `elif tool_name == "..."`
    으로 dispatch 되는 도구명 집합을 정적 분석."""
    text = _EXECUTOR_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"tool_name\s*==\s*[\"']([a-z_]+)[\"']")
    return set(pattern.findall(text))


# ──── 등록 일관성 테스트 ────────────────────────────────────────────
class TestToolRegistrationConsistency:
    def test_every_schema_tool_has_executor_dispatch(self):
        """LLM 에 노출된 모든 도구는 executor dispatch 가 있어야 한다."""
        schema = _registered_tool_names()
        dispatched = _executor_dispatched_tool_names()
        missing = schema - dispatched
        assert not missing, f"executor dispatch 누락: {sorted(missing)}"

    def test_every_schema_tool_in_valid_tools(self):
        """LLM 에 노출된 도구는 analyzer _VALID_TOOLS 에 전부 있어야 한다."""
        schema = _registered_tool_names()
        missing = schema - _VALID_TOOLS
        assert not missing, f"_VALID_TOOLS 누락: {sorted(missing)}"

    def test_no_orphan_valid_tools(self):
        """_VALID_TOOLS 에 있으나 스키마에 없는 도구는 오타 또는 제거 누락 가능."""
        schema = _registered_tool_names()
        orphans = _VALID_TOOLS - schema
        assert not orphans, f"_VALID_TOOLS 잔존(스키마 미등록): {sorted(orphans)}"


# ──── 권한/컨텍스트 자동 주입 커버리지 ──────────────────────────────
class TestDefaultContextCoverage:
    """농장 제어·관리 성격의 도구는 auth_farm_id 자동 주입이 반드시 필요하다.
    TOOL_DEFAULT_CONTEXT 에 'auth_farm_id': True 를 두지 않으면 농장관리자의
    권한 검증이 우회될 수 있다."""

    # 농장 제어·관리 성격 도구 — 이 리스트는 향후 새 제어 도구 추가 시 보강 필수
    _ADMIN_TOOLS_REQUIRING_AUTH = {
        "control_relay",
        "set_house_control_mode",
        "set_growth_stage",
        "set_circulation_mode",
        "set_schedule",
    }

    def test_admin_tools_require_auth_farm_id_default(self):
        for tool in self._ADMIN_TOOLS_REQUIRING_AUTH:
            spec = TOOL_DEFAULT_CONTEXT.get(tool)
            assert spec is not None, f"{tool} 이 TOOL_DEFAULT_CONTEXT 에 누락"
            assert spec.get("auth_farm_id") is True, (
                f"{tool} 에 auth_farm_id 자동 주입 누락 → 권한 검증 우회 가능"
            )


# ──── LLM 스키마가 내부 전용 파라미터를 노출하지 않는지 ─────────────
class TestSchemaDoesNotLeakInternalParams:
    """auth_farm_id 는 서버가 세션 컨텍스트로만 주입해야 한다. LLM 스키마에
    노출되면 LLM 이 임의 지정 가능 → 권한 우회 가능."""

    _INTERNAL_PARAM = "auth_farm_id"

    def test_no_tool_exposes_auth_farm_id(self):
        exposed = []
        for t in get_available_tools():
            fn = t.get("function", {})
            params = fn.get("parameters", {}) or {}
            props = params.get("properties", {}) or {}
            if self._INTERNAL_PARAM in props:
                exposed.append(fn.get("name"))
        assert not exposed, (
            f"{self._INTERNAL_PARAM} 을 LLM 에 노출하는 도구: {exposed} — 권한 우회 위험"
        )
