# ══════════════════════════════════════════════════════════════════════════
# LLM 제어 도구 권한/안전 가드 단위 테스트 (회귀 방지).
# DB/HTTP 의존성 없이 순수 함수 단위로만 검증한다.
# ══════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.ai.tools_auth import (
    require_non_zero_house,
    check_farm_access,
    check_house_control_access,
)


# ──── 0호 거부 가드 ────────────────────────────────────────────────
class TestRequireNonZeroHouse:
    @pytest.mark.parametrize("val", ["0", 0, "통합재배사", "공통", "", None])
    def test_rejects_zero_or_empty(self, val):
        err = require_non_zero_house(val)
        assert err is not None
        assert err["success"] is False

    @pytest.mark.parametrize("val", ["1", "2", "3", "all", "전체"])
    def test_accepts_valid(self, val):
        assert require_non_zero_house(val) is None


# ──── 농장 접근권 검증 ─────────────────────────────────────────────
class TestCheckFarmAccess:
    @pytest.mark.parametrize("auth", [None, "", "0"])
    def test_system_admin_all_farms(self, auth):
        # 시스템관리자는 어떤 target 에도 통과
        assert check_farm_access(auth, "1") is None
        assert check_farm_access(auth, "99") is None

    def test_farm_admin_own_farm(self):
        assert check_farm_access("1", "1") is None

    def test_farm_admin_other_farm_rejected(self):
        err = check_farm_access("1", "2")
        assert err is not None
        assert err["success"] is False
        assert "권한" in err["error"]


# ──── 통합 진입 가드 ───────────────────────────────────────────────
class TestCheckHouseControlAccess:
    def test_system_admin_house_1_ok(self):
        assert check_house_control_access(None, "1", "1") is None

    def test_farm_admin_own_farm_house_ok(self):
        assert check_house_control_access("1", "1", "2") is None

    def test_zero_house_rejected_regardless_of_auth(self):
        err = check_house_control_access(None, "1", "0")
        assert err is not None
        err2 = check_house_control_access("1", "1", "0")
        assert err2 is not None

    def test_other_farm_rejected(self):
        err = check_house_control_access("1", "2", "1")
        assert err is not None
        assert "권한" in err["error"]

    def test_all_allowed_by_default(self):
        # 기본 allow_all=True 이면 'all' 통과 + 권한 검증만 수행
        assert check_house_control_access(None, "1", "all") is None
        assert check_house_control_access("1", "1", "all") is None

    def test_all_rejected_when_disabled(self):
        # set_schedule 처럼 단건 전용 도구는 allow_all=False 로 'all' 거부
        err = check_house_control_access("1", "1", "all", allow_all=False)
        assert err is not None
        assert err["success"] is False
