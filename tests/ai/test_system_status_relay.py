# get_system_status 가 재배사별 릴레이 ON/OFF(semantic)를 포함 — LLM 이 raw SQL 없이
# 모드+릴레이를 한 번에 받도록 (2026-07-19: relay_setting_log 오조회 재발 방지)
from dotenv import load_dotenv
load_dotenv("/workspace/jayeondeule/.env")
from agri_ai_core.src.ai.tools_data import get_system_status


def test_status_includes_relay_lists():
    r = get_system_status("1")
    houses = r.get("houses") or []
    if not houses:
        import pytest; pytest.skip("재배사 없음/DB 불가")
    for h in houses:
        assert "relay_on" in h and "relay_off" in h
        assert isinstance(h["relay_on"], list) and isinstance(h["relay_off"], list)
        # ON+OFF 합이 실제 장치 수(=매핑된 릴레이) 이어야
        assert len(h["relay_on"]) + len(h["relay_off"]) >= 8


def test_system_farm_nested_has_relay():
    r = get_system_status("0")
    for f in (r.get("farms") or []):
        for h in (f.get("houses") or []):
            assert "relay_on" in h and "relay_off" in h


def test_status_includes_last_decision():
    r = get_system_status("1")
    houses = r.get("houses") or []
    if not houses:
        import pytest; pytest.skip("재배사 없음/DB 불가")
    for h in houses:
        assert "last_decision" in h  # 최신 제어 사유(없으면 None) 키 존재
