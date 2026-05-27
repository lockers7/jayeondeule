# ══════════════════════════════════════════════════════════════════════════
# default_tool_args 선언형 빌더 회귀 테스트.
# 새 도구 추가 시 farm_id/auth_farm_id 누락 재발 방지.
# ══════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.ai.tools_utils import (
    TOOL_DEFAULT_CONTEXT,
    build_default_tool_args,
)


class TestDeclarativeSpec:
    """TOOL_DEFAULT_CONTEXT 명세 자체 검증."""

    def test_all_admin_tools_registered(self):
        """관리 도구는 반드시 등록되어 있어야 한다."""
        required = {
            "set_house_control_mode",
            "set_growth_stage",
            "set_circulation_mode",
            "set_schedule",
        }
        assert required.issubset(TOOL_DEFAULT_CONTEXT.keys())

    def test_admin_tools_get_farm_and_auth(self):
        """관리 도구는 farm_id + auth_farm_id 둘 다 자동 주입되어야 한다."""
        for tool in ("set_house_control_mode", "set_growth_stage",
                     "set_circulation_mode", "set_schedule"):
            spec = TOOL_DEFAULT_CONTEXT[tool]
            assert spec.get("farm_id") is True, f"{tool} farm_id 누락"
            assert spec.get("auth_farm_id") is True, f"{tool} auth_farm_id 누락"


class TestBuildDefaultToolArgs:
    def test_farm_manager_session(self):
        out = build_default_tool_args(farm_id="1", house_id="1", auth_farm_id="1")
        assert out["control_relay"] == {"farm_id": "1", "house_id": "1", "auth_farm_id": "1"}
        assert out["set_house_control_mode"] == {"farm_id": "1", "auth_farm_id": "1"}
        assert out["get_system_status"] == {"farm_id": "1"}

    def test_system_admin_no_auth(self):
        out = build_default_tool_args(farm_id="1", house_id=None, auth_farm_id=None)
        # auth_farm_id 가 None 이면 entry 에 키 자체 없음
        assert "auth_farm_id" not in out["control_relay"]
        assert "house_id" not in out["control_relay"]
        assert out["control_relay"]["farm_id"] == "1"

    def test_file_name_propagation(self):
        out = build_default_tool_args(farm_id="1", house_id=None, auth_farm_id="1",
                                       file_name="manual.pdf")
        assert out["search_farm_knowledge"]["file_name"] == "manual.pdf"
        assert out["delete_farm_knowledge"]["file_name"] == "manual.pdf"
        # file_name 은 다른 도구엔 주입 안 됨 (선언 없음)
        assert "file_name" not in out["control_relay"]
        assert "file_name" not in out["set_house_control_mode"]

    def test_empty_session(self):
        out = build_default_tool_args()
        # 세션 컨텍스트 모두 없으면 각 도구는 빈 dict
        for tool, entry in out.items():
            assert isinstance(entry, dict)
            # None 값은 주입되지 않음 → 모든 값이 있으면 truthy
            for k, v in entry.items():
                assert v is not None

    def test_get_farm_realtime_data_house_context(self):
        out = build_default_tool_args(farm_id="1", house_id="2")
        assert out["get_farm_realtime_data"] == {"farm_id": "1", "house_id": "2"}
        # auth_farm_id 는 이 도구엔 주입되지 않음 (조회 도구, 권한 가드 없음)
        assert "auth_farm_id" not in out["get_farm_realtime_data"]
