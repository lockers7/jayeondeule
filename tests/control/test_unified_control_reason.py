# ══════════════════════════════════════════════════════════════════════════════
# test_unified_control_reason — 통합 제어사유 이력 검증
#
# 원칙: 모든 제어 주체(AI 사이클·구독 Agent·채팅 지시)의 릴레이 변경 사유가
# ai_decision_log 한 곳에서 조회돼야 "왜 제어했나" 질문에 항상 답할 수 있다.
# 기록은 best-effort — 실패해도 제어 흐름 불변.
#
# 파일 시작 함수 목록:
#   test_record_external_action_payload : source 태그·장치 상세·사유 기록 형식
#   test_chat_control_records_reason    : 채팅 릴레이 제어 성공 시 자동 기록
#   test_agent_exec_records_reason      : Agent set_relay 성공 시 큐 reason 포함 기록
#   test_record_failure_is_silent       : 기록 실패가 제어 결과를 깨지 않음
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.control import ai_decision_log as adl


def test_record_external_action_payload(monkeypatch):
    captured = {}

    def fake_record(farm_id, house_id, **kw):
        captured.update(farm=farm_id, house=house_id, **kw)
        return 123

    monkeypatch.setattr(adl, "record_decision", fake_record)
    rid = adl.record_external_action("채팅지시", "1", "2",
                                     {"drainage_motor_flag": True, "exhaust_fan_flag": True},
                                     "사용자 채팅 지시")
    assert rid == 123
    assert captured["farm"] == 1 and captured["house"] == 2
    assert captured["action"] == "채팅지시_control"
    assert captured["drainage_motor"] is True
    assert "[채팅지시]" in captured["reason"] and "exhaust_fan_flag=ON" in captured["reason"]


def test_chat_control_records_reason(monkeypatch):
    from agri_ai_core.src.ai import tools_control as tc
    recorded = {}
    monkeypatch.setattr("agri_ai_core.src.control.relay_manager.set_relay_value",
                        lambda f, h, s, **kw: {"success": True, "message": "ok"})
    monkeypatch.setattr("agri_ai_core.src.control.ai_decision_log.record_external_action",
                        lambda src, f, h, dv, rsn: recorded.update(src=src, farm=f, house=h, dv=dv))
    monkeypatch.setattr(tc, "_build_post_control_snapshot", lambda f, h: {}, raising=False)
    r = tc.control_relay(house_id="2", device_name="배출팬", action="on",
                         farm_id="1", auth_farm_id=None)
    assert r.get("success"), r
    assert recorded["src"] == "채팅지시" and recorded["dv"].get("exhaust_fan_flag") is True


def test_agent_exec_records_reason(monkeypatch):
    from agri_ai_core.src.control import agent_pending_worker as apw
    recorded = {}
    monkeypatch.setattr("agri_ai_core.src.control.relay_manager.set_relay_value",
                        lambda f, h, s, raw_mode=False: {"success": True, "message": "ok"})
    monkeypatch.setattr("agri_ai_core.src.control.ai_decision_log.record_external_action",
                        lambda src, f, h, dv, rsn: recorded.update(src=src, rsn=rsn, dv=dv))
    out = apw._exec_set_relay({"farm_id": 1, "house_id": 1,
                               "semantic": "drainage_motor_flag", "on": True,
                               "reason": "습도 100% 초과 대응"})
    assert out["success"]
    assert recorded["src"] == "Agent조치" and "습도 100%" in recorded["rsn"]
    assert recorded["dv"] == {"drainage_motor_flag": True}


def test_record_failure_is_silent(monkeypatch):
    from agri_ai_core.src.control import agent_pending_worker as apw
    monkeypatch.setattr("agri_ai_core.src.control.relay_manager.set_relay_value",
                        lambda f, h, s, raw_mode=False: {"success": True, "message": "ok"})
    monkeypatch.setattr("agri_ai_core.src.control.ai_decision_log.record_external_action",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB down")))
    out = apw._exec_set_relay({"farm_id": 1, "house_id": 1,
                               "semantic": "fog_occurs_flag", "on": False})
    assert out["success"]   # 기록 실패해도 제어 결과 보존
