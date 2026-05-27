# ══════════════════════════════════════════════════════════════════════════
# 밸브-팬 인터록 단위테스트 — interlock.py 의 게이트/latch/상태 로직 검증.
# DB·IoT 의존 없이 순수 함수 테스트로 1·3호(STANDARD) 와 2호(E타입) 핀맵 모두
# 커버. 임계 통과/차단/OFF 자동보정/재진입 시나리오 포함.
# ══════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta

import pytest

from agri_ai_core.src.control import interlock as ilk
from agri_ai_core.src.control.control_common import get_pin_map


@pytest.fixture(autouse=True)
def _reset_state():
    ilk.clear_state()
    yield
    ilk.clear_state()


# ══════════════════════════════════════════════════════════════════════════
# 헬퍼 — semantic flag dict 를 relay_*st_flag dict 로 변환 (house_id 별)
# ══════════════════════════════════════════════════════════════════════════
def _build(house_id, **flags):
    pin_map = get_pin_map(house_id)
    out = {f"relay_{i}st_flag": False for i in range(1, 17)}
    for flag, val in flags.items():
        pin = pin_map.get(flag)
        if pin:
            out[pin] = bool(val)
    return out


# ════════════════════════
# record_valve_transitions
# ════════════════════════
class TestRecordTransitions:
    def test_off_to_on_records_now(self):
        prev = _build(1, air_intake_valve_flag=False)
        new  = _build(1, air_intake_valve_flag=True)
        ts = datetime(2026, 4, 27, 12, 0, 0)
        ilk.record_valve_transitions(1, 1, prev, new, now=ts)
        assert ilk.get_valve_dwell_sec(1, 1, 'air_intake_valve_flag', now=ts) == 0.0

    def test_on_to_off_clears_latch(self):
        prev = _build(1, air_intake_valve_flag=True)
        new  = _build(1, air_intake_valve_flag=False)
        ilk.record_valve_transitions(1, 1, _build(1, air_intake_valve_flag=False), prev,
                                     now=datetime(2026, 4, 27, 12, 0, 0))
        ilk.record_valve_transitions(1, 1, prev, new,
                                     now=datetime(2026, 4, 27, 12, 0, 5))
        assert ilk.get_valve_dwell_sec(1, 1, 'air_intake_valve_flag') is None

    def test_on_kept_does_not_reset_latch(self):
        prev = _build(1, air_intake_valve_flag=True)
        new  = _build(1, air_intake_valve_flag=True)
        ilk.record_valve_transitions(1, 1, _build(1), prev,
                                     now=datetime(2026, 4, 27, 12, 0, 0))
        ilk.record_valve_transitions(1, 1, prev, new,
                                     now=datetime(2026, 4, 27, 12, 0, 5))
        # 5초 후에도 latch 는 12:00:00 그대로 → dwell 5s
        assert ilk.get_valve_dwell_sec(1, 1, 'air_intake_valve_flag',
                                       now=datetime(2026, 4, 27, 12, 0, 5)) == 5.0

    def test_house_2_uses_e_pinmap(self):
        # 2호는 air_intake_valve_flag → relay_11st_flag (STANDARD 14 와 다름)
        prev = _build(2, air_intake_valve_flag=False)
        new  = _build(2, air_intake_valve_flag=True)
        ts = datetime(2026, 4, 27, 12, 0, 0)
        ilk.record_valve_transitions(1, 2, prev, new, now=ts)
        assert ilk.get_valve_dwell_sec(1, 2, 'air_intake_valve_flag', now=ts) == 0.0


