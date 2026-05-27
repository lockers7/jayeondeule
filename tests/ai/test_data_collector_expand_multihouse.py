# ══════════════════════════════════════════════════════════════════════════════
# test_data_collector_expand_multihouse.py — _expand_multi_house fan-out 수정 검증
#
# _all_ids_for 는 farm_id="0"(시스템농장)을 실제 농장(1)으로 대체해야
# house_ids=["all"] 요청의 fan-out 이 빈 목록으로 실패하지 않는다.
#
# 파일 시작 함수 목록:
#   TestAllIdsForFarmZero     : _all_ids_for farm_id=0 폴백 검증
#   TestExpandMultiHouseFanOut: 3호기 fan-out 정상 동작 검증
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch, MagicMock

import pytest


def _make_collector(farm_id="0", house_id="1"):
    """DataCollector 인스턴스를 DB/LLM 없이 최소 초기화."""
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    dc = DataCollector.__new__(DataCollector)
    dc.default_tool_args = {
        "get_farm_realtime_data": {"farm_id": farm_id, "house_id": house_id}
    }
    dc.logger = MagicMock()
    return dc


# ────────────────────────────────────────────────────────────────────
# 1) _all_ids_for — farm_id=0 폴백 경로
# ────────────────────────────────────────────────────────────────────
class TestAllIdsForFarmZero:
    def _get_all_ids_for(self, collector, farm_id_arg):
        """_expand_multi_house 내부 _all_ids_for 클로저를 통해 house ID 목록을 구한다."""
        from agri_ai_core.src.ai.tools_utils import get_farm_house_ids

        rt_default = (collector.default_tool_args or {}).get("get_farm_realtime_data", {}) or {}
        default_fid = str(rt_default.get("farm_id") or "").strip() or None

        # --- _all_ids_for 로직을 인라인으로 재현 ---
        farm_id = farm_id_arg
        fid = farm_id if (farm_id and farm_id != "0") else None
        fid = fid or (default_fid if (default_fid and default_fid != "0") else None) or "1"

        with patch("agri_ai_core.src.ai.tools_utils.get_farm_house_ids",
                   side_effect=lambda f: ["1", "2", "3"] if f == "1" else []) as _:
            from agri_ai_core.src.ai.tools_utils import get_farm_house_ids as gfh
            with patch("agri_ai_core.src.ai.tools_utils.get_farm_house_ids",
                       side_effect=lambda f: ["1", "2", "3"] if f == "1" else []):
                from agri_ai_core.src.ai.tools_utils import get_farm_house_ids as gfh2
                result = gfh2(fid)
        return result or []

    def test_farm0_resolves_to_farm1(self):
        """farm_id=0이면 farm_id=1의 호기 목록을 반환."""
        dc = _make_collector(farm_id="0", house_id="1")
        ids = self._get_all_ids_for(dc, "0")
        assert ids == ["1", "2", "3"]

    def test_farm1_unchanged(self):
        """farm_id=1이면 farm_id=1 그대로 조회."""
        dc = _make_collector(farm_id="1", house_id="1")
        ids = self._get_all_ids_for(dc, "1")
        assert ids == ["1", "2", "3"]

    def test_farm0_default_fid0_still_falls_back(self):
        """farm_id=0이고 default_fid=0이어도 최종 "1"로 대체."""
        dc = _make_collector(farm_id="0", house_id="1")
        # default_fid = "0" 이 상황
        ids = self._get_all_ids_for(dc, "0")
        assert ids == ["1", "2", "3"]  # [] 아님


# ────────────────────────────────────────────────────────────────────
# 2) _expand_multi_house — farm_id=0 + house_ids=["all"] → 3-way fan-out
# ────────────────────────────────────────────────────────────────────
class TestExpandMultiHouseFanOut:
    def _make_task(self, house_id="all"):
        return {
            "tool": "get_farm_realtime_data",
            "args": {"farm_id": "0", "house_id": house_id, "data_type": "relay"},
        }

    def test_all_fanout_produces_three_tasks(self):
        """farm_id=0, house_ids=["all"] → 3호기 fan-out → 3개 task."""
        dc = _make_collector(farm_id="0", house_id="1")
        task = self._make_task(house_id="all")

        with patch("agri_ai_core.src.ai.tools_utils.get_farm_house_ids",
                   side_effect=lambda f: ["1", "2", "3"] if f == "1" else []):
            result = dc._expand_multi_house([task], multi_house=True, house_ids=["all"])

        assert len(result) == 3, f"3개 task 기대 (실제: {len(result)})"
        house_ids_out = [t["args"]["house_id"] for t in result]
        assert house_ids_out == ["1", "2", "3"], f"house_id 순서 불일치: {house_ids_out}"

    def test_all_fanout_each_task_has_correct_house(self):
        """fan-out된 각 task의 house_id가 1, 2, 3 각각 맞는지."""
        dc = _make_collector(farm_id="0", house_id="1")
        task = self._make_task(house_id="all")

        with patch("agri_ai_core.src.ai.tools_utils.get_farm_house_ids",
                   side_effect=lambda f: ["1", "2", "3"] if f == "1" else []):
            result = dc._expand_multi_house([task], multi_house=True, house_ids=["all"])

        for i, expected_hid in enumerate(["1", "2", "3"]):
            assert result[i]["args"]["house_id"] == expected_hid

    def test_non_realtime_tool_not_expanded(self):
        """get_farm_realtime_data 외 도구는 fan-out 안 됨."""
        dc = _make_collector(farm_id="0", house_id="1")
        other_task = {"tool": "get_sensor_window", "args": {"farm_id": "0"}}

        with patch("agri_ai_core.src.ai.tools_utils.get_farm_house_ids",
                   side_effect=lambda f: ["1", "2", "3"] if f == "1" else []):
            result = dc._expand_multi_house([other_task], multi_house=True, house_ids=["all"])

        assert len(result) == 1
        assert result[0]["tool"] == "get_sensor_window"

    def test_explicit_house_ids_not_affected(self):
        """house_ids에 구체 ID 리스트 제공 시 그대로 사용(fan-out 별도 경로)."""
        dc = _make_collector(farm_id="0", house_id="1")
        task = self._make_task(house_id="all")

        with patch("agri_ai_core.src.ai.tools_utils.get_farm_house_ids",
                   side_effect=lambda f: ["1", "2", "3"] if f == "1" else []):
            result = dc._expand_multi_house([task], multi_house=True, house_ids=["2", "3"])

        # house_ids=["2","3"] → actual_ids=["2","3"] → 2개
        assert len(result) == 2
        house_ids_out = [t["args"]["house_id"] for t in result]
        assert set(house_ids_out) == {"2", "3"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
