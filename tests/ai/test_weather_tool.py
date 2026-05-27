# ══════════════════════════════════════════════════════════════════════════════
# test_weather_tool — 채팅 날씨 도구(get_weather_forecast) 검증
#
# 농장 날씨 질문은 farm_m_info 의 KMA 격자 기반 내부 예보로 처리한다
# (웹검색은 존재하지 않는 지명으로 실패 가능).
#
# 파일 시작 함수 목록:
#   test_weather_farm1        : 자연들에(farm 1) 실조회 — 예보 텍스트 반환
#   test_weather_farm2        : 고흥뜰에(farm 2) 실조회 — 주소 헤더 포함
#   test_weather_system_farm  : farm 0(시스템) → 실농장 자동 대체
#   test_weather_in_executor  : tools_executor dispatch 연결 확인
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.tools_data import get_weather_forecast


def test_weather_farm1():
    r = get_weather_forecast("1")
    assert r["success"] is True
    assert "기상청 예보" in r["message"] and "온도" in r["message"]


def test_weather_farm2():
    r = get_weather_forecast("2")
    assert r["success"] is True
    assert "고흥뜰에" in r["message"] and "고흥군" in r["message"]
    assert "강수확률" in r["message"]


def test_weather_system_farm():
    r = get_weather_forecast("0")
    assert r["success"] is True
    assert "자연들에" in r["message"]  # 첫 실농장 대체


def test_weather_in_executor():
    from agri_ai_core.src.ai.tools_executor import execute_tool
    import json
    raw = execute_tool("get_weather_forecast", {"farm_id": "1"})
    parsed = json.loads(raw)
    assert parsed.get("success") is True
