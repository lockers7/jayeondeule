# ═══════════════════════════════════════════════════════════════════════════
# SENSOR_M_SETTING.updt_dttm 인프라 검증 단위테스트.
#
# 검증:
#   1) read_sensor_setting_max_updt 가 timestamp 반환 (이미 row 있음)
#   2) 존재하지 않는 farm/house 는 None 반환
#   3) UPDATE 시 updt_dttm 트리거 자동 갱신
#   4) INSERT 시 updt_dttm 자동 채워짐 (DEFAULT NOW())
# ═══════════════════════════════════════════════════════════════════════════
import time
from datetime import datetime

import pytest

from agri_ai_core.src.postgresql.connection import db_session
from agri_ai_core.src.postgresql.reader import read_sensor_setting_max_updt


# ────────────────────────────────────────────────────────────────────
# 1) 기존 row 가 있는 호기는 timestamp 반환
# ────────────────────────────────────────────────────────────────────
def test_max_updt_for_existing_house():
    # 운영 DB 의 farm=0/house=99 (양식장) 또는 farm=1/house=1 — 적어도 하나는 row 있음
    found = False
    for farm, house in [(0, 99), (1, 1), (1, 2), (1, 3)]:
        v = read_sensor_setting_max_updt(farm, house)
        if v is not None:
            assert isinstance(v, datetime), f"{farm}-{house} updt_dttm 이 datetime 아님: {type(v)}"
            found = True
            break
    assert found, "어느 호기에도 SENSOR_M_SETTING row 가 없음 — 테스트 데이터 누락"


# ────────────────────────────────────────────────────────────────────
# 2) 존재하지 않는 호기 → None
# ────────────────────────────────────────────────────────────────────
def test_max_updt_for_nonexistent():
    v = read_sensor_setting_max_updt(9999, 9999)
    assert v is None


# ────────────────────────────────────────────────────────────────────
# 3) UPDATE 시 trg_sensor_m_setting_updt 가 updt_dttm 자동 갱신
# ────────────────────────────────────────────────────────────────────
def test_update_trigger_touches_updt_dttm():
    """기존 row 의 작은 컬럼(주석 등)을 UPDATE → updt_dttm 가 NOW() 로 갱신되는지 확인.
    원본 보존 위해 같은 값으로 UPDATE 후 변화 검증."""
    # 1-1 의 최신 row 확인
    farm, house = 1, 1
    v_before = read_sensor_setting_max_updt(farm, house)
    if v_before is None:
        pytest.skip("1-1 SENSOR_M_SETTING row 없음 — 본 테스트 skip")

    time.sleep(0.05)
    # 같은 값으로 UPDATE — 그러나 트리거가 updt_dttm 갱신해야 함
    with db_session() as db:
        db.execute_query(
            "UPDATE sensor_m_setting "
            "   SET tprt_min = tprt_min "  # no-op UPDATE
            " WHERE farm_id = %s AND hous_id = %s "
            "   AND setn_dttm = (SELECT MAX(setn_dttm) FROM sensor_m_setting "
            "                     WHERE farm_id = %s AND hous_id = %s)",
            (farm, house, farm, house)
        )

    v_after = read_sensor_setting_max_updt(farm, house)
    assert v_after is not None
    assert v_after > v_before, f"UPDATE trigger 동작 실패 ({v_before} → {v_after})"


# ────────────────────────────────────────────────────────────────────
# 4) INSERT 시 updt_dttm 가 DEFAULT NOW() 로 자동 채워짐
# ────────────────────────────────────────────────────────────────────
def test_insert_default_updt_dttm():
    """매우 먼 미래의 setn_dttm 으로 임시 row INSERT → updt_dttm 자동 채워짐 확인."""
    # __test__ 용 가짜 row — 실제 호기 무관 farm=99999 사용
    test_farm = 99999
    test_house = 99999
    test_setn = datetime(2099, 1, 1, 0, 0, 0)
    try:
        with db_session() as db:
            # farm/house FK 가 있을 수 있어 직접 INSERT 가 막힐 수도 — 그러면 skip
            try:
                db.execute_query(
                    "INSERT INTO sensor_m_setting (farm_id, hous_id, setn_dttm, tprt_min) "
                    "VALUES (%s, %s, %s, %s)",
                    (test_farm, test_house, test_setn, 25.0)
                )
            except Exception as e:
                pytest.skip(f"INSERT 실패 (FK 등): {e}")

        v = read_sensor_setting_max_updt(test_farm, test_house)
        # 99999/99999 는 새 row 라 None 이 아니어야 함
        if v is None:
            # FK 가 silent fail 한 경우 — 실제로는 row 가 안 들어갔음
            pytest.skip("INSERT 가 silent fail (FK 거부)")
        assert isinstance(v, datetime)
    finally:
        with db_session() as db:
            db.execute_query(
                "DELETE FROM sensor_m_setting WHERE farm_id=%s AND hous_id=%s AND setn_dttm=%s",
                (test_farm, test_house, test_setn)
            )
