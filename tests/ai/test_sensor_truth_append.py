# ══════════════════════════════════════════════════════════════════════════════
# test_sensor_truth_append — 센서값 실측 결정론 표 첨부(N/A 근절)
#
# ⛔ 센서는 항상 실측되므로 'N/A' 는 잘못된 표현. get_system_status.sensor 실측으로
#    코드가 최종 표를 붙여 LLM 이 N/A 를 지어내도 실제 숫자가 보이게 한다(2026-07-26).
#
# 파일 시작 함수 목록:
#   test_appends_sensor_table   : 센서 질문에 실측 표 첨부
#   test_missing_shows_dash     : 결측 센서는 '-'(⛔N/A 아님)
#   test_no_append_non_sensor   : 센서 질문 아니면 미첨부
#   test_no_append_tool_absent  : get_system_status 없으면 미첨부
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.pipeline.answer_generator import _append_sensor_truth


def _cr():
    return {"data": [{"tool": "get_system_status", "raw": {"houses": [
        {"house_id": "1", "name": "상황버섯1호재배사",
         "sensor": {"indoor_temperature": 27.286, "indoor_humidity": 100.0,
                    "co2": 1062, "water_temperature": 24.875,
                    "outdoor_temperature": 25.8, "outdoor_humidity": 100.0}},
        {"house_id": "3", "name": "상황버섯3호재배사",
         "sensor": {"indoor_temperature": 28.701, "indoor_humidity": 100.0,
                    "co2": 1029, "water_temperature": None,
                    "outdoor_temperature": 25.8, "outdoor_humidity": 100.0}},
    ]}}]}


def test_appends_sensor_table():
    out = _append_sensor_truth("답변", ["get_system_status"], _cr(),
                               "각 재배사 센서값 온도 습도 보여줘")
    assert "■ 시스템 실측 센서값" in out
    assert "27.3" in out and "1062" in out and "24.9" in out    # 실측 숫자
    assert "N/A" not in out                                      # ⛔N/A 금지


def test_missing_shows_dash():
    # 3호 수온 None → '-' (N/A 아님)
    out = _append_sensor_truth("답변", ["get_system_status"], _cr(), "수온 알려줘")
    # 3호 행에 수온 자리가 '-'
    row3 = [ln for ln in out.splitlines() if "3호" in ln][0]
    assert "| - |" in row3 and "N/A" not in row3


def test_no_append_non_sensor():
    out = _append_sensor_truth("답변", ["get_system_status"], _cr(), "릴레이 상태만 보여줘")
    assert "시스템 실측 센서값" not in out


def test_no_append_tool_absent():
    out = _append_sensor_truth("답변", ["get_camera_view"], _cr(), "센서 온도")
    assert "시스템 실측 센서값" not in out