# ══════════════════════════════════════════════════════════
# evaluate_interlock — ON 인터록 (흡입팬/배출팬 OFF→ON 전이)
# ══════════════════════════════════════════════════════════
class TestOnInterlock:
    def test_intake_fan_on_blocked_when_no_valve(self):
        current = _build(1)   # 모든 OFF
        target  = _build(1, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is False
        assert any(v['flag'] == 'intake_fan_flag' and v['action'] == 'on_blocked' for v in viol)

    def test_intake_fan_on_blocked_when_valve_too_recent(self):
        # 흡입밸브 5초 전 ON
        ts_now = datetime(2026, 4, 27, 12, 0, 5)
        ilk.record_valve_transitions(1, 1,
            _build(1, air_intake_valve_flag=False),
            _build(1, air_intake_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 0))
        current = _build(1, air_intake_valve_flag=True)
        target  = _build(1, air_intake_valve_flag=True, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target, now=ts_now)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is False
        assert viol[0]['remaining_sec'] == 5

    def test_intake_fan_on_allowed_after_10s(self):
        ts_now = datetime(2026, 4, 27, 12, 0, 11)
        ilk.record_valve_transitions(1, 1,
            _build(1, air_intake_valve_flag=False),
            _build(1, air_intake_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 0))
        current = _build(1, air_intake_valve_flag=True)
        target  = _build(1, air_intake_valve_flag=True, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target, now=ts_now)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is True
        assert viol == []

    def test_intake_fan_on_allowed_via_circulation_valve(self):
        # 순환밸브로도 인터록 통과
        ts_now = datetime(2026, 4, 27, 12, 0, 11)
        ilk.record_valve_transitions(1, 1,
            _build(1),
            _build(1, air_circulation_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 0))
        current = _build(1, air_circulation_valve_flag=True)
        target  = _build(1, air_circulation_valve_flag=True, intake_fan_flag=True)
        corrected, _ = ilk.evaluate_interlock(1, 1, current, target, now=ts_now)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is True

    def test_already_on_fan_unaffected(self):
        # 이미 ON 인 팬은 "전이 게이트(dwell)" 는 패스하지만,
        # 사용자 절대 불변식(팬 ON ⇒ 선행 밸브 ON)에 따라 밸브가 하나라도 ON 인
        # 상태여야 유지된다. 밸브 ON 동반 시나리오로 현행 유지 검증.
        current = _build(1, intake_fan_flag=True, air_intake_valve_flag=True)
        target  = _build(1, intake_fan_flag=True, air_intake_valve_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is True
        assert viol == []

    def test_already_on_fan_without_valve_forced_off(self):
        # 밸브 전부 OFF 인데 팬만 ON 잔존 — 강제 OFF
        # (절대 불변식 최종 강제 — 사용자 명시 지시, 모터 소손 방지)
        current = _build(1, intake_fan_flag=True)
        target  = _build(1, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is False
        assert any(v['action'] == 'invariant_forced_off' for v in viol)

    def test_fan_off_request_always_allowed(self):
        current = _build(1, intake_fan_flag=True)
        target  = _build(1, intake_fan_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[intake_pin] is False
        assert viol == []

    def test_exhaust_fan_via_exhaust_valve(self):
        ts_now = datetime(2026, 4, 27, 12, 0, 11)
        ilk.record_valve_transitions(1, 1,
            _build(1),
            _build(1, air_exhaust_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 0))
        current = _build(1, air_exhaust_valve_flag=True)
        target  = _build(1, air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        corrected, _ = ilk.evaluate_interlock(1, 1, current, target, now=ts_now)
        exhaust_pin = get_pin_map(1)['exhaust_fan_flag']
        assert corrected[exhaust_pin] is True

    def test_simultaneous_valve_and_fan_on_blocked(self):
        # 같은 쓰기에 valve OFF→ON 과 fan OFF→ON 이 동시에 오면 dwell=0 → 차단
        current = _build(1)
        target  = _build(1, air_intake_valve_flag=True, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        intake_pin = get_pin_map(1)['intake_fan_flag']
        valve_pin = get_pin_map(1)['air_intake_valve_flag']
        assert corrected[intake_pin] is False  # 팬은 차단
        assert corrected[valve_pin] is True    # 밸브는 허용
        assert viol[0]['remaining_sec'] == 10


# ══════════════════════════════════════════════════════════════════════════
# evaluate_interlock — OFF 인터록
# 사양: 밸브가 닫힌 상태에서 팬이 가동되면 팬 모터 손상. 사용자가 팬을 먼저
# OFF 시키도록 강제. 순환밸브는 흡기측/배기측이 풀가동이면 예외 통과.
# ══════════════════════════════════════════════════════════════════════════
class TestOffInterlock:
    def test_intake_valve_off_blocked_when_intake_fan_on(self):
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True)
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        valve_pin = get_pin_map(1)['air_intake_valve_flag']
        fan_pin = get_pin_map(1)['intake_fan_flag']
        # 밸브 ON 으로 되돌려짐, 팬은 그대로 ON
        assert corrected[valve_pin] is True
        assert corrected[fan_pin] is True
        v = next(x for x in viol if x['action'] == 'off_blocked')
        assert v['flag'] == 'air_intake_valve_flag'
        assert 'intake_fan_flag' in v['blocking_fans']

    def test_intake_valve_off_allowed_when_intake_fan_already_off(self):
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=False)
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        valve_pin = get_pin_map(1)['air_intake_valve_flag']
        assert corrected[valve_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_intake_valve_off_allowed_when_fan_off_in_same_write(self):
        # 같은 쓰기에서 팬을 OFF 하면서 밸브도 OFF — 통과
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True)
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        valve_pin = get_pin_map(1)['air_intake_valve_flag']
        assert corrected[valve_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_exhaust_valve_off_blocked_when_exhaust_fan_on(self):
        current = _build(1, air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        target  = _build(1, air_exhaust_valve_flag=False, exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        valve_pin = get_pin_map(1)['air_exhaust_valve_flag']
        fan_pin = get_pin_map(1)['exhaust_fan_flag']
        assert corrected[valve_pin] is True
        assert corrected[fan_pin] is True
        assert any(v['action'] == 'off_blocked' and v['flag'] == 'air_exhaust_valve_flag' for v in viol)

    def test_circulation_valve_off_blocked_when_both_fans_on_no_side_full(self):
        # 흡입밸브/배출밸브 OFF 라 흡기/배기 측 둘 다 풀가동 아님 → 차단
        current = _build(1, air_circulation_valve_flag=True,
                         intake_fan_flag=True, exhaust_fan_flag=True)
        target  = _build(1, air_circulation_valve_flag=False,
                         intake_fan_flag=True, exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        assert corrected[c_pin] is True   # 차단되어 ON 유지
        v = next(x for x in viol if x['action'] == 'off_blocked')
        assert v['flag'] == 'air_circulation_valve_flag'
        assert set(v['blocking_fans']) == {'intake_fan_flag', 'exhaust_fan_flag'}

    def test_circulation_valve_off_blocked_when_one_side_dead_end(self):
        # 흡입측 풀가동이어도 배출팬 ON & 배출밸브 OFF 면 차단 (배출팬 출구 봉쇄)
        # Rule 1/2 invariant 보존을 위한 AND 식 검증
        current = _build(1, air_circulation_valve_flag=True,
                         air_intake_valve_flag=True, intake_fan_flag=True,
                         exhaust_fan_flag=True)
        target  = _build(1, air_circulation_valve_flag=False,
                         air_intake_valve_flag=True, intake_fan_flag=True,
                         exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        assert corrected[c_pin] is True   # 차단
        v = next(x for x in viol if x['action'] == 'off_blocked')
        assert v['flag'] == 'air_circulation_valve_flag'
        assert 'exhaust_fan_flag' in v['blocking_fans']

    def test_circulation_valve_off_allowed_when_intake_fan_off_exhaust_full(self):
        # 흡입팬 OFF + 배출측 풀가동 → 모든 ON 팬(배출팬)이 자기 측 밸브 보장 → 통과
        current = _build(1, air_circulation_valve_flag=True,
                         air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        target  = _build(1, air_circulation_valve_flag=False,
                         air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        assert corrected[c_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_circulation_valve_off_allowed_when_both_sides_full_on(self):
        # 흡기측·배기측 둘 다 풀가동 → 통과
        current = _build(1, air_circulation_valve_flag=True,
                         air_intake_valve_flag=True, intake_fan_flag=True,
                         air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        target  = _build(1, air_circulation_valve_flag=False,
                         air_intake_valve_flag=True, intake_fan_flag=True,
                         air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        assert corrected[c_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_circulation_valve_off_allowed_when_both_fans_off(self):
        current = _build(1, air_circulation_valve_flag=True,
                         intake_fan_flag=False, exhaust_fan_flag=False)
        target  = _build(1, air_circulation_valve_flag=False,
                         intake_fan_flag=False, exhaust_fan_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        assert corrected[c_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol)

    # ───── Rule 3 · 4 — 순환밸브 ON + 반대측 팬 ON 예외 ─────
    def test_intake_valve_off_allowed_when_circ_on_and_exhaust_fan_on(self):
        # Rule 3: 순환밸브 ON 만 으로는 부족 — 배출팬도 ON 이어야 흡입팬 출구 보장
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                         air_circulation_valve_flag=True, exhaust_fan_flag=True)
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=True,
                         air_circulation_valve_flag=True, exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        if_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[iv_pin] is False
        assert corrected[if_pin] is True
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_intake_valve_off_blocked_when_circ_on_but_exhaust_fan_off(self):
        # Rule 3 회귀: 순환밸브 ON 인데 배출팬 OFF → 차단
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                         air_circulation_valve_flag=True)   # 배출팬 OFF
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=True,
                         air_circulation_valve_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        assert corrected[iv_pin] is True   # 차단됨
        assert any(v['action'] == 'off_blocked' and v['flag'] == 'air_intake_valve_flag' for v in viol)

    def test_exhaust_valve_off_allowed_when_circ_on_and_intake_fan_on(self):
        # Rule 4: 순환밸브 ON + 흡입팬 ON 이어야 통과
        current = _build(1, air_exhaust_valve_flag=True, exhaust_fan_flag=True,
                         air_circulation_valve_flag=True, intake_fan_flag=True)
        target  = _build(1, air_exhaust_valve_flag=False, exhaust_fan_flag=True,
                         air_circulation_valve_flag=True, intake_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        ev_pin = get_pin_map(1)['air_exhaust_valve_flag']
        ef_pin = get_pin_map(1)['exhaust_fan_flag']
        assert corrected[ev_pin] is False
        assert corrected[ef_pin] is True
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_exhaust_valve_off_blocked_when_circ_on_but_intake_fan_off(self):
        # Rule 4 회귀: 순환밸브 ON 인데 흡입팬 OFF → 차단
        current = _build(1, air_exhaust_valve_flag=True, exhaust_fan_flag=True,
                         air_circulation_valve_flag=True)   # 흡입팬 OFF
        target  = _build(1, air_exhaust_valve_flag=False, exhaust_fan_flag=True,
                         air_circulation_valve_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        ev_pin = get_pin_map(1)['air_exhaust_valve_flag']
        assert corrected[ev_pin] is True
        assert any(v['action'] == 'off_blocked' and v['flag'] == 'air_exhaust_valve_flag' for v in viol)

    def test_intake_valve_off_blocked_when_no_circulation_no_fan_off(self):
        # Rule 3 회귀: 순환밸브 OFF + 흡입팬 ON → 차단
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                         air_circulation_valve_flag=False)
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=True,
                         air_circulation_valve_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        assert corrected[iv_pin] is True   # 차단됨
        v = next(x for x in viol if x['action'] == 'off_blocked')
        assert v['flag'] == 'air_intake_valve_flag'

    def test_intake_and_circulation_off_same_write_blocks_intake_keeps_circ(self):
        # 동시 OFF: 흡입밸브와 순환밸브 둘 다 OFF 시도 → 흡입밸브 차단,
        # 순환밸브 OFF 는 (흡입팬 ON & 흡입밸브 ON 으로 되돌아간 상태) → Rule 5 통과
        current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                         air_circulation_valve_flag=True)
        target  = _build(1, air_intake_valve_flag=False, intake_fan_flag=True,
                         air_circulation_valve_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        # 흡입밸브 차단되어 ON 으로 되돌아감 → 흡입팬에 흡입밸브 경로 → Rule 5 통과
        assert corrected[iv_pin] is True
        assert corrected[c_pin] is False
        # off_blocked 위반은 흡입밸브 1건 (순환밸브 통과)
        blocked = [v for v in viol if v['action'] == 'off_blocked']
        assert len(blocked) == 1 and blocked[0]['flag'] == 'air_intake_valve_flag'


# ══════════════════════════════════════════════════════════════════════════
# 사용자 제공 전체 시나리오 — Rules 1..5 종합 검증
# ══════════════════════════════════════════════════════════════════════════
class TestUserScenarios:
    def test_intake_circulation_intake_valve_all_on_circulation_off_allowed(self):
        # 사용자 시나리오: 흡입팬 ON, 순환밸브 ON, 흡입밸브 ON, 배출팬 OFF
        # 순환밸브 OFF — Rule 5: 흡입측 풀가동 → 통과
        state = _build(1, intake_fan_flag=True,
                       air_circulation_valve_flag=True,
                       air_intake_valve_flag=True)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        target1 = dict(state); target1[c_pin] = False
        corrected1, viol1 = ilk.evaluate_interlock(1, 1, state, target1)
        assert corrected1[c_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol1)

    def test_intake_valve_off_blocked_when_only_circ_on_no_exhaust_fan(self):
        # 사용자 시나리오: 흡입팬 ON, 순환밸브 ON, 흡입밸브 ON, 배출팬 OFF
        # 흡입밸브 OFF — Rule 3: 흡입팬 OFF 도, (순환밸브 ON ∧ 배출팬 ON) 도 모두
        # 만족 안 함 → 차단
        state = _build(1, intake_fan_flag=True,
                       air_circulation_valve_flag=True,
                       air_intake_valve_flag=True)   # 배출팬 OFF
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        target = dict(state); target[iv_pin] = False
        corrected, viol = ilk.evaluate_interlock(1, 1, state, target)
        assert corrected[iv_pin] is True   # 차단
        assert any(v['action'] == 'off_blocked' and v['flag'] == 'air_intake_valve_flag' for v in viol)

    def test_exhaust_full_with_intake_fan_runs_circulation_off_blocked(self):
        # 배출측 풀가동 + 흡입팬 ON & 흡입밸브 OFF → 차단 (흡입팬 출구 봉쇄)
        current = _build(1, intake_fan_flag=True,
                         air_circulation_valve_flag=True,
                         air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        target = _build(1, intake_fan_flag=True,
                        air_circulation_valve_flag=False,
                        air_exhaust_valve_flag=True, exhaust_fan_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        assert corrected[c_pin] is True   # 차단
        assert any(v['action'] == 'off_blocked' for v in viol)

    def test_external_circulation_to_exhaust_circulation_three_changes(self):
        # 외부순환(모든 밸브 ON, 모든 팬 ON) → 배기순환 (배출밸브·배출팬만 ON)
        # 동시 변경 3개: 흡입팬 OFF, 흡입밸브 OFF, 순환밸브 OFF
        current = _build(1, intake_fan_flag=True, exhaust_fan_flag=True,
                         air_intake_valve_flag=True, air_exhaust_valve_flag=True,
                         air_circulation_valve_flag=True)
        target  = _build(1, intake_fan_flag=False, exhaust_fan_flag=True,
                         air_intake_valve_flag=False, air_exhaust_valve_flag=True,
                         air_circulation_valve_flag=False)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        # 흡입밸브 OFF: 흡입팬 OFF (target) → 통과
        # 순환밸브 OFF: 흡입팬 OFF & 배출팬 ON & 배출밸브 ON → 통과
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        c_pin = get_pin_map(1)['air_circulation_valve_flag']
        if_pin = get_pin_map(1)['intake_fan_flag']
        assert corrected[iv_pin] is False
        assert corrected[c_pin] is False
        assert corrected[if_pin] is False
        assert all(v['action'] != 'off_blocked' for v in viol)

    def test_circulation_only_running_can_open_intake_valve_to_outside(self):
        # 내부순환(순환밸브·흡입팬·배출팬 ON) → 외부순환 진입을 위해 흡입밸브 ON
        # 흡입밸브 OFF→ON 은 본질 안전 → 인터록 영향 없이 즉시 통과
        current = _build(1, air_circulation_valve_flag=True,
                         intake_fan_flag=True, exhaust_fan_flag=True)
        target  = _build(1, air_circulation_valve_flag=True,
                         intake_fan_flag=True, exhaust_fan_flag=True,
                         air_intake_valve_flag=True)
        corrected, viol = ilk.evaluate_interlock(1, 1, current, target)
        iv_pin = get_pin_map(1)['air_intake_valve_flag']
        assert corrected[iv_pin] is True
        assert viol == []


# ════════════════════════════════════════════════
# bootstrap_valve_state — 부팅 시 latch 복원
# ════════════════════════════════════════════════
class TestBootstrap:
    def test_bootstrap_marks_on_valves_as_long_ago(self):
        latest = _build(1, air_intake_valve_flag=True, air_exhaust_valve_flag=True)
        ilk.bootstrap_valve_state(1, 1, latest_relay=latest)
        # 24h 전으로 latch → 한참 전 dwell
        d = ilk.get_valve_dwell_sec(1, 1, 'air_intake_valve_flag')
        assert d is not None and d > 3600
        # OFF 인 순환밸브는 latch 없음
        assert ilk.get_valve_dwell_sec(1, 1, 'air_circulation_valve_flag') is None


# ════════════════════════════════════════════════
# get_interlock_status — UI 표시용 잔여시간
# ════════════════════════════════════════════════
class TestStatus:
    def test_no_valve_on_means_full_threshold(self):
        st = ilk.get_interlock_status(1, 1, current=_build(1))
        assert st['intake_fan_flag']['can_on'] is False
        assert st['intake_fan_flag']['remaining_sec'] == ilk.VALVE_FAN_INTERLOCK_SEC
        assert st['exhaust_fan_flag']['can_on'] is False

    def test_after_10s_can_on(self):
        ilk.record_valve_transitions(1, 1, _build(1),
            _build(1, air_intake_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 0))
        st = ilk.get_interlock_status(1, 1,
            current=_build(1, air_intake_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 11))
        assert st['intake_fan_flag']['can_on'] is True
        assert st['intake_fan_flag']['remaining_sec'] == 0
        assert st['intake_fan_flag']['gate_via'] == 'air_intake_valve_flag'

    def test_partial_dwell_returns_remaining(self):
        ilk.record_valve_transitions(1, 1, _build(1),
            _build(1, air_circulation_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 0))
        st = ilk.get_interlock_status(1, 1,
            current=_build(1, air_circulation_valve_flag=True),
            now=datetime(2026, 4, 27, 12, 0, 3))   # 3초 경과
        assert st['intake_fan_flag']['can_on'] is False
        assert st['intake_fan_flag']['remaining_sec'] == 7
        assert st['exhaust_fan_flag']['can_on'] is False
        assert st['exhaust_fan_flag']['remaining_sec'] == 7
