# ══════════════════════════════════════════════════════════════════════════════
# test_admin_directive — 관리자 강제 지시 메커니즘 검증
#
# 사용자 절대 요구: "관리자가 지시한 내용을 강제로 이행할 수단".
# 우선순위: 인터록(물리) > 관리자지시 > 비상가드 > LLM.
#
# 파일 시작 함수 목록:
#   test_set_get_release_roundtrip : 등록→조회→해제 실DB 왕복
#   test_apply_forces_relay_values : relay_values 강제 적용 (LLM 값 덮어씀)
#   test_prompt_block_format       : 제어 LLM 주입 블록 생성
#   test_invalid_semantic_rejected : 잘못된 장치명 거부
#   test_tool_all_houses           : 채팅 도구 all 확장 + 해제
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.control.admin_directive import (
    set_directive, release_directive, get_active,
    apply_to_relay_values, format_prompt_block,
)
from agri_ai_core.src.control.control_common import get_pin_map

F, H = 1, 99   # 테스트 전용 (house 99 — 운영 재배사 아님)


def _cleanup():
    for sem in ("water_heater_flag", "lighting_flag"):
        release_directive(F, H, sem)


def test_set_get_release_roundtrip():
    _cleanup()
    r = set_directive(F, H, "water_heater_flag", False, note="테스트 OFF 유지")
    assert r["success"] is True
    act = get_active(F, H)
    assert act["water_heater_flag"]["forced_value"] is False
    r2 = release_directive(F, H, "water_heater_flag")
    assert r2["success"] is True
    assert "water_heater_flag" not in get_active(F, H)


def test_apply_forces_relay_values():
    _cleanup()
    set_directive(F, H, "water_heater_flag", False, note="OFF 강제")
    pin_map = get_pin_map(H)
    pin = pin_map["water_heater_flag"]
    relay = {f"relay_{i}st_flag": False for i in range(1, 17)}
    relay[pin] = True   # LLM/비상가드가 ON 을 시도한 상황
    fixed, applied = apply_to_relay_values(F, H, relay, pin_map)
    assert fixed[pin] is False, "관리자 지시(OFF)가 ON 시도를 덮어써야 함"
    assert applied and "water_heater_flag" in applied[0]
    _cleanup()


def test_prompt_block_format():
    _cleanup()
    set_directive(F, H, "water_heater_flag", False, note="사용자 지시")
    block = format_prompt_block(F, H)
    assert "관리자 강제 지시" in block
    assert "water_heater_flag = OFF" in block
    _cleanup()
    assert format_prompt_block(F, H) == ""   # 지시 없으면 빈 문자열


def test_invalid_semantic_rejected():
    r = set_directive(F, H, "nonexistent_flag", True)
    assert r["success"] is False


def test_tool_all_houses():
    from agri_ai_core.src.ai.tools_admin import set_admin_directive, release_admin_directive
    # house 99 단일 (all 은 1~3 운영 재배사 대상이라 단일로 검증)
    r = set_admin_directive(house_id="99", device_name="조명", state="OFF",
                            note="도구 테스트", farm_id="1", auth_farm_id=None)
    assert r["success"] is True and "강제" in r["message"]
    assert get_active(F, H).get("lighting_flag", {}).get("forced_value") is False
    r2 = release_admin_directive(house_id="99", device_name="조명",
                                 farm_id="1", auth_farm_id=None)
    assert r2["success"] is True
    assert "lighting_flag" not in get_active(F, H)
