# 릴레이 상태 질문에 get_system_status 실측 표를 결정론적으로 첨부(LLM 오독 보정). 2026-07-20
from agri_ai_core.src.ai.pipeline.answer_generator import _append_relay_truth

def _cr():
    return {"data": [{"tool": "get_system_status", "raw": {"houses": [
        {"house_id":"1","name":"상황버섯1호재배사","relay_on":["배출팬","배출밸브"],
         "relay_off":["포그생성","수온히터","순환밸브"]},
        {"house_id":"2","name":"상황버섯2호재배사","relay_on":["배출팬","배출밸브"],
         "relay_off":["포그생성","수온히터","순환밸브"]},
    ]}}]}

def test_appends_truth_table_for_relay_query():
    # LLM 답변이 1호 포그를 ON 이라 잘못 씀
    ans = "상황버섯1호재배사 포그생성 ON ..."
    out = _append_relay_truth(ans, ["get_system_status"], _cr(), "릴레이 제어 상태를 표로 작성하라")
    assert "시스템 실측 릴레이 상태" in out
    # 실측 표에 1호 포그생성 = OFF 로 표기 (실측이 정확)
    assert "포그생성" in out
    # 표 행에 상황버섯1호재배사 + OFF 들 포함
    assert "상황버섯1호재배사" in out and "OFF" in out.split("시스템 실측")[1]

def test_no_append_when_not_relay_query():
    out = _append_relay_truth("답변", ["get_system_status"], _cr(), "1호 온도 알려줘")
    assert "시스템 실측 릴레이 상태" not in out

def test_no_append_when_tool_absent():
    out = _append_relay_truth("답변", ["get_camera_view"], _cr(), "릴레이 상태")
    assert "시스템 실측 릴레이 상태" not in out
