# ══════════════════════════════════════════════════════════════════════════
# 모든 운용모드(AI/알고리즘/수동) 가 단일 인터록 게이트 (interlock.evaluate_interlock,
# 호출지: relay_manager.set_relay_value) 를 통과하는지 회귀 검증.
# DB·서비스 의존 없이 monkeypatch 로 mock 하여 각 모드의 진입점 호출 시 게이트가
# 호출되는지, 그리고 위반 시 corrected 된 안전 상태가 기록되는지 확인.
# ══════════════════════════════════════════════════════════════════════════
from datetime import datetime, timedelta

import pytest

from agri_ai_core.src.control import relay_manager as rm
from agri_ai_core.src.control import interlock as ilk
from agri_ai_core.src.control.control_common import get_pin_map


@pytest.fixture(autouse=True)
def _reset_state():
    ilk.clear_state()
    yield
    ilk.clear_state()


class _CapturedDB:
    def __init__(self):
        self.last_params = None
        self.calls = 0
    def execute_query(self, query, params):
        self.calls += 1
        self.last_params = params
        return True
    def fetch_one(self, query, vals):
        return None


@pytest.fixture
def db_mock(monkeypatch):
    captured = _CapturedDB()
    class _Sess:
        def __enter__(self_inner): return captured
        def __exit__(self_inner, *a): return False
    monkeypatch.setattr(rm, "db_session", _Sess)
    monkeypatch.setattr(rm, "_persist_relay_values", lambda *a, **kw: None)
    return captured


def _build(house_id, **flags):
    pin_map = get_pin_map(house_id)
    out = {f"relay_{i}st_flag": False for i in range(1, 17)}
    for f, v in flags.items():
        pin = pin_map.get(f)
        if pin:
            out[pin] = bool(v)
    return out


def _written(captured):
    if captured.last_params is None:
        return None
    return captured.last_params[3:]


def _idx(house_id, semantic_flag):
    pin = get_pin_map(house_id)[semantic_flag]
    return int(pin.replace("relay_", "").replace("st_flag", "")) - 1


# ══════════════════════════════════════════════════════════════════════════
# 1) 수동제어 진입점 (tools_control.control_relay → set_relay_value)
#    LLM/웹 manual mode 가 시멘틱 키 단일 토글로 호출.
# ══════════════════════════════════════════════════════════════════════════
def test_manual_path_blocks_unsafe_fan_on(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: _build(1))
    rm.set_relay_value(1, 1, {"intake_fan_flag": True})
    # 게이트가 차단 → 흡입팬 컬럼 = False
    assert _written(db_mock)[_idx(1, "intake_fan_flag")] is False


# ══════════════════════════════════════════════════════════════════════════
# 2) AI/algo (raw_mode=True) — rev6 AND spec: 한쪽 dead end 면 순환밸브 OFF 차단
# ══════════════════════════════════════════════════════════════════════════
def test_raw_mode_path_blocks_circulation_off_when_one_side_dead_end(monkeypatch, db_mock):
    # 흡입측 풀가동 + 배출팬 ON + 배출밸브 OFF → 순환밸브 OFF 차단되어야
    current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                     air_circulation_valve_flag=True, exhaust_fan_flag=True)
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: current)
    target = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                    air_circulation_valve_flag=False, exhaust_fan_flag=True)
    rm.set_relay_value(1, 1, target, raw_mode=True)
    assert _written(db_mock)[_idx(1, "air_circulation_valve_flag")] is True   # 차단


# ══════════════════════════════════════════════════════════════════════════
# 3) AI 모드 — Rule 3 (rev5): 흡입밸브 OFF 시 순환밸브 ON + 배출팬 ON 둘 다 필요
# ══════════════════════════════════════════════════════════════════════════
def test_raw_mode_intake_valve_off_allowed_via_circ_and_exhaust_fan(monkeypatch, db_mock):
    current = _build(1, air_intake_valve_flag=True, intake_fan_flag=True,
                     air_circulation_valve_flag=True, exhaust_fan_flag=True)
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: current)
    target = _build(1, air_intake_valve_flag=False, intake_fan_flag=True,
                    air_circulation_valve_flag=True, exhaust_fan_flag=True)
    rm.set_relay_value(1, 1, target, raw_mode=True)
    assert _written(db_mock)[_idx(1, "air_intake_valve_flag")] is False
    assert _written(db_mock)[_idx(1, "intake_fan_flag")] is True


# ══════════════════════════════════════════════════════════════════════════
# 4) 알고리즘 모드 — 외부순환 → 흡입순환 전이 시 게이트 통과 (Phase 1 새 로직)
#    current = 외부순환 (모든 valve ON 제외 circ, 모든 fan ON)
#    Phase 1 target = (current AND new) — exhaust_fan 은 새 모드에서 OFF 라 Phase 1 에서 OFF
#    → exhaust_valve OFF 가 같은 쓰기에서 통과
# ══════════════════════════════════════════════════════════════════════════
def test_external_to_intake_circulation_phase1_passes_gate(monkeypatch, db_mock):
    current = _build(1,
                     air_intake_valve_flag=True, air_exhaust_valve_flag=True,
                     air_circulation_valve_flag=False,
                     intake_fan_flag=True, exhaust_fan_flag=True)
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: current)
    # Phase 1 시뮬레이션: valves 새 mode + fans = current AND new
    # 새 mode (흡입순환): intake_valve=ON, exhaust_valve=OFF, circ=OFF,
    #                    intake_fan=ON, exhaust_fan=OFF
    phase1 = _build(1,
                    air_intake_valve_flag=True, air_exhaust_valve_flag=False,
                    air_circulation_valve_flag=False,
                    intake_fan_flag=(True and True),       # current AND new
                    exhaust_fan_flag=(True and False))      # → False
    rm.set_relay_value(1, 1, phase1, raw_mode=True)
    # exhaust_valve OFF 가 정상 통과 (exhaust_fan target=OFF 라 차단 없음)
    assert _written(db_mock)[_idx(1, "air_exhaust_valve_flag")] is False
    assert _written(db_mock)[_idx(1, "exhaust_fan_flag")] is False


# ══════════════════════════════════════════════════════════════════════════
# 5) 모드 무관 — 모든 set_relay_value 호출은 인터록 게이트를 거친다는 회귀
# ══════════════════════════════════════════════════════════════════════════
def test_gate_runs_for_every_set_relay_value_call(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: _build(1))
    called = {"count": 0}
    orig_eval = ilk.evaluate_interlock
    def _spy(*args, **kwargs):
        called["count"] += 1
        return orig_eval(*args, **kwargs)
    monkeypatch.setattr(rm, "evaluate_interlock", _spy)

    # 다양한 진입 형태로 set_relay_value 호출
    rm.set_relay_value(1, 1, {"intake_fan_flag": True})                    # manual semantic
    rm.set_relay_value(1, 1, _build(1, intake_fan_flag=True), raw_mode=True)  # raw_mode (AI/algo)
    rm.set_relay_value(1, 1, {"air_intake_valve_flag": True})              # 다른 시멘틱

    assert called["count"] == 3, "모든 호출이 게이트를 거쳐야 함"
