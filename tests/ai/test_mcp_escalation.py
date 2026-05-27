# ══════════════════════════════════════════════════════════════════════════════
# test_mcp_escalation — 채팅 파이프라인 MCP 적응 에스컬레이션 보완 검증(①~⑤)
#
# 원하는 구조: 질문분석 → 웹검색 → (부족판단) → 필요한 MCP 찾아 연결 → 추가수집 → 답변.
#   ① validator 보충도구에 mcp_list_tools/mcp_call/manage_mcp_server + 에스컬레이션 규칙
#   ② 보충 라운드 2 (_MAX_SUPPLEMENT_ROUNDS)
#   ③ MCP 카탈로그 RAG(정보요구→적합 MCP) 회상
#   ④ ANALYZER·validator 프롬프트에 manage_mcp_server 노출
#   ⑤ 외부검색형(search_web)은 rule 사전통과 금지 → 검증 거쳐 MCP 기회
#   + 결정론적 배선: 부족→validator가 mcp_call 제안→DataCollector 실행
#
# 파일 시작 함수 목록:
#   test_validator_prompt_has_mcp_escalation : ①④ validator
#   test_supplement_rounds_two               : ②
#   test_mcp_catalog_seeded_recalled         : ③
#   test_analyzer_prompt_has_manage_mcp      : ④ analyzer
#   test_rule_skip_gated_by_web              : ⑤
#   test_pipeline_executes_mcp_supplement    : 통합 배선(부족→MCP 실행)
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai.pipeline import data_collector as dc


def test_validator_prompt_has_mcp_escalation():
    from agri_ai_core.src.ai.pipeline.prompts import get_data_validator_prompt
    p = get_data_validator_prompt()
    for kw in ("mcp_list_tools", "mcp_call", "manage_mcp_server", "MCP 에스컬레이션 규칙"):
        assert kw in p, kw


def test_supplement_rounds_two():
    assert dc._MAX_SUPPLEMENT_ROUNDS >= 2


def test_mcp_catalog_seeded_recalled():
    from agri_ai_core.src.ai import mcp_catalog as cat
    keys = {k for k, _ in cat.CATALOG_DOCS}
    assert {"mcpcat_overview", "mcpcat_paper", "mcpcat_naver", "mcpcat_time_unreg"} <= keys
    cat.seed_mcp_catalog()
    from agri_ai_core.src.ai.system_knowledge import recall_system_knowledge
    r = recall_system_knowledge("상황버섯 최신 연구논문 찾아줘")
    assert "paper-search" in r                       # 정보요구→적합 MCP 회상
    r2 = recall_system_knowledge("현재 시각과 타임존 변환")
    # time MCP 는 2026-07-25 등록됨 → 카탈로그가 get_current_time 사용법을 안내(회상)
    assert "get_current_time" in r2 or "convert_time" in r2 or "server='time'" in r2


def test_analyzer_prompt_has_manage_mcp():
    from agri_ai_core.src.ai.pipeline.prompts import get_analyzer_system_prompt
    p = get_analyzer_system_prompt()
    assert "manage_mcp_server" in p and "mcp_call" in p


def _neutralize_safety_nets(monkeypatch, collector):
    for m in ("_ensure_admin_directive", "_ensure_weather_data", "_ensure_control_mode"):
        monkeypatch.setattr(collector, m, lambda *a, **k: None)


def test_rule_skip_gated_by_web(monkeypatch):
    # ⑤ search_web 개입 시 수집량이 커도 rule 통과 금지 → LLM 검증 실행
    calls = {"validate": 0}

    def _val(q, a, s):
        calls["validate"] += 1
        return {"sufficient": True, "reason": "", "supplement": []}
    monkeypatch.setattr("agri_ai_core.src.ai.pipeline.validators.validate_with_llm", _val)
    monkeypatch.setattr("agri_ai_core.src.ai.pipeline.validators.summarize_collected_data",
                        lambda d: "요약")

    collector = dc.DataCollector(default_tool_args={})
    _neutralize_safety_nets(monkeypatch, collector)

    def fake_exec(tasks, uq):
        collector.collected_data.append({"tool": "search_web", "result": "x" * 7000})
        collector.tools_used.append("search_web")
    monkeypatch.setattr(collector, "_execute_tasks", fake_exec)

    collector.collect({"required_data": [{"tool": "search_web", "args": {"query": "정읍 특산물"}}],
                       "question_type": "web_search", "intent": "정읍 특산물"})
    assert calls["validate"] >= 1        # 웹개입 → 검증됨(과거엔 rule-skip 됐을 상황)


def test_pipeline_executes_mcp_supplement(monkeypatch):
    # 통합 배선: 웹부족 → validator가 mcp_call 보충 제안 → DataCollector 가 실제 실행
    executed = []

    def fake_execute_tool(tool_name, args):
        executed.append(tool_name)
        if tool_name == "search_web":
            return '{"results":[{"title":"일반정보","url":"http://x"}]}'   # 부족
        if tool_name == "mcp_call":
            return '{"result":"Phellinus linteus 재배 논문 3건: ..."}'      # 충분
        return "{}"
    monkeypatch.setattr("agri_ai_core.src.ai.tools_executor.execute_tool", fake_execute_tool)
    monkeypatch.setattr("agri_ai_core.src.ai.llm_client._refine_tool_result",
                        lambda t, r, q: r)

    seq = [
        {"sufficient": False, "reason": "논문 근거 부족",
         "supplement": [{"tool": "mcp_call",
                         "args": {"server": "paper-search", "tool": "search_arxiv",
                                  "args": {"query": "Phellinus linteus"}}}]},
        {"sufficient": True, "reason": "논문 확보", "supplement": []},
    ]
    monkeypatch.setattr("agri_ai_core.src.ai.pipeline.validators.summarize_collected_data",
                        lambda d: "요약")
    monkeypatch.setattr("agri_ai_core.src.ai.pipeline.validators.validate_with_llm",
                        lambda q, a, s: seq.pop(0) if seq else {"sufficient": True, "supplement": []})

    collector = dc.DataCollector(default_tool_args={})
    _neutralize_safety_nets(monkeypatch, collector)
    result = collector.collect({
        "required_data": [{"tool": "search_web", "args": {"query": "상황버섯 연구"}}],
        "question_type": "web_search", "intent": "상황버섯 연구논문"})

    assert "search_web" in executed and "mcp_call" in executed     # 웹→MCP 에스컬레이션 실행
    assert "mcp_call" in collector.tools_used
