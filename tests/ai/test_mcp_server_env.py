# ══════════════════════════════════════════════════════════════════════════════
# test_mcp_server_env — mcp.json 의 서버별 env 블록이 Popen 에 전달되는지
#
# 배경(2026-07-18): 3개 Popen 이 env=os.environ.copy() 만 써서 mcp.json 의 env
#   블록이 무시됐다. searxng(SEARXNG_URL)·naver(CLIENT_ID/SECRET) 는 .env 에 같은
#   키가 우연히 있어야만 동작했고, mcp.json 을 믿고 .env 에서 지우면 조용히 죽었다.
#   korea-weather 의 KOREA_WEATHER_API_KEY 도 이 경로로 전달되어야 한다.
#   ${VAR} VSCode 치환 문법은 os.environ 기준으로 확장한다.
#
# 파일 시작 함수 목록:
#   test_env_block_merged        : env 블록이 os.environ 에 병합됨
#   test_var_expansion           : ${VAR} 가 os.environ 값으로 확장됨
#   test_no_env_block_safe        : env 블록 없는 서버도 안전(os.environ 그대로)
#   test_popen_uses_server_env   : 두 Popen 이 _server_env 를 쓴다(회귀 방지)
# ══════════════════════════════════════════════════════════════════════════════
import inspect
import os

from agri_ai_core.src.ai import mcp_client as mc


def test_env_block_merged():
    e = mc._server_env({"env": {"SEARXNG_URL": "http://127.0.0.1:8888", "K": "v"}})
    assert e["SEARXNG_URL"] == "http://127.0.0.1:8888"
    assert e["K"] == "v"
    assert "PATH" in e, "os.environ 이 보존되어야 함"


def test_var_expansion(monkeypatch):
    monkeypatch.setenv("_MCP_ENV_PROBE", "expanded-value")
    e = mc._server_env({"env": {"TOKEN": "${_MCP_ENV_PROBE}"}})
    assert e["TOKEN"] == "expanded-value", "${VAR} 가 os.environ 값으로 확장되어야 함"


def test_no_env_block_safe():
    e = mc._server_env({"command": "npx", "args": ["-y", "x"]})
    assert isinstance(e, dict) and "PATH" in e
    # None env 값은 무시
    e2 = mc._server_env({"env": {"A": None, "B": "b"}})
    assert "A" not in e2 and e2["B"] == "b"


# ⛔ 회귀 방지: 두 MCP Popen 이 os.environ.copy() 로 되돌아가면 env 블록이 다시 죽는다.
def test_popen_uses_server_env():
    src = inspect.getsource(mc)
    # call_mcp_server_tool / list_mcp_server_tools 의 Popen 이 _server_env(server) 사용
    assert src.count("env=_server_env(server)") >= 2, (
        "MCP 서버 Popen 이 _server_env 를 쓰지 않음 — mcp.json env 블록이 무시된다")
