# ══════════════════════════════════════════════════════════════════════════════
# 제어 단순화 — 물리값/정합 수정 회귀 테스트 (2026-07-19)
#   #3 저온비상 fog hysteresis 를 정상 경로와 동일 +5℃ 로 통일
#   #5 3호 수온 상한 임계 28→40℃ (형제 호기와 정합)
# ══════════════════════════════════════════════════════════════════════════════
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
from agri_ai_core.src.control.environment_logic import _check_emergency, LOWTEMP_FOG_HYST_C
from agri_ai_core.src.control.ai_thresholds import get_thresholds


def _sensors(indoor, water):
    return {'indoor_temperature': indoor, 'indoor_humidity': 80, 'co2': 700,
            'outdoor_temperature': 5, 'outdoor_humidity': 65, 'water_temperature': water}


def test_lowtemp_fog_hysteresis_is_5c():
    assert LOWTEMP_FOG_HYST_C == 5.0


def test_lowtemp_emergency_fog_off_below_5c():
    # 저온비상(실내<임계하한), 수온 = 실내+4℃ (<+5) → fog OFF, heater ON
    ts = get_thresholds(1, 1)
    lo = ts.temp_critical_low
    is_e, dev, circ, _ = _check_emergency(_sensors(lo - 2, (lo - 2) + 4), ts)
    assert is_e is True
    assert dev['water_heater_flag'] is True
    assert dev['fog_occurs_flag'] is False   # +4℃ 는 +5 미만 → 포그 안 켬


def test_lowtemp_emergency_fog_on_at_5c():
    # 수온 = 실내+6℃ (≥+5) → fog ON
    ts = get_thresholds(1, 1)
    lo = ts.temp_critical_low
    is_e, dev, circ, _ = _check_emergency(_sensors(lo - 2, (lo - 2) + 6), ts)
    assert dev['fog_occurs_flag'] is True


def test_house3_water_temp_high_is_40():
    assert get_thresholds(1, 3).water_temp_high == 40.0
