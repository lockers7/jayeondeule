# ══════════════════════════════════════════════════════════════════════════════
# test_camera_view_tool — get_camera_view 채팅 도구 (5중 등록 + 가드)
#
# 배경(2026-07-19): 채팅 LLM 에 카메라 도구가 없어 "camera-control 서버를 찾을 수
#   없다"는 없는 서버명을 지어내고, 실시간 촬영 대신 farm_knowledge 의 옛 곰팡이
#   기록을 회상했다. capture_image+analyze_vision_llm(gemma3 멀티모달)+heuristics 를
#   get_camera_view 도구로 노출해 LLM 이 현재 프레임을 직접 판독하게 한다.
#   촬영 실패(원격 보드 미응답) 시 환각 없이 정직한 실패 사유를 반환한다.
#
# 파일 시작 함수 목록:
#   test_zero_house_blocked      : house_id=0(통합재배사) 거부
#   test_none_house_blocked      : house_id 미지정 거부
#   test_capture_fail_honest     : 촬영 실패 시 정직한 실패 dict (환각 없음)
#   test_capture_success_shape   : 촬영 성공 시 heuristics/vision/summary 포함
#   test_five_fold_registration  : ⛔ 5중 등록 정합 (정의/실행/분석기/DB도구/DB프롬프트)
# ══════════════════════════════════════════════════════════════════════════════
from unittest.mock import patch

from agri_ai_core.src.ai.tools_data import get_camera_view


def test_zero_house_blocked():
    r = get_camera_view(farm_id="1", house_id="0")
    assert r.get("success") is False and "0" in str(r.get("error", ""))


def test_none_house_blocked():
    r = get_camera_view(farm_id="1", house_id=None)
    assert r.get("success") is False


def test_capture_fail_honest():
    # 촬영 실패(빈 dict) → 환각 없이 captured=False + 사유
    with patch("agri_ai_core.src.control.ai_camera_vision.get_camera_context",
               return_value={}):
        r = get_camera_view(farm_id="1", house_id="1")
    assert r.get("captured") is False
    assert "촬영 실패" in r.get("message", "")


def test_capture_success_shape():
    fake = {"image_bytes_size": 1234,
            "heuristics": {"brightness": 120.0},
            "vision_text": "자실체 중기, 곰팡이 일부 관찰"}
    with patch("agri_ai_core.src.control.ai_camera_vision.get_camera_context",
               return_value=fake), \
         patch("agri_ai_core.src.control.ai_camera_vision.format_camera_block",
               return_value="[카메라] 자실체 중기"):
        r = get_camera_view(farm_id="1", house_id="1")
    assert r.get("success") is True and r.get("captured") is True
    assert r.get("heuristics") == {"brightness": 120.0}
    assert "곰팡이" in r.get("vision", "")
    assert "카메라" in r.get("summary", "")


# ⛔ 회귀 방지(2026-07-19): 시스템(0) 세션에서 농장명 없이 "1호 재배사 카메라"만 물으면
#   farm_id=0 이 남아 FARM_RPI_CAM_URL_0_1(없음)로 촬영 실패했다. 실농장으로 대체돼야 한다.
def test_system_session_farm_fallback():
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    dc = DataCollector(
        default_tool_args={"get_farm_realtime_data": {"farm_id": "0", "house_id": "1"}},
        raw_user_query="1호 재배사 카메라 보여줘")
    m = dc._merge_args("get_camera_view", {"farm_id": "0", "house_id": "1"})
    assert m.get("farm_id") == "1", "시스템세션 farm 0 → 실농장 대체 실패"
    # house 99(시스템 카메라)는 farm 0 보존
    m99 = dc._merge_args("get_camera_view", {"farm_id": "0", "house_id": "99"})
    assert m99.get("farm_id") == "0", "시스템 카메라(house 99)는 farm 0 유지해야 함"


# ⛔ 5중 등록이 하나라도 빠지면 LLM 이 도구를 못 쓰거나(정의/분석기) DB 가 코드를 덮어(도구/프롬프트) 사라진다.
def test_five_fold_registration():
    from agri_ai_core.src.ai.tools_definition import get_available_tools
    from agri_ai_core.src.ai.pipeline.question_analyzer import _VALID_TOOLS
    from agri_ai_core.src.prompt_registry import get_chunk_by_id

    names = {t.get("function", {}).get("name")
             for t in get_available_tools() if isinstance(t, dict)}
    assert "get_camera_view" in names, "① tools_definition(+DB tool_definition_m) 누락"
    assert "get_camera_view" in _VALID_TOOLS, "③ 분석기 화이트리스트 누락"
    chunk = get_chunk_by_id("chat_analyzer_raw") or ""
    assert "get_camera_view" in chunk, "④⑥ 분석기 프롬프트(DB chat_analyzer_raw) 누락"
