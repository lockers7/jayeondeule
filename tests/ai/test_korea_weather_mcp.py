# ══════════════════════════════════════════════════════════════════════════════
# test_korea_weather_mcp — korea-weather MCP 서버 기동 설정 검증
#
# 배경(2026-07-17 실측): mcp.json 이 `uvx --from git+... korea_weather` 로 등록돼
#   있었으나 실행 시 "Package `korea-weather` does not provide any executables."
#   로 즉사 → tools/list 무응답. 원인은 API 키가 아니라 진입점이었다.
#   저장소는 pyproject 에 console_scripts 가 없고 py-modules=["korea_weather"] +
#   [tool.smithery] server="korea_weather:create_server" 인 단일 모듈이라,
#   `create_server().run(transport="stdio")` 를 직접 띄워야 한다.
#
# 키(KOREA_WEATHER_API_KEY)는 도구 목록 조회에는 불필요하고 실제 날씨 조회에만
#   필요하다 — 서버 26~29행이 키 부재 시 load_dotenv() 만 하고 죽지 않기 때문.
#
# 파일 시작 함수 목록:
#   test_korea_weather_registered          : 실제 설정에 서버가 등록돼 있음
#   test_config_uses_uv_run_not_uvx        : ⛔ 실행파일 없는 uvx 방식 회귀 방지
#   test_config_entrypoint_runs_stdio      : -c 진입점이 stdio 서버를 띄움
#   test_gateway_lists_three_tools         : (live) 게이트웨이로 도구 3종 발견
#   test_missing_key_gives_clear_error     : (live) 키 부재 시 LLM 이 읽을 메시지
# ══════════════════════════════════════════════════════════════════════════════
import os

import pytest

from agri_ai_core.src.ai import mcp_client as mc

_SERVER = "korea-weather"
_REPO = "git+https://github.com/ohhan777/korea_weather.git"

# 실제 uv 실행 + 네트워크(git clone/캐시)가 필요해 회귀 스위트에서는 제외.
# 수동 검증: AGRI_MCP_LIVE=1 pytest tests/ai/test_korea_weather_mcp.py
_live = pytest.mark.skipif(
    not os.getenv("AGRI_MCP_LIVE"),
    reason="uv 실행 + 네트워크 필요 — AGRI_MCP_LIVE=1 로 수동 실행",
)


def _cfg():
    servers = mc._load_mcp_servers()
    assert _SERVER in servers, f"{_SERVER} 가 mcp.json 에 없음"
    return servers[_SERVER]


def test_korea_weather_registered():
    assert _cfg().get("command"), "command 미지정 → 기동 불가"


# ⛔ 회귀 방지 (2026-07-17): korea-weather 패키지는 실행파일을 제공하지 않는다.
#   uvx 는 실행파일을 찾아 실행하는 도구이므로 어떤 인자를 줘도 이 서버는 못 띄운다.
def test_config_uses_uv_run_not_uvx():
    cfg = _cfg()
    assert cfg["command"] == "uv", (
        f"command 가 'uv' 여야 함 (현재 {cfg['command']!r}) — "
        "uvx 는 'does not provide any executables' 로 즉사")
    args = [str(a) for a in cfg.get("args", [])]
    assert args[0] == "run", "uv 의 첫 인자는 'run'"
    assert "--with" in args and _REPO in args, "저장소를 --with 로 설치해야 함"
    assert "--from" not in args, "--from 은 uvx 실행파일 방식의 잔재"


def test_config_entrypoint_runs_stdio():
    args = [str(a) for a in _cfg().get("args", [])]
    assert "python" in args and "-c" in args, "모듈을 직접 띄우는 -c 진입점이어야 함"
    payload = args[args.index("-c") + 1]
    assert "create_server" in payload, "smithery 진입점 create_server 호출 필요"
    # 우리 클라이언트는 stdio(JSON-RPC over pipe) 전용 — http 면 응답을 못 읽는다
    assert "stdio" in payload, "transport 는 stdio 여야 함"


@_live
def test_gateway_lists_three_tools():
    from agri_ai_core.src.ai.tools_mcp_gateway import mcp_list_tools

    r = mcp_list_tools(_SERVER)
    assert r.get("success") is not False, f"조회 실패: {r.get('error')}"
    names = {t.get("name") for t in (r.get("tools") or [])}
    assert {"get_nowcast_observation",
            "get_nowcast_forecast",
            "get_short_term_forecast"} <= names, f"도구 누락: {names}"


@_live
@pytest.mark.skipif(
    bool(os.getenv("KOREA_WEATHER_API_KEY")),
    reason="키가 설정돼 있으면 부재 메시지를 검증할 수 없음",
)
def test_missing_key_gives_clear_error():
    from agri_ai_core.src.ai.tools_mcp_gateway import mcp_call

    r = mcp_call(_SERVER, "get_nowcast_observation", {"lon": 127.285, "lat": 34.611})
    # 키가 없어도 MCP 통신 자체는 성공해야 하고(서버가 죽지 않음),
    # LLM 이 원인을 알 수 있게 결과 텍스트로 사유가 와야 한다.
    assert "KOREA_WEATHER_API_KEY" in str(r.get("result", "")), (
        f"키 부재 사유가 결과에 없음: {r}")
