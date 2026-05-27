# ══════════════════════════════════════════════════════════════════════════════
# test_device_safety_minimal — 수온계 안전 4케이스(농장주 지정) 검증
#
# 원칙: 제어 판단은 LLM 100% 자율. 코드 개입은 아래 4케이스뿐 —
#   A) 외부 ≤1℃ & 수온 ≥50℃ → 수온 ≤30℃ 될 때까지 수온히터 OFF (락아웃)
#   B) 외부 ≥10℃ → 수온히터 무조건 OFF
#   C) 외부 ≥29℃ → 배수밸브 무조건 ON, 수온이 지하수 온도(15℃±1) 도달 시 포그 ON
#   D) 여름냉각(C)·수온과열 아닌데 포그 OFF+배수 ON → 배수 OFF (배수=포그 세트)
#
# 파일 시작 함수 목록:
#   test_case_a_lockout_trip_hold_release : A — 트립/유지/해제(≤30℃) 사이클
#   test_case_b_warm_outdoor_heater_off   : B — 외부 ≥10℃ 히터 강제 OFF
#   test_case_c_hot_outdoor_cooling       : C — 배수 강제 + 지하수온 도달 시 포그
#   test_no_case_llm_preserved            : 3케이스 밖 LLM 결정 완전 보존
#   test_both_off_is_normal_standby       : 히터 OFF+배수 OFF 무보정 (절대 룰 1)
#   test_keep_repair_uses_water_safety    : keep 결정에도 3케이스 적용/미적용
#   test_case_d_fog_off_drainage_off_pairing : D — 포그 없는 배수 해제 + 예외(포그세트/C/과열)
# ══════════════════════════════════════════════════════════════════════════════
import pytest

from agri_ai_core.src.control import environment_logic as el
from agri_ai_core.src.control import ai_control as ac


@pytest.fixture(autouse=True)
def _clear_lockout():
    el._WS_HEATER_LOCKOUT.clear()
    yield
    el._WS_HEATER_LOCKOUT.clear()


def test_case_a_lockout_trip_hold_release():
    dev = {'water_heater_flag': True, 'drainage_motor_flag': False}
    # 트립: 외부 0℃ + 수온 51℃
    _, corr = el.apply_water_safety(dev, {'outdoor_temperature': 0.0, 'water_temperature': 51.0}, 1, 1)
    assert dev['water_heater_flag'] is False and any('[A]' in c for c in corr)
    # 유지: 수온 40℃ (>30) — 외부가 5℃ 로 올라도 락아웃 지속
    dev2 = {'water_heater_flag': True}
    _, corr2 = el.apply_water_safety(dev2, {'outdoor_temperature': 5.0, 'water_temperature': 40.0}, 1, 1)
    assert dev2['water_heater_flag'] is False and any('[A]' in c for c in corr2)
    # 해제: 수온 29℃ (≤30) → 락아웃 해제, 이후 히터 허용 (외부 <10)
    dev3 = {'water_heater_flag': True}
    _, corr3 = el.apply_water_safety(dev3, {'outdoor_temperature': 5.0, 'water_temperature': 29.0}, 1, 1)
    assert dev3['water_heater_flag'] is True and corr3 == []
    # 재배사별 독립: 다른 호기는 락아웃 무관
    dev4 = {'water_heater_flag': True}
    _, corr4 = el.apply_water_safety(dev4, {'outdoor_temperature': 0.0, 'water_temperature': 40.0}, 1, 2)
    assert dev4['water_heater_flag'] is True and corr4 == []


def test_case_b_warm_outdoor_heater_off():
    dev = {'water_heater_flag': True, 'drainage_motor_flag': False}
    _, corr = el.apply_water_safety(dev, {'outdoor_temperature': 10.0, 'water_temperature': 20.0}, 1, 1)
    assert dev['water_heater_flag'] is False and any('[B]' in c for c in corr)
    # 배수는 건드리지 않음 (배수=포그 세트 — LLM 영역)
    assert dev['drainage_motor_flag'] is False


def test_case_c_hot_outdoor_cooling():
    # 수온 아직 높음(25℃): 배수만 강제, 포그는 LLM 결정 보존
    dev = {'water_heater_flag': False, 'fog_occurs_flag': False, 'drainage_motor_flag': False}
    _, corr = el.apply_water_safety(dev, {'outdoor_temperature': 30.0, 'water_temperature': 25.0}, 1, 1)
    assert dev['drainage_motor_flag'] is True and dev['fog_occurs_flag'] is False
    # 수온이 지하수 온도 도달(15.5℃ ≤ 15+1): 포그 강제 ON
    dev2 = {'fog_occurs_flag': False, 'drainage_motor_flag': True}
    _, corr2 = el.apply_water_safety(dev2, {'outdoor_temperature': 30.0, 'water_temperature': 15.5}, 1, 1)
    assert dev2['fog_occurs_flag'] is True and any('포그 ON' in c for c in corr2)


