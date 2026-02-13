#!/usr/bin/env python3
"""Focused functional smoke tests for current agri_ai_core modules."""

import sys
import traceback


def test_config_module():
    from agri_ai_core.config import settings, get_sensor_field_mapping, get_relay_field_mapping

    assert settings.database.host
    assert isinstance(settings.database.port, int)
    assert isinstance(get_sensor_field_mapping(), dict)
    assert isinstance(get_relay_field_mapping(), dict)


def test_utils_module():
    from agri_ai_core.src.utils import (
        clean_sensor_value,
        parse_boolean,
        parse_datetime,
        convert_sensor_relay_data,
        extract_relay_data,
    )

    assert clean_sensor_value("25.31℃") == 25.31
    assert parse_boolean("True") is True
    assert parse_boolean("0") is False
    assert parse_datetime("2026-02-14 07:00:00") is not None

    sample = {
        "indoor_temperature_value": "25.0",
        "relay_1st_flag": "true",
        "relay_stats": {"relay_7st_flag": False},
    }
    converted = convert_sensor_relay_data(sample)
    assert "sensor_data" in converted and "relay_data" in converted
    relay_data = extract_relay_data(sample)
    assert relay_data.get("relay_7st_flag") is False


def test_llm_cleaner():
    from agri_ai_core.src.ai.llm_client import clean_llm_response

    raw = """Okay, the user said hello. I should respond nicely.\n\n안녕하세요! 농장 AI입니다."""
    cleaned = clean_llm_response(raw)
    assert "Okay" not in cleaned
    assert "안녕하세요" in cleaned


def test_entrypoints():
    import agri_ai_core
    from agri_ai_core.startup import initialize_app, shutdown_app
    from agri_ai_core.main.main import app

    assert callable(initialize_app)
    assert callable(shutdown_app)
    assert app is not None
    assert agri_ai_core.db_session is not None


def run_all() -> int:
    print("=" * 64)
    print("agri_ai_core complete smoke test")
    print("=" * 64)

    tests = [
        ("Config", test_config_module),
        ("Utils", test_utils_module),
        ("LLM cleaner", test_llm_cleaner),
        ("Entrypoints", test_entrypoints),
    ]

    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"✓ {name}")
        except Exception as exc:
            failed += 1
            print(f"✗ {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    print("-" * 64)
    if failed == 0:
        print("ALL TESTS PASSED")
        return 0
    print(f"FAILED TESTS: {failed}")
    return 1


if __name__ == "__main__":
    sys.exit(run_all())
