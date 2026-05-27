# ══════════════════════════════════════════════════════════════════════════════
# test_interlock_invariant — 밸브-팬 절대 불변식 검증
#
# 사용자 명시 지시(절대 제거 금지):
#   · 흡입팬 ON 은 반드시 흡입밸브 ON 혹은 순환밸브 ON
#   · 배출팬 ON 은 반드시 배출밸브 ON 혹은 순환밸브 ON
# 전이 게이트 + 최종 불변식 강제(잔존 위반도 무조건 교정) 검증.
#
# 파일 시작 함수 목록:
#   test_rule_mapping_guard          : 매핑이 지시 규칙과 일치 (제거/변경 방지)
#   test_invariant_forces_fan_off    : 잔존 위반(팬 ON+밸브 전부 OFF) → 팬 강제 OFF
#   test_invariant_pass_intake_valve : 흡입밸브 ON 이면 흡입팬 유지
#   test_invariant_pass_circulation  : 순환밸브 ON 이면 양 팬 모두 유지
#   test_transition_block_kept       : 기존 OFF→ON 전이 차단 동작 유지
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.control.interlock import (
    FAN_VALVE_GATE, evaluate_interlock,
)
from agri_ai_core.src.control.control_common import get_pin_map

H = 1
PIN = get_pin_map(H)
FAN_IN = PIN['intake_fan_flag']
FAN_EX = PIN['exhaust_fan_flag']
V_IN = PIN['air_intake_valve_flag']
V_EX = PIN['air_exhaust_valve_flag']
V_CIRC = PIN['air_circulation_valve_flag']


def _all_off():
    return {f"relay_{i}st_flag": False for i in range(1, 17)}


def test_rule_mapping_guard():
    # 지시 규칙 그대로인지 — 매핑 변경/제거 시 즉시 실패
    assert FAN_VALVE_GATE['intake_fan_flag'] == (
        'air_intake_valve_flag', 'air_circulation_valve_flag')
    assert FAN_VALVE_GATE['exhaust_fan_flag'] == (
        'air_exhaust_valve_flag', 'air_circulation_valve_flag')


def test_invariant_forces_fan_off():
    # 잔존 위반: current 부터 이미 팬 ON + 밸브 전부 OFF (전이 없음 → 전이 게이트는 통과)
    current = _all_off(); current[FAN_IN] = True; current[FAN_EX] = True
    target = dict(current)   # 변경 없음 (전이 없음)
    fixed, violations = evaluate_interlock(1, H, current, target)
    assert fixed[FAN_IN] is False and fixed[FAN_EX] is False, \
        "밸브 전부 OFF 인데 팬 ON 잔존 — 불변식이 강제 OFF 해야 함"
    acts = [v['action'] for v in violations]
    assert acts.count('invariant_forced_off') == 2


def test_invariant_pass_intake_valve():
    current = _all_off(); current[FAN_IN] = True; current[V_IN] = True
    target = dict(current)
    fixed, violations = evaluate_interlock(1, H, current, target)
    assert fixed[FAN_IN] is True   # 흡입밸브 ON → 흡입팬 유지
    assert not [v for v in violations if v['action'] == 'invariant_forced_off']


def test_invariant_pass_circulation():
    current = _all_off()
    current[FAN_IN] = True; current[FAN_EX] = True; current[V_CIRC] = True
    target = dict(current)
    fixed, violations = evaluate_interlock(1, H, current, target)
    assert fixed[FAN_IN] is True and fixed[FAN_EX] is True  # 순환밸브 ON → 양 팬 허용
    assert not [v for v in violations if v['action'] == 'invariant_forced_off']


def test_transition_block_kept():
    # 밸브 없이 팬 OFF→ON 시도 → 차단 (dwell 게이트)
    current = _all_off()
    target = _all_off(); target[FAN_EX] = True
    fixed, violations = evaluate_interlock(1, H, current, target)
    assert fixed[FAN_EX] is False
    assert [v for v in violations if v['action'] == 'on_blocked']
