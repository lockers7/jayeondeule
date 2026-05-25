# ════════════════════════════════════════════════════════════════════
# [Phase A · 2026-05-04] _emergency_override / apply_emergency_override 단위 테스트
# 사용자 원칙 검증: 비상 가드는 위반 항목만 강제, 운용모드 결정은 보존.
#
# 파일 시작 함수 목록:
#   _ts_obj                                : 임계값 mock helper
#   test_no_emergency_returns_user_decision: 비상 미트립 시 운용 결정 그대로
#   test_low_temp_overrides_only_heater    : #1 저온비상 — heater 만 강제
#   test_high_temp_normal_outdoor_external : #2 고온비상 + 외기 정상 → 외부순환
#   test_high_temp_abnormal_outdoor_exhaust: #2 고온비상 + 외기 부적합 → 배기순환
#   test_co2_high_circulation_only         : #7 CO2 비상 — circulation 만 강제
#   test_water_temp_low_heater_drainage    : #6 수온저하 — heater + drainage 강제
#   test_water_temp_high_indoor_normal     : #4 수온과열 + 실내 정상 → heater 만
#   test_water_temp_high_indoor_hot        : #4 수온과열 + 실내 고온 → heater + drainage
#   test_apply_preserves_user_fog          : 운용모드의 fog 결정이 비상에 의해 변경 안 됨
# ════════════════════════════════════════════════════════════════════
import sys

sys.path.insert(0, '/workspace/jayeondeule')

from agri_ai_core.src.control.environment_logic import (
    _emergency_override, apply_emergency_override,
)


# ────────────────────────────────────────────────────────────────────
# 임계값 mock — sensor_m_setting 같은 설정 모방
# ────────────────────────────────────────────────────────────────────
class _TS:
    temp_low, temp_high = 25.0, 28.0
    temp_critical_low, temp_critical_high = 24.0, 31.0
    humidity_low, humidity_high = 70.0, 95.0
    humidity_critical_low, humidity_critical_high = 50.0, 101.0
    water_temp_low, water_temp_high = 20.0, 40.0
    water_temp_critical_low, water_temp_critical_high = 15.0, 45.0
    co2_critical_high = 2500.0


def _ts_obj():
    return _TS()


# ────────────────────────────────────────────────────────────────────
# 비상 미트립 — devices override 빈 dict, circulation None
# ────────────────────────────────────────────────────────────────────
def test_no_emergency_returns_user_decision():
    sensor = {'indoor_temperature': 26, 'indoor_humidity': 80,
              'co2': 1000, 'water_temperature': 35, 'outdoor_temperature': 25}
    is_e, dev, circ, wto = _emergency_override(sensor, _ts_obj())
    assert is_e is False
    assert dev == {}
    assert circ is None


# ────────────────────────────────────────────────────────────────────
# #1 저온비상 — water_heater_flag 만 강제 ON. fog/drainage 미명시 (보존).
# ────────────────────────────────────────────────────────────────────
def test_low_temp_overrides_only_heater():
    sensor = {'indoor_temperature': 22, 'water_temperature': 30}
    is_e, dev, circ, _ = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {'water_heater_flag': True}
    assert circ == '내부순환'
    assert 'fog_occurs_flag' not in dev
    assert 'drainage_motor_flag' not in dev


# ────────────────────────────────────────────────────────────────────
# #2 고온비상 + 외기 정상 — heater OFF 강제 + 외부순환
# ────────────────────────────────────────────────────────────────────
def test_high_temp_normal_outdoor_external():
    sensor = {'indoor_temperature': 32, 'outdoor_temperature': 26}
    is_e, dev, circ, _ = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {'water_heater_flag': False}
    assert circ == '외부순환'


# ────────────────────────────────────────────────────────────────────
# #2 고온비상 + 외기 부적합 — heater OFF + 배기순환 (능동냉각은 운용에 위임)
# ────────────────────────────────────────────────────────────────────
def test_high_temp_abnormal_outdoor_exhaust():
    sensor = {'indoor_temperature': 32, 'outdoor_temperature': 35}
    is_e, dev, circ, _ = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {'water_heater_flag': False}
    assert circ == '배기순환'


# ────────────────────────────────────────────────────────────────────
# #7 CO2 비상 — devices 빈 dict, circulation 만 오버라이드
# ────────────────────────────────────────────────────────────────────
def test_co2_high_circulation_only():
    sensor = {'indoor_temperature': 26, 'outdoor_temperature': 26, 'co2': 2600}
    is_e, dev, circ, _ = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {}
    assert circ == '외부순환'


# ────────────────────────────────────────────────────────────────────
# #6 수온저하 — heater ON + drainage OFF (가온 위해 물 가둠). fog 미명시.
# ────────────────────────────────────────────────────────────────────
def test_water_temp_low_heater_drainage():
    sensor = {'indoor_temperature': 26, 'water_temperature': 14}
    is_e, dev, circ, wto = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {'water_heater_flag': True, 'drainage_motor_flag': False}
    assert circ is None
    assert wto is True


# ────────────────────────────────────────────────────────────────────
# #4 수온과열 + 실내 가열 필요/정상 — heater OFF 만. fog/drainage 보존.
# ────────────────────────────────────────────────────────────────────
def test_water_temp_high_indoor_normal():
    sensor = {'indoor_temperature': 26, 'water_temperature': 47}
    is_e, dev, circ, wto = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {'water_heater_flag': False}
    assert wto is True


# ────────────────────────────────────────────────────────────────────
# #4 수온과열 + 실내 고온 — heater OFF + drainage ON (능동냉각).
# ────────────────────────────────────────────────────────────────────
def test_water_temp_high_indoor_hot():
    sensor = {'indoor_temperature': 30, 'water_temperature': 47}
    is_e, dev, circ, wto = _emergency_override(sensor, _ts_obj())
    assert is_e is True
    assert dev == {'water_heater_flag': False, 'drainage_motor_flag': True}
    assert wto is True


# ────────────────────────────────────────────────────────────────────
# apply_emergency_override — 운용모드의 fog 결정이 비상에 의해 변경 안 됨.
# 저온비상에서도 LLM 의 fog 결정 그대로 보존.
# ────────────────────────────────────────────────────────────────────
def test_apply_preserves_user_fog():
    sensor = {'indoor_temperature': 22, 'water_temperature': 30}
    user_devices = {
        'water_heater_flag': False,  # 운용 결정: heater OFF
        'fog_occurs_flag': True,      # 운용 결정: fog ON (LLM 자율)
        'drainage_motor_flag': True,  # 운용 결정: drainage ON
    }
    final, circ, is_e = apply_emergency_override(user_devices, '배기순환', sensor, _ts_obj())
    assert is_e is True
    # heater 만 비상에 의해 강제 ON
    assert final['water_heater_flag'] is True
    # fog 와 drainage 는 운용 결정 그대로 보존
    assert final['fog_occurs_flag'] is True
    assert final['drainage_motor_flag'] is True
    # circulation 은 비상이 우선
    assert circ == '내부순환'