def test_no_case_llm_preserved():
    # 외부 5℃(1~10 사이) + 수온 45℃ — 어떤 케이스도 미발동, LLM 결정 완전 보존
    for dev in (
        {'water_heater_flag': True, 'fog_occurs_flag': True, 'drainage_motor_flag': False},
        {'water_heater_flag': True, 'drainage_motor_flag': True},   # 동시 ON 도 코드 개입 없음
    ):
        snapshot = dict(dev)
        _, corr = el.apply_water_safety(dev, {'outdoor_temperature': 5.0, 'water_temperature': 45.0}, 1, 1)
        assert corr == [] and dev == snapshot
    # 센서 결함(outdoor None): 보정 없음
    dev = {'water_heater_flag': True}
    _, corr = el.apply_water_safety(dev, {'outdoor_temperature': None, 'water_temperature': 60.0}, 1, 1)
    assert corr == [] and dev['water_heater_flag'] is True


def test_both_off_is_normal_standby():
    dev = {'water_heater_flag': False, 'fog_occurs_flag': False, 'drainage_motor_flag': False}
    _, corr = el.apply_water_safety(dev, {'outdoor_temperature': 5.0, 'water_temperature': 22.0}, 1, 1)
    assert corr == []
    assert dev['drainage_motor_flag'] is False


def test_keep_repair_uses_water_safety(monkeypatch):
    monkeypatch.setattr(ac, "_current_llm_devices",
                        lambda relay, hid: {"water_heater_flag": True,
                                            "fog_occurs_flag": False,
                                            "drainage_motor_flag": False})
    # 외부 12℃ → 케이스 B 발동 → keep 이 change 로 전환
    repair = ac._build_keep_safety_repair({"any": "relay"},
                                          {"outdoor_temperature": 12.0,
                                           "water_temperature": 22.0}, 1, 1)
    assert repair is not None and repair["devices"]["water_heater_flag"] is False
    # 외부 5℃ → 미발동 → None (keep 유지)
    repair2 = ac._build_keep_safety_repair({"any": "relay"},
                                           {"outdoor_temperature": 5.0,
                                            "water_temperature": 22.0}, 1, 1)
    assert repair2 is None


def test_case_d_fog_off_drainage_off_pairing(monkeypatch):
    # D) 여름냉각(C)·수온과열 아닌데 포그 OFF + 배수 ON → 배수 OFF (배수=포그 세트)
    class _TS:
        water_temp_critical_high = 35.0
    monkeypatch.setattr("agri_ai_core.src.control.ai_thresholds.get_thresholds",
                        lambda f, h: _TS())
    # 1호 실제 상황 재현: 외부 23℃, 포그 OFF, 수온 정상, 배수 ON
    dev = {'water_heater_flag': False, 'fog_occurs_flag': False, 'drainage_motor_flag': True}
    _, corr = el.apply_water_safety(dev, {'outdoor_temperature': 23.3, 'water_temperature': 23.9}, 1, 1)
    assert dev['drainage_motor_flag'] is False and any('[D]' in c for c in corr)

    # 포그와 세트(포그 ON)면 배수 유지 — 정당
    dev2 = {'fog_occurs_flag': True, 'drainage_motor_flag': True}
    _, corr2 = el.apply_water_safety(dev2, {'outdoor_temperature': 23.3, 'water_temperature': 23.9}, 1, 1)
    assert dev2['drainage_motor_flag'] is True and not any('[D]' in c for c in corr2)

    # 여름냉각(C, 외부≥29℃)이면 배수 유지 — C가 우선
    dev3 = {'fog_occurs_flag': False, 'drainage_motor_flag': True}
    _, corr3 = el.apply_water_safety(dev3, {'outdoor_temperature': 30.0, 'water_temperature': 25.0}, 1, 1)
    assert dev3['drainage_motor_flag'] is True

    # 수온 과열(≥35℃)이면 배수 유지 — 탱크 교체 정당
    dev4 = {'fog_occurs_flag': False, 'drainage_motor_flag': True, 'water_heater_flag': False}
    _, corr4 = el.apply_water_safety(dev4, {'outdoor_temperature': 23.0, 'water_temperature': 36.0}, 1, 1)
    assert dev4['drainage_motor_flag'] is True
