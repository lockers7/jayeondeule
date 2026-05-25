# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 단위테스트 — agent read-only 도구 5종.
# DB 의존 — 운영 DB 의 실 데이터로 검증 (sensor_l_recording, ai_decision_log 등).
# 빈 DB / 신규 환경에서도 "success=True + n=0" 같은 형태로 통과해야.
# ═══════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.ai.tools_agent_read import (
    get_sensor_window, get_recent_decisions, get_relay_state,
    compare_houses, get_thresholds, tool_specs_text,
    TOOL_REGISTRY, TOOL_SPECS,
)


# ════════════════════════════════════════════════════════════════════
# Args validation — DB 호출 전 가벼운 검증
# ════════════════════════════════════════════════════════════════════
class TestArgsValidation:
    def test_get_sensor_window_minutes_range(self):
        assert "error" in get_sensor_window(1, 1, 0)
        assert "error" in get_sensor_window(1, 1, 1441)
        assert "error" in get_sensor_window(1, 1, -5)

    def test_get_sensor_window_type(self):
        assert "error" in get_sensor_window("1", 1, 60)        # farm 이 str
        assert "error" in get_sensor_window(1, "1", 60)        # house 가 str
        assert "error" in get_sensor_window(1, 1, "60")        # minutes 가 str

    def test_get_recent_decisions_hours_range(self):
        assert "error" in get_recent_decisions(1, 1, 0)
        assert "error" in get_recent_decisions(1, 1, 25)

    def test_compare_houses_metric_whitelist(self):
        assert "error" in compare_houses(1, "invalid_metric")
        assert "error" in compare_houses(1, "TEMP")            # 대소문자
        # 정상 metric 은 success 확인 (DB 의존)
        r = compare_houses(1, "co2")
        assert r.get("success") is True

    def test_get_thresholds_type(self):
        assert "error" in get_thresholds(None, 1)
        assert "error" in get_thresholds(1, None)


# ════════════════════════════════════════════════════════════════════
# 실제 DB 호출 — 운영 데이터로 형식 검증 (값 검증 X)
# ════════════════════════════════════════════════════════════════════
class TestRealDB:
    def test_get_sensor_window_shape(self):
        r = get_sensor_window(1, 1, 60)
        assert r.get("success") is True
        assert r["farm"] == 1 and r["house"] == 1 and r["minutes"] == 60
        assert "n" in r
        if r["n"] > 0:
            assert "indoor_temp" in r and "avg" in r["indoor_temp"]
            assert "co2" in r and isinstance(r["co2"]["avg"], (int, float, type(None)))

    def test_get_sensor_window_no_data(self):
        """존재하지 않는 호기 — n=0 정상 반환."""
        r = get_sensor_window(1, 999, 60)
        assert r.get("success") is True
        assert r["n"] == 0

    def test_get_recent_decisions_shape(self):
        r = get_recent_decisions(1, 1, 1)
        assert r.get("success") is True
        assert "total" in r and "change_count" in r and "keep_count" in r
        assert r["change_count"] + r["keep_count"] <= r["total"]   # 정합성
        assert isinstance(r["decisions"], list)
        if r["decisions"]:
            d = r["decisions"][0]
            assert d["action"] in ("change", "keep")

    def test_get_relay_state_shape(self):
        r = get_relay_state(1, 1)
        assert r.get("success") is True
        if "raw_flags" in r:
            assert len(r["raw_flags"]) == 16
            assert all(k.startswith("relay_") for k in r["raw_flags"])
            assert isinstance(r["semantic_on"], list)

    def test_compare_houses_shape(self):
        r = compare_houses(1, "indoor_temp")
        assert r.get("success") is True
        assert r["metric"] == "indoor_temp"
        assert isinstance(r["houses"], list)
        assert isinstance(r["outliers"], list)
        for h in r["houses"]:
            assert "house" in h and "current" in h and "avg_60min" in h

    def test_get_thresholds_shape(self):
        r = get_thresholds(1, 1)
        assert r.get("success") is True
        if "indoor_temp" in r:
            assert "min" in r["indoor_temp"] and "crit_max" in r["indoor_temp"]


# ════════════════════════════════════════════════════════════════════
# TOOL_REGISTRY / TOOL_SPECS 메타데이터 일관성
# ════════════════════════════════════════════════════════════════════
class TestRegistry:
    def test_registry_specs_alignment(self):
        """TOOL_REGISTRY 와 TOOL_SPECS 의 이름 1:1 일치."""
        registry_names = set(TOOL_REGISTRY.keys())
        spec_names = {s["name"] for s in TOOL_SPECS}
        assert registry_names == spec_names

    def test_all_tools_callable(self):
        for name, fn in TOOL_REGISTRY.items():
            assert callable(fn), f"{name} not callable"

    def test_specs_have_args(self):
        for spec in TOOL_SPECS:
            assert "name" in spec
            assert "description" in spec
            assert "args" in spec and isinstance(spec["args"], dict)

    def test_specs_text_nonempty(self):
        txt = tool_specs_text()
        assert isinstance(txt, str) and len(txt) > 0
        for name in TOOL_REGISTRY.keys():
            assert name in txt, f"{name} 가 specs_text 에 누락"


# ════════════════════════════════════════════════════════════════════
# 호출자 시뮬 — agent 가 args dict 로 호출하는 패턴
# ════════════════════════════════════════════════════════════════════
class TestAgentCallPattern:
    def test_kwargs_dispatch(self):
        """agent 가 {'tool': 'X', 'args': {...}} 로 호출하는 패턴 검증."""
        cases = [
            ("get_sensor_window",    {"farm": 1, "house": 1, "minutes": 30}),
            ("get_recent_decisions", {"farm": 1, "house": 1, "hours": 1}),
            ("get_relay_state",      {"farm": 1, "house": 1}),
            ("compare_houses",       {"farm": 1, "metric": "co2"}),
            ("get_thresholds",       {"farm": 1, "house": 1}),
        ]
        for tool_name, args in cases:
            fn = TOOL_REGISTRY[tool_name]
            r = fn(**args)
            assert "success" in r or "error" in r, f"{tool_name} 반환에 success/error 없음"

    def test_extra_args_rejected(self):
        """추가 인자 — TypeError (Python 기본 동작 — agent loop 가 catch)."""
        with pytest.raises(TypeError):
            get_sensor_window(1, 1, 60, extra_arg=True)
