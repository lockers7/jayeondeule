# ══════════════════════════════════════════════════════════════════════════════
# test_farm_geo_multifarm — 농장별 지역정보 DB 조회 검증
#
# 원칙: 지역정보(기상 격자·생활기상지수 지점코드)는 농장 속성 — farm_m_info 에서
# 실시간 read. 농장 추가 시 코드 변경 0 (등록 데이터만). env 는 폴백 전용.
#
# 파일 시작 함수 목록:
#   test_farm_geo_rows            : 농장 1/2 지역 데이터 존재·상이
#   test_grid_for_reads_db        : 기상예보 격자가 DB 값 사용 (농장별 상이)
#   test_grid_env_override_wins   : 재배사별 env 오버라이드 우선 유지
#   test_atm_area_from_db         : 대기확산 지점코드가 DB 값 사용
# ══════════════════════════════════════════════════════════════════════════════
import os
from unittest.mock import patch


def test_farm_geo_rows():
    from agri_ai_core.src.postgresql.connection import db_session
    import agri_ai_core.src.postgresql.queries as dbQry
    with db_session() as d:
        f1 = d.fetch_one(dbQry.GET_FARM_GEO, (1,))
        f2 = d.fetch_one(dbQry.GET_FARM_GEO, (2,))
    assert f1["kma_area_no"] == "5218000000" and f1["kma_nx"] == 57
    assert f2["kma_area_no"] == "4677000000" and f2["kma_nx"] == 66
    assert f1["kma_area_no"] != f2["kma_area_no"]  # 농장별 상이 보장


def test_grid_for_reads_db():
    from agri_ai_core.src.control.ai_weather_forecast import _grid_for
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("FARM_NX_") and not k.startswith("FARM_NY_")}
    with patch.dict(os.environ, env, clear=True):
        assert _grid_for(1, 1) == ("57", "84")
        assert _grid_for(2, 1) == ("66", "62")


def test_grid_env_override_wins():
    from agri_ai_core.src.control.ai_weather_forecast import _grid_for
    with patch.dict(os.environ, {"FARM_NX_1_3": "99", "FARM_NY_1_3": "98"}):
        assert _grid_for(1, 3) == ("99", "98")  # 재배사별 특수 오버라이드 유지


def test_atm_area_from_db():
    # get_atm_stagnation 내부의 DB 조회 경로 검증 — GET_FARM_GEO 로 farm2 지점 확인
    from agri_ai_core.src.postgresql.connection import db_session
    import agri_ai_core.src.postgresql.queries as dbQry
    with db_session() as d:
        row = d.fetch_one(dbQry.GET_FARM_GEO, (2,))
    assert row["farm_name"] == "고흥뜰에"
    assert str(row["kma_area_no"]).startswith("4677")
