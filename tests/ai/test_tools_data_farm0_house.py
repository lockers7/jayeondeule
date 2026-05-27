# ══════════════════════════════════════════════════════════════════════════════
# test_tools_data_farm0_house.py — farm_id=0 교체 시 house_id 보존 검증
#
# get_farm_realtime_data 는 farm_id=0 → 1 대체 과정에서 house_id 가
# 숫자 문자열("1","2","3" 등)이면 보존해야 한다 — 초기화되면 1호기
# 자동선택으로 2·3호기 데이터 조회가 불가해진다.
#
# 파일 시작 함수 목록:
#   _patch_all                   : 외부 의존성 일괄 mock 헬퍼
#   TestFarm0HouseIdPreservation : house_id 보존/초기화 경계 케이스
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

import pytest

from agri_ai_core.src.ai import tools_data

SENSOR_FIXTURE = {
    "record_datetime": "2026-06-28 07:00",
    "indoor_temperature": 24.0,
    "indoor_humidity": 70.0,
    "outdoor_temperature": 20.0,
    "outdoor_humidity": 55.0,
    "co2": 500.0,
    "water_temperature": 18.0,
    "light_level": 100.0,
}
RELAY_FIXTURE = {
    "relay_1st_flag": False,
    "relay_2st_flag": False,
    "relay_3st_flag": False,
    "relay_5st_flag": False,
    "relay_6st_flag": False,
}
JUDGMENT_FIXTURE = {
    "sensor": "온도 24.0℃",
    "growth_stage": "성장기",
    "reason": "정상",
    "devices": {"water_heater_flag": False},
    "circulation": "내부순환",
    "device_summary": "OFF=[수온히터]",
}


def _patch_all():
    """get_farm_realtime_data 외부 의존성 일괄 mock."""

    class _FakeDB:
        def fetch_one(self, query=None, vals=None):
            if "ctrl_type" in (query or ""):
                return {"ctrl_type": "ai"}
            # GET_ONE_FARM → farm_id=1 반환
            if "farm_id" in (query or "") and "hous_id" not in (query or ""):
                return {"farm_id": 1}
            # GET_ONE_HOUSE → hous_id=1 반환 (자동조회 fallback)
            return {"farm_id": 1, "hous_id": 1}

        def fetch_all(self, *a, **kw):
            return []

    class _FakeDBCtx:
        def __enter__(self): return _FakeDB()
        def __exit__(self, *a): return False

    return [
        patch("agri_ai_core.src.postgresql.connection.db_session",
              return_value=_FakeDBCtx()),
        patch("agri_ai_core.src.postgresql.reader.read_current_sensor_info",
              return_value=SENSOR_FIXTURE),
        patch("agri_ai_core.src.postgresql.reader.read_latest_relay_info",
              return_value=RELAY_FIXTURE),
        patch("agri_ai_core.src.control.manual_control.get_ai_environment_judgment",
              return_value=JUDGMENT_FIXTURE),
    ]


def _call(farm_id, house_id, data_type="relay"):
    patches = _patch_all()
    for p in patches:
        p.start()
    try:
        return tools_data.get_farm_realtime_data(
            farm_id=farm_id, house_id=house_id, data_type=data_type
        )
    finally:
        for p in patches:
            p.stop()


class TestFarm0HouseIdPreservation:
    def test_house2_preserved_when_farm0(self):
        """farm_id=0 → 1 대체 시 house_id='2' 는 보존되어 2호기 조회."""
        r = _call(farm_id="0", house_id="2")
        assert r.get("success") is True
        assert r.get("house_id") == "2", (
            f"house_id가 '2'여야 하는데 '{r.get('house_id')}' 반환 — 초기화 버그"
        )
        assert r.get("auto_selected") is False

    def test_house3_preserved_when_farm0(self):
        """farm_id=0 → 1 대체 시 house_id='3' 는 보존."""
        r = _call(farm_id="0", house_id="3")
        assert r.get("success") is True
        assert r.get("house_id") == "3"
        assert r.get("auto_selected") is False

    def test_house1_preserved_when_farm0(self):
        """farm_id=0 → 1 대체 시 house_id='1' 보존."""
        r = _call(farm_id="0", house_id="1")
        assert r.get("success") is True
        assert r.get("house_id") == "1"
        assert r.get("auto_selected") is False

    def test_house_none_triggers_auto_select(self):
        """house_id=None 이면 자동조회 (GET_ONE_HOUSE) — 종전 동작 유지."""
        r = _call(farm_id="0", house_id=None)
        assert r.get("success") is True
        assert r.get("auto_selected") is True

    def test_house_all_triggers_auto_select(self):
        """house_id='all' 이면 초기화 후 자동조회 — fan-out 은 상위 레이어 담당."""
        r = _call(farm_id="0", house_id="all")
        assert r.get("success") is True
        assert r.get("auto_selected") is True

    def test_house_zero_triggers_auto_select(self):
        """house_id='0' 이면 초기화 후 자동조회."""
        r = _call(farm_id="0", house_id="0")
        assert r.get("success") is True
        assert r.get("auto_selected") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
