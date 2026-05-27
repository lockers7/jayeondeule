# ══════════════════════════════════════════════════════════════════════════════
# test_agent_external_tools — 주기 Agent 외부접속 능력 결합 검증
#
# 주기 Agent(run_agent)가 MCP·웹·기상 등 외부 정보를 조회할 수 있게 됐는지.
# 전부 read-only(제어 위험 0). 검증된 채팅 구현을 얇게 래핑.
#
# 파일 시작 함수 목록:
#   test_wrappers_delegate      : 래퍼가 채팅 구현에 위임하고 dict 반환
#   test_wrappers_validate_args : 필수 인자 누락 시 error dict
#   test_wrappers_swallow_exc   : 하위 예외를 삼켜 error dict (loop 보호)
#   test_registry_and_specs     : 레지스트리·스펙 노출(5개 외부도구)
#   test_merged_into_agent      : Agent TOOL_REGISTRY 에 결합 + read-only(비-write)
#   test_agent_execute_external : Agent _execute_tool 로 외부도구 디스패치
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import tools_agent_external as ext


def test_wrappers_delegate(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.ai.tools_search.search_web",
                        lambda query, n_results=5: {"success": True, "q": query, "n": n_results})
    r = ext.agent_search_web(query="상황버섯 고온 관리", max_results=3)
    assert r["success"] and r["q"] == "상황버섯 고온 관리" and r["n"] == 3

    monkeypatch.setattr("agri_ai_core.src.ai.tools_mcp_gateway.mcp_call",
                        lambda server, tool, args=None, timeout=45: {"success": True, "s": server, "t": tool, "a": args})
    r2 = ext.agent_mcp_call(server="paper-search", tool="search_arxiv", args={"query": "Phellinus linteus"})
    assert r2["s"] == "paper-search" and r2["t"] == "search_arxiv" and r2["a"] == {"query": "Phellinus linteus"}

    monkeypatch.setattr("agri_ai_core.src.ai.tools_mcp_gateway.mcp_list_tools",
                        lambda server=None: {"success": True, "server": server})
    assert ext.agent_mcp_list_tools(server="naver-search")["server"] == "naver-search"

    monkeypatch.setattr("agri_ai_core.src.ai.tools_search.fetch_url_content",
                        lambda url: {"success": True, "url": url})
    assert ext.agent_fetch_url(url="https://x.test")["url"] == "https://x.test"

    monkeypatch.setattr("agri_ai_core.src.ai.tools_data.get_weather_forecast",
                        lambda farm_id=None, house_id=None: {"success": True, "farm": farm_id})
    assert ext.agent_get_weather(farm=1)["farm"] == "1"


def test_wrappers_validate_args():
    assert not ext.agent_search_web(query="")["error"] == ""       # 빈 query → error
    assert "error" in ext.agent_search_web()
    assert "error" in ext.agent_fetch_url()
    assert "error" in ext.agent_mcp_call(server="x")               # tool 누락
    assert "error" in ext.agent_mcp_call(tool="y")                 # server 누락


def test_wrappers_swallow_exc(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("네트워크 끊김")
    monkeypatch.setattr("agri_ai_core.src.ai.tools_search.search_web", boom)
    r = ext.agent_search_web(query="q")
    assert "error" in r and "실패" in r["error"]                    # 예외 → error dict(흐름 보호)


def test_registry_and_specs():
    assert set(ext.TOOL_REGISTRY) == {
        "search_web", "fetch_url_content", "mcp_list_tools", "mcp_call", "get_weather_forecast",
        "get_camera_view", "get_server_resources"}   # +카메라·리소스 read(GAP3/4 보완)
    txt = ext.tool_specs_text()
    assert "외부 정보 조회 도구" in txt
    for name in ext.TOOL_REGISTRY:
        assert name in txt


def test_merged_into_agent():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for name in ("search_web", "mcp_call", "mcp_list_tools", "fetch_url_content", "get_weather_forecast"):
        assert name in ama.TOOL_REGISTRY                # Agent 도구셋에 결합됨
        assert name not in ama._WRITE_TOOL_NAMES        # read-only (제어 위험 없음)
    assert "외부 정보 조회 도구" in ama.tool_specs_text()   # ReAct 프롬프트에 노출


def test_agent_execute_external(monkeypatch):
    from agri_ai_core.src.control import ai_monitor_agent as ama
    monkeypatch.setattr("agri_ai_core.src.ai.tools_search.search_web",
                        lambda query, n_results=5: {"success": True, "q": query})
    out = ama._execute_tool("search_web", {"query": "농자재 시세", "max_results": 5})
    assert out.get("success") and out.get("q") == "농자재 시세"


# ── 임무유형 프롬프트 라우팅 (외부임무 → 외부전용 프롬프트) ──
def test_external_task_detection():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for t in ["웹 검색으로 상황버섯 관리 팁 찾아줘", "논문에서 재배 정보 조사해",
              "농자재 시세 알아봐줘", "기상예보 확인해서 알려줘", "병해충 정보 검색해"]:
        assert ama._is_external_info_task(t), t
    for t in ["1호 습도 확인하고 제어해줘", "재배사 제어 상태 보고",
              "전체 호기 센서값 감시", None, ""]:
        assert not ama._is_external_info_task(t), t


def test_prompt_routing(monkeypatch):
    from agri_ai_core.src.control import ai_monitor_agent as ama
    seen = {}

    def fake_block(block_id, **kw):
        seen["id"] = block_id
        return f"PROMPT[{block_id}]"

    monkeypatch.setattr("agri_ai_core.src.prompt_registry.get_control_block", fake_block)
    ama.build_system_prompt(task="웹 검색으로 논문 찾아줘")
    assert seen["id"] == "CTRL_AGENT_EXTERNAL"          # 외부임무 → 외부전용
    ama.build_system_prompt(task="1호 습도 제어해줘")
    assert seen["id"] == "CTRL_AGENT_SYSTEM"            # 제어임무 → 제어프롬프트
    ama.build_system_prompt(task=None)
    assert seen["id"] == "CTRL_AGENT_SYSTEM"            # 기본 → 제어프롬프트
