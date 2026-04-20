# ══════════════════════════════════════════════════════════════════════════
# [Wave 2 · B2] 히터 쿨다운 경고 헬퍼 회귀 테스트.
# LLM 직접 제어 시 경고만 포함하고 실행은 차단하지 않는지 검증.
# ══════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta

import pytest

from agri_ai_core.src.control import control_common as cc
from agri_ai_core.src.ai.tools_control import _get_heater_cooldown_warning


@pytest.fixture(autouse=True)
def _reset_heater_state():
    cc._heater_state.clear()
    yield
    cc._heater_state.clear()


def _set_on_since(farm_id, house_id, minutes_ago):
    cc._heater_state[(farm_id, int(house_id))] = {
        "on_since": datetime.now() - timedelta(minutes=minutes_ago),
    }


def _set_cooling(farm_id, house_id, minutes_remaining):
    cc._heater_state[(farm_id, int(house_id))] = {
        "cooling_until": datetime.now() + timedelta(minutes=minutes_remaining),
    }


class TestHeaterCooldownWarning:
    def test_normal_on_no_warning(self):
        # 최근 ON 된 히터는 경고 없음
        _set_on_since(1, 1, minutes_ago=5)
        assert _get_heater_cooldown_warning(1, 1, "indoor_heater_flag", "on") is None

    def test_max_continuous_triggers_cooldown_warning(self):
        # 30분+ 경과 후 ON 시도 → cooling 전환, 경고 반환
        _set_on_since(1, 1, minutes_ago=31)
        w = _get_heater_cooldown_warning(1, 1, "indoor_heater_flag", "on")
        assert w is not None
        assert "쿨다운" in w

    def test_cooling_period_on_warning(self):
        _set_cooling(1, 2, minutes_remaining=3)
        w = _get_heater_cooldown_warning(1, 2, "water_heater_flag", "on")
        assert w is not None

    def test_off_action_no_warning(self):
        # OFF 는 안전 이슈 없음
        _set_on_since(1, 1, minutes_ago=31)
        assert _get_heater_cooldown_warning(1, 1, "indoor_heater_flag", "off") is None

    @pytest.mark.parametrize("device", ["lighting_flag", "intake_fan_flag",
                                        "fog_occurs_flag", "irrigation_flag"])
    def test_non_heater_devices_no_warning(self, device):
        _set_cooling(1, 1, minutes_remaining=3)
        assert _get_heater_cooldown_warning(1, 1, device, "on") is None

    def test_unknown_device_no_warning(self):
        assert _get_heater_cooldown_warning(1, 1, "unknown_flag", "on") is None
