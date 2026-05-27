# ══════════════════════════════════════════════════════════════════════════════
# test_external_api_tool — 범용 외부 API 도구 검증
#
# 목적: 신규 외부 연동을 코드 변경 없이 DB 등록(manage_external_api)만으로
#       처리하는 체계 — 등록 권한/템플릿 치환/ENV 키/SSRF 차단.
#
# 파일 시작 함수 목록:
#   test_register_admin_only     : 농장계정 등록 거부
#   test_register_list_get       : 등록 → 목록/상세 조회 왕복
#   test_call_url_substitution   : {param} URL 인코딩 치환 + {ENV:} 키 치환
#   test_call_missing_param      : 필수 파라미터 누락 오류
#   test_private_host_blocked    : 사설/루프백 호스트 등록 차단
#   test_call_unknown_api        : 미등록 API 호출시 목록 안내
#   test_weather_backstop        : 농장 날씨 질문 → get_weather_forecast 자동 병행
# ══════════════════════════════════════════════════════════════════════════════
import os
import json

from agri_ai_core.src.ai.tools_external_api import (
    manage_external_api, call_external_api, _render_url, _is_private_host,
)

_TEST_API = "pytest_sample_api"


def _cleanup():
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("DELETE FROM external_api_m WHERE api_name = %s", (_TEST_API,))


def test_register_admin_only():
    r = manage_external_api("register", api_name=_TEST_API,
                            description="x", url_template="https://example.com/{q}",
                            auth_farm_id="1")
    assert r["success"] is False and "관리자" in r["error"]


def test_register_list_get():
    _cleanup()
    r = manage_external_api("register", api_name=_TEST_API,
                            description="pytest 시험용",
                            url_template="https://example.com/api?q={q}",
                            response_hint="시험", auth_farm_id=None)
    assert r["success"] is True
    lst = manage_external_api("list")
    assert any(a["api_name"] == _TEST_API for a in lst["apis"])
    g = manage_external_api("get", api_name=_TEST_API)
    assert g["success"] is True and g["api"]["url_template"].startswith("https://example.com")
    _cleanup()


def test_call_url_substitution(monkeypatch):
    monkeypatch.setenv("PYTEST_FAKE_KEY", "sekret")
    url = _render_url(
        "https://example.com/api?key={ENV:PYTEST_FAKE_KEY}&q={q}&n={n}",
        {"q": "정읍 날씨&비", "n": 3})
    assert "key=sekret" in url
    assert "q=%EC%A0%95%EC%9D%8D%20%EB%82%A0%EC%94%A8%26%EB%B9%84" in url  # 인코딩 — & 주입 불가
    assert url.endswith("n=3")


def test_call_missing_param():
    try:
        _render_url("https://example.com/{a}/{b}", {"a": "1"})
        assert False, "누락 오류가 나야 함"
    except ValueError as e:
        assert "b" in str(e)


def test_private_host_blocked():
    for bad in ("http://127.0.0.1/x", "http://localhost/x",
                "http://192.168.0.10/x", "http://172.20.1.1/x", "http://10.0.0.5/x"):
        assert _is_private_host(bad) is True
        r = manage_external_api("register", api_name=_TEST_API, description="x",
                                url_template=bad, auth_farm_id=None)
        assert r["success"] is False
    assert _is_private_host("https://apis.data.go.kr/x") is False


def test_call_unknown_api():
    r = call_external_api("no_such_api_xyz")
    assert r["success"] is False and "미등록" in r["error"]


def test_weather_backstop(monkeypatch):
    # "웹에서 검색해서" 표현의 농장 날씨 질문 →
    # ANALYZER 가 웹검색만 계획해도 get_weather_forecast 자동 병행
    from agri_ai_core.src.ai.pipeline.data_collector import DataCollector
    calls = []
    dc = DataCollector(default_tool_args={"get_weather_forecast": {"farm_id": "1"}},
                       raw_user_query="자연들에 농장의 현재 날씨를 웹에서 검색해서 알려줘.")

    def fake_execute(tool_name, args):
        calls.append((tool_name, dict(args)))
        return json.dumps({"success": True, "message": "온도 24℃ 예보"})

    monkeypatch.setattr("agri_ai_core.src.ai.tools_executor.execute_tool", fake_execute)
    monkeypatch.setattr("agri_ai_core.src.ai.llm_client._refine_tool_result",
                        lambda t, r, q: r)
    dc._ensure_weather_data()
    assert [c[0] for c in calls] == ["get_weather_forecast"]

    # 농장 문맥 없는 타지역 날씨 → 개입 안 함
    calls.clear()
    dc2 = DataCollector(default_tool_args={}, raw_user_query="서울 내일 날씨 알려줘.")
    dc2._ensure_weather_data()
    assert calls == []

    # 농장명 언급(문맥 단어 없이) → DB 농장명 매칭 + 언급 농장으로 조회
    calls.clear()
    dc3 = DataCollector(default_tool_args={}, raw_user_query="고흥뜰에 내일 비 오는지 예보 알려줘.")
    dc3._ensure_weather_data()
    assert [c[0] for c in calls] == ["get_weather_forecast"]
    assert calls[0][1].get("farm_id") == "2"  # 세션이 아닌 질문 언급 농장

    # ANALYZER 가 직접 계획한 호출도 언급 농장으로 교정
    dc4 = DataCollector(default_tool_args={"get_weather_forecast": {"farm_id": "1"}},
                        raw_user_query="고흥뜰에 주소를 확인하고 현재 날씨정보를 알려줘.")
    merged = dc4._merge_args("get_weather_forecast", {})
    assert merged["farm_id"] == "2"

    # 복수 농장 언급 → 교정 없음(세션 유지)
    dc5 = DataCollector(default_tool_args={"get_weather_forecast": {"farm_id": "1"}},
                        raw_user_query="자연들에와 고흥뜰에 날씨를 비교해줘.")
    merged5 = dc5._merge_args("get_weather_forecast", {})
    assert merged5["farm_id"] == "1"
