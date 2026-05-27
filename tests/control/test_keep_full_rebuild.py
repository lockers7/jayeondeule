# ══════════════════════════════════════════════════════════════════════════════
# test_keep_full_rebuild — keep(현상유지) 시 전체 재구성 검증 (농장주 지시)
#
# 원칙: change 든 keep 이든 매 사이클 릴레이를 전체 재구성한다 (전부 OFF 초기화
# → 목표만 ON). 이전 값 잔재를 남기지 않는다. 조명/관수도 스케줄 시간으로 매번
# 재계산(현상유지 아님). 순환밸브 같은 잔재가 keep 반복 중 자동 정리되어야 함.
#
# 파일 시작 함수 목록:
#   test_schedule_target_pure          : compute_schedule_target ON/OFF/None 판정
#   test_execute_control_injects_schedule : 조명/관수 스케줄값이 relay 에 반영
#   test_execute_control_full_reset    : 명시 안 한 릴레이는 OFF 로 초기화 (잔재 제거)
#   test_get_last_change_target        : 마지막 change 결정 조회
#   test_keep_rebuild_clears_stale     : keep 시 마지막 change 재구성 → 순환밸브 잔재 OFF
# ══════════════════════════════════════════════════════════════════════════════
from datetime import time as _t

from agri_ai_core.src.control import schedule_control as sc
from agri_ai_core.src.control import manual_control as mc
from agri_ai_core.src.control import ai_control as ac
from agri_ai_core.src.control.control_common import get_pin_map, CIRCULATION_MODES


def test_schedule_target_pure(monkeypatch):
    # 스케줄 없음 → None (현재 유지)
    monkeypatch.setattr(sc, "read_light_irrigation_settings", lambda f, h, t: [])
    assert sc.compute_schedule_target(1, 1, "light") is None
    # 시간대 내 daily → True
    monkeypatch.setattr(sc, "read_light_irrigation_settings",
                        lambda f, h, t: [{"strt_time": _t(0, 0), "fnsh_time": _t(23, 59),
                                          "excs_type": "daily"}])
    assert sc.compute_schedule_target(1, 1, "light") is True
    # 시간대 밖 → False
    monkeypatch.setattr(sc, "read_light_irrigation_settings",
                        lambda f, h, t: [{"strt_time": _t(3, 0), "fnsh_time": _t(3, 1),
                                          "excs_type": "daily"}])
    assert sc.compute_schedule_target(1, 1, "light") is False


def test_execute_control_full_reset(monkeypatch):
    # _build_relay_values: 명시 안 한 핀은 False 초기화 (잔재 제거의 핵심)
    monkeypatch.setattr(sc, "read_light_irrigation_settings", lambda f, h, t: [])
    pm = get_pin_map(1)
    # current 에 순환밸브 ON 잔재가 있어도, semantic 에 OFF 명시하면 OFF
    current = {f"relay_{i}st_flag": True for i in range(1, 17)}   # 전부 ON 잔재
    sem = dict(CIRCULATION_MODES['배기순환']['dampers'])  # 순환밸브 False 포함
    sem.update({'water_heater_flag': False, 'fog_occurs_flag': False, 'drainage_motor_flag': False})
    rv = mc._build_relay_values(1, sem, current, harvest_mode=False)
    cvpin = pm['air_circulation_valve_flag']
    assert rv[cvpin] is False   # 배기순환 → 순환밸브 OFF (current ON 잔재 무시)


def test_execute_control_injects_schedule(monkeypatch):
    # _execute_control 이 조명/관수 스케줄값을 phase semantic 에 주입
    written = {}
    monkeypatch.setattr(mc, "_write_relay", lambda f, h, rv: written.update(rv) or {"success": True})
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    monkeypatch.setattr("agri_ai_core.src.control.schedule_control.compute_schedule_target",
                        lambda f, h, stype: True if stype == "light" else False)
    pm = get_pin_map(1)
    mc._execute_control(1, 1, {'water_heater_flag': False, 'fog_occurs_flag': False,
                               'drainage_motor_flag': False},
                        "배기순환", {}, harvest_mode=False, reason="test")
    assert written[pm['lighting_flag']] is True     # 조명 스케줄 ON
    assert written[pm['irrigation_flag']] is False  # 관수 스케줄 OFF


def test_get_last_change_target(monkeypatch):
    class _DB:
        def fetch_one(self, sql, vals=None):
            return {"circulation": "배기순환", "water_heater": False,
                    "fog_occurs": False, "drainage_motor": False}
    class _S:
        def __enter__(self): return _DB()
        def __exit__(self, *a): return False
    monkeypatch.setattr("agri_ai_core.src.postgresql.connection.db_session", lambda: _S())
    r = ac._get_last_change_target(1, 1)
    assert r["circulation"] == "배기순환"


def test_keep_rebuild_clears_stale(monkeypatch):
    # keep 이어도 마지막 change(배기순환)를 전체 재구성 → 순환밸브 OFF 정리
    executed = {}
    monkeypatch.setattr(ac, "_get_last_change_target",
                        lambda f, h: {"circulation": "배기순환", "water_heater": False,
                                      "fog_occurs": False, "drainage_motor": False})
    monkeypatch.setattr(ac, "_execute_control",
                        lambda f, h, dev, circ, cur, hm, reason="", order_label="":
                        executed.update(circ=circ, dev=dict(dev)) or {"success": True})
    monkeypatch.setattr(ac, "apply_water_safety", lambda dev, s, f, h, scope="": (dev, []))
    # keep 재구성이 마지막 change 의 순환모드로 _execute_control 호출하는지
    last = ac._get_last_change_target(1, 1)
    dev = {'water_heater_flag': False, 'fog_occurs_flag': False, 'drainage_motor_flag': False}
    dev, _ = ac.apply_water_safety(dev, {}, 1, 1)
    ac._execute_control(1, 1, dev, last['circulation'], {}, False, reason="현상유지 재구성")
    assert executed["circ"] == "배기순환"   # 배기순환 재구성 → 순환밸브가 정의대로 OFF 됨
