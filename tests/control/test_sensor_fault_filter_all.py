# ══════════════════════════════════════════════════════════════════════════════
# test_sensor_fault_filter_all — 센서 결함필터 전 센서 검증
#
# RPi 는 센서 읽기실패 시 0.0 폴백 기록. 0.0 이 비상가드에 "저온비상" 등으로
# 오인되지 않도록 결함필터가 실내/실외 온도·습도·CO2 를 None 처리해야 한다.
#
# 파일 시작 함수 목록:
#   test_indoor_zero_filtered      : 실내온도 0.0 → None
#   test_outdoor_zero_filtered     : 실외온도 0.0 → None
#   test_humidity_zero_filtered    : 습도 0.0 → None / 100.0 은 실측이므로 통과
#   test_co2_zero_filtered         : CO2 0.0 → None
#   test_water_legacy_kept         : 수온 기존 규칙(-454 등) 유지
#   test_normal_values_pass        : 정상값 무변경 (음수 실외온도 포함)
#   test_emergency_guard_skips_none: None 실내온도로 비상가드 미발동 (E2E 핵심)
#   test_prompt_marks_fault        : 프롬프트에 측정불가+판단근거 안내 표기
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

from agri_ai_core.src.postgresql import reader as R


def _row(**over):
    base = {
        'record_datetime': '2026-07-04 15:33:06',
        'indoor_temperature': 28.058, 'indoor_humidity': 100.0,
        'outdoor_temperature': 22.0, 'outdoor_humidity': 95.5,
        'co2': 1570.0, 'water_temperature': 18.75,
        'light_level': 0, 'water_level': 0,
    }
    base.update(over)
    return base


def _filtered(**over):
    with patch.object(R, '_db_query', return_value=_row(**over)):
        return R.read_current_sensor_info(1, 1)


def test_indoor_zero_filtered():
    out = _filtered(indoor_temperature=0.0)
    assert out['indoor_temperature'] is None      # 폴백값 0.0 → None
    assert out['water_temperature'] == 18.75      # 다른 값 무변경


def test_outdoor_zero_filtered():
    assert _filtered(outdoor_temperature=0.0)['outdoor_temperature'] is None


def test_humidity_zero_filtered():
    out = _filtered(indoor_humidity=0.0, outdoor_humidity=0.0)
    assert out['indoor_humidity'] is None
    assert out['outdoor_humidity'] is None
    # 습도 100.0 은 실측(현장 상시 발생) — 통과해야 함
    assert _filtered(indoor_humidity=100.0)['indoor_humidity'] == 100.0


def test_co2_zero_filtered():
    assert _filtered(co2=0.0)['co2'] is None
    assert _filtered(co2=4287.0)['co2'] == 4287.0  # 고농도 실측 통과


def test_water_legacy_kept():
    assert _filtered(water_temperature=-454.0)['water_temperature'] is None
    assert _filtered(water_temperature=0.0)['water_temperature'] is None
    assert _filtered(water_temperature=22.7)['water_temperature'] == 22.7


def test_normal_values_pass():
    out = _filtered()
    assert out['indoor_temperature'] == 28.058
    # 겨울 실외 영하 실측은 통과 (0.0 정확값만 폴백으로 간주)
    assert _filtered(outdoor_temperature=-5.3)['outdoor_temperature'] == -5.3


def test_emergency_guard_skips_none():
    # E2E: 실내온도 결함(None) 이면 저온비상 미발동 → 히터 강제 ON 없음
    from agri_ai_core.src.control.environment_logic import _emergency_override
    from agri_ai_core.src.control.ai_thresholds import get_thresholds
    sensor = _filtered(indoor_temperature=0.0)      # 필터 통과 후 None
    ts = get_thresholds(1, 1)
    is_e, dev, circ, _ = _emergency_override(sensor, ts)
    assert not (is_e and dev.get('water_heater_flag') is True), \
        "결함값(None) 실내온도로 저온비상(히터 ON)이 발동하면 안 됨"


def test_prompt_marks_fault():
    from agri_ai_core.src.control.ai_control import _build_user_prompt
    sensor = _filtered(indoor_temperature=0.0)
    prompt = _build_user_prompt(sensor, {}, '수확기', {}, '', 1)
    assert "내부온도=측정불가(센서장애)" in prompt
    assert "실내온도 센서 장애(순간 결함)" in prompt
    assert "None" not in prompt.split("생육단계")[0]  # 센서 라인에 None 미노출
