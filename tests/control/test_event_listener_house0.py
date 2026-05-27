# ══════════════════════════════════════════════════════════════════════════════
# test_event_listener_house0 — 단절감지 hous_id=0 제외 회귀 가드
#
# hous_id=0 은 공통/가상 호기(GET_ALL_HOUSES 등 코드베이스 관례상 제외 대상).
# 이벤트리스너 heartbeat 단절감지 쿼리에 제외 조건이 유지되는지 소스 수준에서 검증.
#
# 파일 시작 함수 목록:
#   test_heartbeat_query_excludes_house0 : 단절감지 SQL 에 hous_id != 0 포함
# ══════════════════════════════════════════════════════════════════════════════
import inspect
import re


def test_heartbeat_query_excludes_house0():
    import agri_ai_core.src.control.agent_event_listener as mod
    src = inspect.getsource(mod)
    # 단절감지 쿼리 블록: sensor_l_recording GROUP BY hous_id 조회부에 제외 조건 존재
    m = re.search(r"MAX\(recd_dttm\).*?GROUP BY hous_id", src, re.S)
    assert m is not None, "단절감지 쿼리를 찾지 못함"
    assert "hous_id != 0" in m.group(0), "hous_id=0(공통 호기) 제외 조건이 사라짐"
