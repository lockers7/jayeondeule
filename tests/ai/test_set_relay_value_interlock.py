# ══════════════════════════════════════════════════════════════════════════
# set_relay_value ↔ interlock 통합 테스트.
# DB(read_latest_relay_info, db_session) 와 IoT 폴링 백그라운드 스레드를
# monkeypatch 로 mock 처리하고 게이트가 실제 DB 쓰기 직전에 적용되어
# corrected 값이 기록되는지 검증.
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


# ══════════════════════════════════════════════════════════════════════════
# DB mock — read_latest_relay_info 와 db_session.execute_query 가 호출되는
# 파라미터를 캡처하고 항상 성공 응답을 반환한다.
# ══════════════════════════════════════════════════════════════════════════
class _CapturedDB:
    def __init__(self):
        self.last_params = None
    def execute_query(self, query, params):
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
    # 백그라운드 IoT 폴링 스레드는 테스트에서 시작하지 않음
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


# ══════════════════════════════════════════════════════════════════════════
# 1) 수동제어 (raw_mode=False, 시멘틱 키 사용) — 흡입팬 ON 시도, 밸브 미충족
# ══════════════════════════════════════════════════════════════════════════
def test_manual_control_blocks_intake_fan_without_valve(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: _build(1))   # 모든 OFF
    result = rm.set_relay_value(1, 1, {"intake_fan_flag": True})
    assert result["success"] is True
    intake_pin = get_pin_map(1)["intake_fan_flag"]
    # corrected 결과가 DB 에 쓰여야 함 — params 마지막 16개가 relay flags
    written = db_mock.last_params[3:]
    intake_idx = int(intake_pin.replace("relay_", "").replace("st_flag", "")) - 1
    assert written[intake_idx] is False, "흡입팬 ON 차단되어 False 로 쓰여야 함"
    assert any(v["flag"] == "intake_fan_flag" for v in result["interlock_violations"])


# ══════════════════════════════════════════════════════════════════════════
# 2) 수동제어 — 밸브가 한참 ON 인 상태 → 흡입팬 ON 통과
# ══════════════════════════════════════════════════════════════════════════
def test_manual_control_allows_intake_fan_when_valve_dwelled(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info",
                        lambda f, h: _build(1, air_intake_valve_flag=True))
    # latch 를 30초 전으로 수동 셋업 (실제로는 record_valve_transitions 가 채움)
    ilk._valve_on_since[(str(1), 1, 'air_intake_valve_flag')] = datetime.now() - timedelta(seconds=30)
    result = rm.set_relay_value(1, 1, {"intake_fan_flag": True})
    assert result["success"] is True
    intake_pin = get_pin_map(1)["intake_fan_flag"]
    written = db_mock.last_params[3:]
    intake_idx = int(intake_pin.replace("relay_", "").replace("st_flag", "")) - 1
    assert written[intake_idx] is True
    assert result["interlock_violations"] == []


# ══════════════════════════════════════════════════════════════════════════
# 3) raw_mode (수동환경제어 16개 직접 전달) — 게이트는 동일하게 적용
# ══════════════════════════════════════════════════════════════════════════
def test_raw_mode_still_applies_gate(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: _build(1))
    target_raw = _build(1, air_intake_valve_flag=True, intake_fan_flag=True)
    result = rm.set_relay_value(1, 1, target_raw, raw_mode=True)
    assert result["success"] is True
    intake_pin = get_pin_map(1)["intake_fan_flag"]
    written = db_mock.last_params[3:]
    intake_idx = int(intake_pin.replace("relay_", "").replace("st_flag", "")) - 1
    # 동시 ON 시도 → 게이트가 팬은 차단, 밸브는 통과
    assert written[intake_idx] is False


