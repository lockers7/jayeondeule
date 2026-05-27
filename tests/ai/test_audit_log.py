# ══════════════════════════════════════════════════════════════════════════
# 도구 호출 추적성 감사 로그 회귀 테스트.
# ══════════════════════════════════════════════════════════════════════════
import json

import pytest

from agri_ai_core.src.ai.pipeline.data_collector import DataCollector


@pytest.fixture
def dc():
    return DataCollector(default_tool_args={"get_farm_realtime_data": {"farm_id": "1"}})


class TestSanitize:
    def test_auth_farm_id_masked(self, dc):
        out = dc._sanitize_args_for_audit({
            "farm_id": "1", "house_id": "2", "auth_farm_id": "1",
        })
        assert out["auth_farm_id"] == "***"
        assert out["farm_id"] == "1"
        assert out["house_id"] == "2"

    def test_empty_dict(self, dc):
        assert dc._sanitize_args_for_audit({}) == {}
        assert dc._sanitize_args_for_audit(None) == {}

    def test_no_auth_key_preserved(self, dc):
        out = dc._sanitize_args_for_audit({"farm_id": "1", "house_id": "1"})
        assert "auth_farm_id" not in out


class TestRecordToolCall:
    def test_success_case(self, dc):
        dc._record_tool_call(
            "control_relay",
            args={"house_id": "1", "device_name": "lighting_flag", "action": "on"},
            raw_result='{"success":true,"house_id":"1","device_name":"lighting_flag"}',
            elapsed=0.12, ok=True,
        )
        e = dc.tool_calls_detail[0]
        assert e["tool"] == "control_relay"
        assert e["success"] is True
        assert e["elapsed_ms"] == 120.0
        assert "error" not in e

    def test_failure_case_captures_error(self, dc):
        dc._record_tool_call(
            "control_relay",
            args={"house_id": "0"},
            raw_result='{"success":false,"error":"house_id=0 거부"}',
            elapsed=0.01, ok=False,
        )
        e = dc.tool_calls_detail[0]
        assert e["success"] is False
        assert "error" in e
        assert "0 거부" in e["error"]

    def test_invalid_json_uses_ok_flag(self, dc):
        dc._record_tool_call(
            "tool_x",
            args={},
            raw_result="not-json",
            elapsed=0.5, ok=True,
        )
        e = dc.tool_calls_detail[0]
        assert e["success"] is True  # ok flag fallback

    def test_multiple_calls_accumulate(self, dc):
        for i in range(3):
            dc._record_tool_call(
                "get_farm_realtime_data",
                args={"house_id": str(i + 1)},
                raw_result=f'{{"success":true,"house_id":"{i+1}"}}',
                elapsed=0.1, ok=True,
            )
        assert len(dc.tool_calls_detail) == 3
        assert [e["args"]["house_id"] for e in dc.tool_calls_detail] == ["1", "2", "3"]
