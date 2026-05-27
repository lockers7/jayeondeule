# ══════════════════════════════════════════════════════════════════════════════
# test_mcp_call_flatten_tolerance — mcp_call 평탄 인자 관용(회귀)
#
# LLM 이 MCP 도구 인자(query·max_results 등)를 args 로 감싸지 않고 최상위로 평탄하게
# 넘기는 자연스러운 호출을, 에이전트·채팅 두 경로 모두 args 로 자동 병합해 수용해야
# 한다. (2026-07-25 자율 web_scan 에서 paper-search 3회 실패 → 근본수정 후 락인.)
#
# gateway.mcp_call 을 가로채 전달 args 만 검증(서브프로세스 미기동, 결정적).
#
# 파일 시작 함수 목록:
#   test_agent_mcp_call_flattened : 에이전트 경로 평탄 인자 병합
#   test_chat_mcp_call_flattened  : 채팅 경로 평탄 인자 병합
#   test_nested_args_still_work   : 기존 중첩 args 형태 유지
# ══════════════════════════════════════════════════════════════════════════════
import agri_ai_core.src.ai.tools_mcp_gateway as gw


def _capture(monkeypatch):
    captured = {}

    def fake_mcp_call(server=None, tool=None, args=None, timeout=45):
        captured.update({"server": server, "tool": tool, "args": args, "timeout": timeout})
        return {"success": True, "server": server, "tool": tool, "result": "ok"}

    monkeypatch.setattr(gw, "mcp_call", fake_mcp_call)
    return captured


def test_agent_mcp_call_flattened(monkeypatch):
    captured = _capture(monkeypatch)
    from agri_ai_core.src.ai.tools_agent_external import agent_mcp_call
    r = agent_mcp_call(server="paper-search", tool="search_arxiv",
                       query="Phellinus linteus", max_results=5)
    assert r.get("success")
    assert captured["args"].get("query") == "Phellinus linteus"
    assert captured["args"].get("max_results") == 5


def test_chat_mcp_call_flattened(monkeypatch):
    captured = _capture(monkeypatch)
    from agri_ai_core.src.ai.tools_executor import execute_tool
    execute_tool("mcp_call", {"server": "wikipedia", "tool": "search_wikipedia",
                              "query": "상황버섯"})
    assert captured["args"].get("query") == "상황버섯"


def test_nested_args_still_work(monkeypatch):
    captured = _capture(monkeypatch)
    from agri_ai_core.src.ai.tools_agent_external import agent_mcp_call
    agent_mcp_call(server="wikipedia", tool="search_wikipedia",
                   args={"query": "상황버섯", "limit": 3})
    assert captured["args"].get("query") == "상황버섯"
    assert captured["args"].get("limit") == 3
