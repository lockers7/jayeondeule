# 고습 → 포그 강제 OFF 가드 (농장주 절대룰). 냉각 상황(고온/여름 외부≥29)은 예외로 유지. (2026-07-20)
import types
from agri_ai_core.src.control.environment_logic import apply_humidity_fog_guard, WS_OUTDOOR_HOT_C

TS = types.SimpleNamespace(humidity_high=94.0, temp_high=28.0)
PIN = {"fog_occurs_flag": "relay_2st_flag"}

def _rv(fog=True): return {"relay_2st_flag": fog, "relay_6st_flag": True}

def test_highhum_nocool_forces_fog_off():
    rv, corr = apply_humidity_fog_guard(_rv(True),
        {"indoor_humidity": 100.0, "indoor_temperature": 25.0, "outdoor_temperature": 20.0}, TS, PIN)
    assert rv["relay_2st_flag"] is False and corr  # 고습+냉각아님 → 포그 OFF

def test_hightemp_cooling_keeps_fog():
    rv, corr = apply_humidity_fog_guard(_rv(True),
        {"indoor_humidity": 100.0, "indoor_temperature": 30.0, "outdoor_temperature": 20.0}, TS, PIN)
    assert rv["relay_2st_flag"] is True and not corr  # 고온 냉각 → 포그 유지

def test_summer_cooling_keeps_fog():
    rv, corr = apply_humidity_fog_guard(_rv(True),
        {"indoor_humidity": 100.0, "indoor_temperature": 25.0, "outdoor_temperature": WS_OUTDOOR_HOT_C + 1}, TS, PIN)
    assert rv["relay_2st_flag"] is True and not corr  # 여름(외부≥29) → 포그 유지

def test_low_humidity_keeps_fog():
    rv, corr = apply_humidity_fog_guard(_rv(True),
        {"indoor_humidity": 70.0, "indoor_temperature": 25.0, "outdoor_temperature": 20.0}, TS, PIN)
    assert rv["relay_2st_flag"] is True and not corr  # 저습 → 포그 유지(가습 가능)

def test_fog_already_off_noop():
    rv, corr = apply_humidity_fog_guard(_rv(False),
        {"indoor_humidity": 100.0, "indoor_temperature": 25.0, "outdoor_temperature": 20.0}, TS, PIN)
    assert rv["relay_2st_flag"] is False and not corr
