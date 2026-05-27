# ══════════════════════════════════════════════════════════════════════════════
# test_directive_safety_net — 관리자 지속지시 세이프티넷 검증
#
# 지속 표현("유지/별도 지시까지") 요청에서 ANALYZER 가 set_admin_directive
# 계획을 누락해도 data_collector 가 control_relay 인자를 복사해
# 기계적으로 등록을 보장한다.
#
# 파일 시작 함수 목록:
#   test_net_registers_on_persist_keyword : 지속 키워드 + relay 성공 → 자동 등록
#   test_net_skips_without_keyword        : 지속 키워드 없음 → 개입 안 함
#   test_net_releases_on_release_keyword  : 해제 표현 + relay 실행 → 자동 해제
#   test_net_release_without_relay_holds  : 해제 표현 + relay 없음 → 개입 보류
#   test_net_release_all_houses           : 해제 devices 리스트형 + all → 장치별 해제
#   test_net_skips_if_already_planned     : LLM이 이미 등록했으면 중복 등록 안 함
#   test_net_devices_list_multi           : devices 리스트형 + all → 장치별 등록
#   test_net_ignores_unknown_action       : toggle 등 상태불명 액션은 지시화 금지
#   test_net_intent_contamination_ignored : intent(LLM요약) 오염돼도 원문 기준 판정
#   test_net_wrong_direction_not_blocking : LLM이 반대 도구(release) 오호출해도 등록 보장
#   test_resolve_physical_farm            : farm 0(시스템) → 첫 실농장 자동 대체
# ══════════════════════════════════════════════════════════════════════════════
import json

from agri_ai_core.src.ai.pipeline.data_collector import DataCollector


def _make_collector(monkeypatch, raw_query, calls_log):
    dc = DataCollector(
        default_tool_args={"set_admin_directive": {"farm_id": "1", "auth_farm_id": None}},
        raw_user_query=raw_query,
    )

    def fake_execute(tool_name, args):
        calls_log.append((tool_name, dict(args)))
        return json.dumps({"success": True, "message": "ok"})

    monkeypatch.setattr(
        "agri_ai_core.src.ai.tools_executor.execute_tool", fake_execute)
    monkeypatch.setattr(
        "agri_ai_core.src.ai.llm_client._refine_tool_result",
        lambda tool, raw, q: raw)
    return dc


def _relay_call(args):
    return {"tool": "control_relay", "success": True, "args": args}