# ══════════════════════════════════════════════════════════════════════════
# 4) OFF 차단 (rev2) — 흡입밸브 OFF 요청 시 흡입팬이 ON 이면 차단되어
#    DB 에는 밸브가 ON 그대로 기록되고 violations 에 off_blocked 가 포함된다.
# ══════════════════════════════════════════════════════════════════════════
def test_valve_off_blocked_when_dependent_fan_on(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info",
                        lambda f, h: _build(1, air_intake_valve_flag=True, intake_fan_flag=True))
    result = rm.set_relay_value(1, 1, {"air_intake_valve_flag": False})
    assert result["success"] is True
    written = db_mock.last_params[3:]
    intake_fan_pin = get_pin_map(1)["intake_fan_flag"]
    valve_pin = get_pin_map(1)["air_intake_valve_flag"]
    fan_idx = int(intake_fan_pin.replace("relay_", "").replace("st_flag", "")) - 1
    valve_idx = int(valve_pin.replace("relay_", "").replace("st_flag", "")) - 1
    # 차단됨 — 밸브와 팬 둘 다 ON 그대로
    assert written[valve_idx] is True
    assert written[fan_idx] is True
    v = next(x for x in result["interlock_violations"] if x["action"] == "off_blocked")
    assert v["flag"] == "air_intake_valve_flag"


# ══════════════════════════════════════════════════════════════════════════
# 5) 밸브 OFF→ON 전이 시 latch 가 갱신되어 다음 호출에서 dwell 계산 가능
# ══════════════════════════════════════════════════════════════════════════
def test_latch_updated_after_successful_write(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: _build(1))
    rm.set_relay_value(1, 1, {"air_intake_valve_flag": True})
    # 직후 dwell 은 0초 근처
    d = ilk.get_valve_dwell_sec(1, 1, 'air_intake_valve_flag')
    assert d is not None
    assert d < 1.0


# ══════════════════════════════════════════════════════════════════════════
# 6) 2호 (E타입 핀맵) — 동일 시멘틱 → 다른 relay 번호 → 같은 인터록 동작
# ══════════════════════════════════════════════════════════════════════════
def test_house_2_e_pinmap_interlock(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info", lambda f, h: _build(2))
    result = rm.set_relay_value(1, 2, {"intake_fan_flag": True})
    assert result["success"] is True
    intake_pin = get_pin_map(2)["intake_fan_flag"]   # 2호: relay_7st_flag
    written = db_mock.last_params[3:]
    intake_idx = int(intake_pin.replace("relay_", "").replace("st_flag", "")) - 1
    assert written[intake_idx] is False


# ══════════════════════════════════════════════════════════════════════════
# 7) raw_mode dict 가 무작위 순서로 들어와도 컬럼 1..16 순서로 정렬되어 기록.
#    (Java HashMap → JSON → Python dict 경로에서 키 순서가 섞이는 케이스 재현)
# ══════════════════════════════════════════════════════════════════════════
def test_raw_mode_column_order_preserved(monkeypatch, db_mock):
    monkeypatch.setattr(rm, "read_latest_relay_info",
                        lambda f, h: {f"relay_{i}st_flag": False for i in range(1, 17)})
    # 일부러 무작위 순서 dict — relay_5 만 True, relay_1 만 True
    shuffled = {
        "relay_10st_flag": False, "relay_3st_flag":  False,
        "relay_15st_flag": False, "relay_1st_flag":  True,
        "relay_8st_flag":  False, "relay_14st_flag": False,
        "relay_7st_flag":  False, "relay_5st_flag":  True,
        "relay_2st_flag":  False, "relay_11st_flag": False,
        "relay_6st_flag":  False, "relay_12st_flag": False,
        "relay_4st_flag":  False, "relay_9st_flag":  False,
        "relay_13st_flag": False, "relay_16st_flag": False,
    }
    rm.set_relay_value(1, 1, shuffled, raw_mode=True)
    written = db_mock.last_params[3:]
    # relay_1 (idx 0), relay_5 (idx 4) 만 True 여야 함 — 다른 컬럼 침범 없음
    expected = [True, False, False, False, True, False, False, False,
                False, False, False, False, False, False, False, False]
    # 단, intake_fan(relay_5) ON 은 valve dwell 없어 게이트가 차단 → relay_5 = False
    expected[4] = False
    for i, exp in enumerate(expected):
        assert written[i] is exp, f"relay_{i+1}st_flag 기대={exp}, 실제={written[i]}"
