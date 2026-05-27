# ══════════════════════════════════════════════════════════════════════════════
# test_tools_data_judgment_separation
#   — get_farm_realtime_data 의 AI/알고리즘 모드 권장값 분리
#
# AI 모드 호기에서 *현재 상태* 와 *알고리즘 64케이스 권장* 이 동시 노출되면
# LLM 이 모순 답변을 생성하므로, 모드별로 권장값 노출을 분리한다.
#
# 검증 목표:
#   · AI 모드 호기 → algorithm_proposed_next_cycle 미포함
#   · 알고리즘 호기 → algorithm_proposed_next_cycle 포함 + meta 라벨
#   · relay_mapping_meta 항상 포함 (현재 상태 라벨 명시)
#   · control_mode 항상 노출
#
# 파일 시작 함수 목록:
#   TestAiModeBlocksProposal      : ctrl_type='ai' → 차단
#   TestAlgorithmModeIncludes     : ctrl_type='algorithm' → 포함
#   TestRelayMappingMeta          : relay_mapping_meta 라벨 검증
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

import pytest

from agri_ai_core.src.ai import tools_data


SENSOR_FIXTURE = {
    "record_datetime": "2026-06-06 17:40",
    "indoor_temperature": 24.5,
    "indoor_humidity": 70.0,
    "outdoor_temperature": 26.0,
    "outdoor_humidity": 60.0,
    "co2": 500.0,
    "water_temperature": 19.0,
    "light_level": 100.0,
}
RELAY_FIXTURE = {
    "relay_1st_flag": True,
    "relay_2st_flag": False,
    "relay_3st_flag": False,
    "relay_5st_flag": False,
    "relay_6st_flag": True,
}
JUDGMENT_FIXTURE = {
    "sensor": "온도 24.5℃",
    "growth_stage": "수확기",
    "reason": "64케이스",
    "devices": {"water_heater_flag": False, "drainage_motor_flag": True},
    "circulation": "외부순환",
    "device_summary": "ON=[배수밸브], OFF=[수온히터]",
}


# ────────────────────────────────────────────────────────────────────
# 공통 mock 헬퍼 — DB·센서·릴레이·판단 모두 격리
# ────────────────────────────────────────────────────────────────────
def _patch_common(ctrl_type: str):
    """get_farm_realtime_data 의 외부 의존성 일괄 mock."""
    class _FakeDB:
        def fetch_one(self, query=None, vals=None):
            if "ctrl_type" in (query or ""):
                return {"ctrl_type": ctrl_type}
            return {"farm_id": "1", "hous_id": "1"}
        def fetch_all(self, *a, **k):
            return []

    class _FakeDBCtx:
        def __enter__(self_inner):
            return _FakeDB()
        def __exit__(self_inner, *a):
            return False

    return [
        patch(
            "agri_ai_core.src.postgresql.connection.db_session",
            return_value=_FakeDBCtx(),
        ),
        patch(
            "agri_ai_core.src.postgresql.reader.read_current_sensor_info",
            return_value=SENSOR_FIXTURE,
        ),
        patch(
            "agri_ai_core.src.postgresql.reader.read_latest_relay_info",
            return_value=RELAY_FIXTURE,
        ),
        patch(
            "agri_ai_core.src.control.manual_control.get_ai_environment_judgment",
            return_value=JUDGMENT_FIXTURE,
        ),
    ]


# ────────────────────────────────────────────────────────────────────
# AI 모드 → algorithm_proposed_next_cycle 차단
# ────────────────────────────────────────────────────────────────────
class TestAiModeBlocksProposal:
    def test_ai_mode_skips_proposal(self):
        patches = _patch_common(ctrl_type="ai")
        for p in patches: p.start()
        try:
            r = tools_data.get_farm_realtime_data(
                house_id="1", farm_id="1", data_type="all"
            )
        finally:
            for p in patches: p.stop()

        assert r.get("success") is True
        assert r.get("control_mode") == "ai"
        assert "algorithm_proposed_next_cycle" not in r, \
            "AI 모드 호기는 알고리즘 권장값 노출 금지"
        assert "algorithm_proposed_skipped" in r, "차단 사유 명시 필요"


# ────────────────────────────────────────────────────────────────────
# 알고리즘 모드 → algorithm_proposed_next_cycle 포함 + meta
# ────────────────────────────────────────────────────────────────────
class TestAlgorithmModeIncludes:
    def test_algorithm_mode_includes_proposal(self):
        patches = _patch_common(ctrl_type="algorithm")
        for p in patches: p.start()
        try:
            r = tools_data.get_farm_realtime_data(
                house_id="1", farm_id="1", data_type="all"
            )
        finally:
            for p in patches: p.stop()

        assert r.get("control_mode") == "algorithm"
        assert "algorithm_proposed_next_cycle" in r
        assert r["algorithm_proposed_next_cycle"]["circulation"] == "외부순환"
        meta = r.get("algorithm_proposed_meta", {})
        assert "미적용" in meta.get("label", "")
        assert "relay_mapping" in meta.get("warning", "")


# ────────────────────────────────────────────────────────────────────
# relay_mapping_meta 항상 명시 (현재 상태 라벨)
# ────────────────────────────────────────────────────────────────────
class TestRelayMappingMeta:
    def test_meta_present_with_label(self):
        patches = _patch_common(ctrl_type="ai")
        for p in patches: p.start()
        try:
            r = tools_data.get_farm_realtime_data(
                house_id="1", farm_id="1", data_type="all"
            )
        finally:
            for p in patches: p.stop()

        meta = r.get("relay_mapping_meta", {})
        assert "현재" in meta.get("label", "")
        assert "snapshot" in meta.get("label", "").lower() or "적용" in meta.get("label", "")
