import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_user_prompt_uses_pin_mapping_for_current_relay_state():
    from agri_ai_core.src.control.ai_control import _build_user_prompt
    from agri_ai_core.src.control.control_common import get_pin_map

    pin_map = get_pin_map(2)
    current_relay = {
        pin_map["water_heater_flag"]: True,
        pin_map["fog_occurs_flag"]: False,
        pin_map["drainage_motor_flag"]: False,
    }
    prompt = _build_user_prompt(
        {
            "indoor_temperature": 20.0,
            "indoor_humidity": 80.0,
            "co2": 600,
            "outdoor_temperature": 10.0,
            "outdoor_humidity": 70.0,
            "water_temperature": 26.0,
        },
        current_relay,
        "생육기",
        {},
        "",
        2,
    )

    assert "water_heater_flag=ON" in prompt
    assert "fog_occurs_flag=OFF" in prompt
    assert "drainage_motor_flag=OFF" in prompt
    assert "룰 1 준수: 수온히터 ON ↔ 배수밸브 OFF" in prompt


def test_ai_control_schema_requires_drainage_motor():
    from agri_ai_core.src.control.ai_control import RELAY_RESPONSE_SCHEMA

    required = RELAY_RESPONSE_SCHEMA["properties"]["devices"]["required"]
    assert "drainage_motor_flag" in required


def test_system_prompt_uses_single_fog_hysteresis_threshold():
    from agri_ai_core.src.control.ai_control import _build_system_prompt

    prompt = _build_system_prompt("생육기")
    # fog hysteresis 는 +5℃ 로 통일 (절대 룰 3, CTRL_ROLE) — +3℃ 잔존 금지
    assert "실내온도 + 5℃" in prompt
    assert "실내 + 3℃" not in prompt
    assert "실내+3℃" not in prompt