def test_net_registers_on_persist_keyword(monkeypatch):
    calls = []
    dc = _make_collector(monkeypatch, "2호재배사 수온히터 별도 지시 있을때 까지 꺼줘.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "0", "house_id": "2", "device_name": "water_heater_flag", "action": "off"}))
    dc._ensure_admin_directive("2호 수온히터 끄기")
    directive_calls = [c for c in calls if c[0] == "set_admin_directive"]
    assert len(directive_calls) == 1
    a = directive_calls[0][1]
    assert a["farm_id"] == "0" and a["house_id"] == "2"
    assert a["device_name"] == "water_heater_flag" and a["state"] == "OFF"
    assert a["auth_farm_id"] is None  # 기본 인자 병합 확인


def test_net_skips_without_keyword(monkeypatch):
    calls = []
    dc = _make_collector(monkeypatch, "2호 수온히터 꺼줘.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "1", "house_id": "2", "device_name": "water_heater_flag", "action": "off"}))
    dc._ensure_admin_directive("2호 수온히터 끄기")
    assert calls == []


def test_net_releases_on_release_keyword(monkeypatch):
    # "유지 지시를 해제해주라" 에 LLM이 release 도구 대신 control_relay 만
    # 호출한 경우 → 세이프티넷이 인자를 복사해 해제를 보장해야 함
    calls = []
    dc = _make_collector(monkeypatch, "수온히터 유지 지시 해제하고 켜줘.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "1", "house_id": "2", "device_name": "water_heater_flag", "action": "on"}))
    dc._ensure_admin_directive("유지 해제 후 켜기")
    release_calls = [c for c in calls if c[0] == "release_admin_directive"]
    assert len(release_calls) == 1
    a = release_calls[0][1]
    assert a["house_id"] == "2" and a["device_name"] == "water_heater_flag"
    assert not [c for c in calls if c[0] == "set_admin_directive"]  # 등록으로 오동작 금지


def test_net_release_without_relay_holds(monkeypatch):
    # 해제 표현이지만 control_relay 미실행 → 대상 불명, 코드 임의판단 금지(보류)
    calls = []
    dc = _make_collector(monkeypatch, "모든 유지 지시를 해제해주라.", calls)
    dc._ensure_admin_directive("지시 해제")
    assert calls == []


def test_net_release_all_houses(monkeypatch):
    # control_relay(all, devices 리스트) 만 실행된 해제 요청
    calls = []
    dc = _make_collector(monkeypatch, "모든 재배사의 수온히터 유지 지시를 해제해주라.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "0", "house_id": "all",
         "devices": [{"device_name": "water_heater_flag", "action": "off"}]}))
    dc._ensure_admin_directive("전체 수온히터 유지 해제")
    release_calls = [c for c in calls if c[0] == "release_admin_directive"]
    assert len(release_calls) == 1
    a = release_calls[0][1]
    assert a["house_id"] == "all" and a["device_name"] == "water_heater_flag"


def test_net_skips_if_already_planned(monkeypatch):
    calls = []
    dc = _make_collector(monkeypatch, "모든 재배사 수온히터 별도 지시할때 까지 OFF 유지.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "1", "house_id": "all", "device_name": "water_heater_flag", "action": "off"}))
    dc.tool_calls_detail.append({"tool": "set_admin_directive", "success": True, "args": {}})
    dc._ensure_admin_directive("전체 OFF 유지")
    assert calls == []


def test_net_devices_list_multi(monkeypatch):
    calls = []
    dc = _make_collector(monkeypatch, "히터랑 포그 내가 별도 지시할때 까지 꺼둬.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "1", "house_id": "all",
         "devices": [{"device_name": "water_heater_flag", "action": "off"},
                     {"device_name": "fog_valve_flag", "action": "off"}]}))
    dc._ensure_admin_directive("전체 히터·포그 OFF 유지")
    directive_calls = [c for c in calls if c[0] == "set_admin_directive"]
    assert len(directive_calls) == 2
    assert {c[1]["device_name"] for c in directive_calls} == {"water_heater_flag", "fog_valve_flag"}
    assert all(c[1]["house_id"] == "all" and c[1]["state"] == "OFF" for c in directive_calls)


def test_net_ignores_unknown_action(monkeypatch):
    calls = []
    dc = _make_collector(monkeypatch, "순환팬 계속 지금 상태로 유지해줘.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "1", "house_id": "1", "device_name": "circulation_fan_flag", "action": "toggle"}))
    dc._ensure_admin_directive("순환팬 유지")
    assert calls == []


def test_net_intent_contamination_ignored(monkeypatch):
    # 원문은 순수 유지 요청인데 intent(LLM 요약)에 "해제/복귀" 가 섞인
    # 경우 → 원문 기준으로 등록이어야 하며 해제 오작동 금지
    calls = []
    dc = _make_collector(monkeypatch,
                         "자연들에 모든 재배사의 수온히터를 내가 별도 지시하기 전까지 OFF하라.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "0", "house_id": "all",
         "devices": [{"device_name": "water_heater_flag", "action": "off"}]}))
    dc._ensure_admin_directive("수온히터 OFF 후 지시 시 자율 제어 복귀 및 기존 지시 해제")
    assert [c[0] for c in calls] == ["set_admin_directive"]
    assert calls[0][1]["state"] == "OFF"


def test_net_wrong_direction_not_blocking(monkeypatch):
    # LLM 이 유지 요청에 release_admin_directive 를 잘못 호출한 경우 —
    # 반대 방향 실행은 "이미 처리됨" 으로 취급하지 않고 등록을 보장
    calls = []
    dc = _make_collector(monkeypatch,
                         "모든 재배사 수온히터 별도 지시할때 까지 OFF 유지하라.", calls)
    dc.tool_calls_detail.append(_relay_call(
        {"farm_id": "1", "house_id": "all",
         "devices": [{"device_name": "water_heater_flag", "action": "off"}]}))
    dc.tool_calls_detail.append({"tool": "release_admin_directive", "success": True, "args": {}})
    dc._ensure_admin_directive("전체 수온히터 OFF 유지")
    assert [c[0] for c in calls] == ["set_admin_directive"]


def test_resolve_physical_farm():
    from agri_ai_core.src.ai.tools_admin import _resolve_physical_farm
    assert _resolve_physical_farm("0") == "1"   # 시스템농장 → 첫 실농장(자연들에)
    assert _resolve_physical_farm("1") == "1"
    assert _resolve_physical_farm("2") == "2"
