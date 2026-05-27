# ══════════════════════════════════════════════════════════════════════════════
# test_sensor_fault_log_throttle — 센서 결함값 로그 스로틀 (logger.warning 직접 카운트)
# ══════════════════════════════════════════════════════════════════════════════
import agri_ai_core.src.postgresql.reader as reader


def _faulty():
    return {'water_temperature': 0.0, 'indoor_temperature': 25.0, 'indoor_humidity': 60.0,
            'outdoor_temperature': 20.0, 'outdoor_humidity': 50.0, 'co2': 800.0}


def _patch_warn(monkeypatch):
    msgs = []
    monkeypatch.setattr(reader.logger, "warning", lambda m, *a, **k: msgs.append(str(m)))
    return msgs


def test_fault_filtered_and_log_throttled(monkeypatch):
    reader._FAULT_LOG_LAST.clear()
    msgs = _patch_warn(monkeypatch)
    monkeypatch.setattr(reader, "_db_query", lambda *a, **k: _faulty())
    results = [reader.read_current_sensor_info(1, 3) for _ in range(5)]
    # 1) 결함값 매번 None(안전 유지)
    assert all(r['water_temperature'] is None for r in results)
    # 2) 정상값 보존
    assert all(r['indoor_temperature'] == 25.0 for r in results)
    # 3) 수온 결함 로그 1회만(스로틀)
    wt = [m for m in msgs if "수온 결함값" in m]
    assert len(wt) == 1, f"수온 결함 로그 {len(wt)}회 (1회여야)"


def test_state_change_relogs(monkeypatch):
    reader._FAULT_LOG_LAST.clear()
    msgs = _patch_warn(monkeypatch)
    seq = iter([_faulty(), {'water_temperature': 22.0, 'indoor_temperature': 25.0}, _faulty()])
    monkeypatch.setattr(reader, "_db_query", lambda *a, **k: next(seq))
    for _ in range(3):
        reader.read_current_sensor_info(1, 3)
    wt = [m for m in msgs if "수온 결함값" in m]
    assert len(wt) == 2, f"상태변화 재로깅 {len(wt)}회 (2회여야)"
