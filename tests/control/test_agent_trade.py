# ══════════════════════════════════════════════════════════════════════════════
# test_agent_trade — Agent 국내주식 자동매매(Phase 1) 결합 검증
#
# 로컬 AI Agent 가 공시 이벤트 스캔→후보 선정·저장→관리자 승인요청까지 수행하는지.
# ⛔ Phase 1 은 실제 주문 없음(후보·승인요청까지). KIS 주문은 Phase 2(승인 게이트).
#
# 파일 시작 함수 목록:
#   test_scan_normalizes         : DART 결과 정규화(종목코드 필터·이벤트 목록)
#   test_scan_success_flag       : mcp_call 실패 시 error 전파
#   test_save_validates          : stock_code 필수
#   test_save_list_approval       : 저장→조회→승인요청(카카오) 라운드트립(+정리)
#   test_merged_into_agent        : Agent 도구셋 결합 + 비 농장제어-write
#   test_trading_task_routing     : 매매임무→CTRL_AGENT_TRADE (제어/코딩과 분리)
#   test_trade_cap_and_steps      : 트레이딩 캡·단계가 조회보다 큼(다건 저장)
#   test_prompt_in_db             : CTRL_AGENT_TRADE 프롬프트 존재
# ══════════════════════════════════════════════════════════════════════════════
import json

from agri_ai_core.src.ai import tools_agent_trade as tr


def test_scan_normalizes(monkeypatch):
    payload = {"status": "000", "total_count": 3, "list": [
        {"stock_code": "005810", "corp_name": "풍산홀딩스", "report_nm": "자기주식취득결정", "rcept_dt": "20260723"},
        {"stock_code": "", "corp_name": "비상장사", "report_nm": "감사보고서", "rcept_dt": "20260723"},  # 제외
        {"stock_code": "028080", "corp_name": "휴맥스홀딩스", "report_nm": "회사합병결정", "rcept_dt": "20260723"},
    ]}
    monkeypatch.setattr("agri_ai_core.src.ai.tools_mcp_gateway.mcp_call",
                        lambda server, tool, args=None, timeout=45: {"success": True, "result": json.dumps(payload)})
    r = tr.agent_scan_stock_events(scan_type="B")
    assert r["success"] and r["count"] == 2                # 종목코드 없는 건 제외
    assert "005810" in r["events"] and "028080" in r["events"]   # 컴팩트 요약에 종목코드
    assert "비상장사" not in r["events"]                          # 종목코드 없는 건 미노출


def test_scan_success_flag(monkeypatch):
    monkeypatch.setattr("agri_ai_core.src.ai.tools_mcp_gateway.mcp_call",
                        lambda server, tool, args=None, timeout=45: {"success": False, "error": "DART 다운"})
    assert not tr.agent_scan_stock_events()["success"]


def test_save_validates():
    assert not tr.agent_save_trade_candidate(stock_name="x")["success"]   # stock_code 누락


def test_save_list_approval(monkeypatch):
    # 저장 → 조회 → 승인요청(카카오 stub) 라운드트립. 테스트 종목은 정리.
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        d.execute_query("DELETE FROM trading_candidate WHERE stock_code='TSTT01'", ())
    r = tr.agent_save_trade_candidate(stock_code="TSTT01", stock_name="테스트종목",
                                      event_type="자기주식취득결정", thesis="테스트 논거",
                                      target_buy=1000, target_sell=1150, stop_loss=950,
                                      expected_return_pct=15, confidence=0.8)
    assert r["success"]
    lst = tr.agent_list_trade_candidates()
    assert any(c["stock_code"] == "TSTT01" for c in lst["candidates"])

    sent = {}
    monkeypatch.setattr("agri_ai_core.src.ai.kakao_notify.push_alert",
                        lambda level, title, body, web_url=None: sent.update(title=title, body=body))
    ap = tr.agent_request_trade_approval()
    assert ap["success"] and ap["requested"] >= 1 and "승인요청" in sent.get("title", "")

    with db_session() as d:
        d.execute_query("DELETE FROM trading_candidate WHERE stock_code='TSTT01'", ())


def test_merged_into_agent():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for n in ("scan_stock_events", "save_trade_candidate",
              "list_trade_candidates", "request_trade_approval"):
        assert n in ama.TOOL_REGISTRY
        assert n in ama._TRADE_TOOL_NAMES
        assert n not in ama._WRITE_TOOL_NAMES        # 농장제어-write 아님
    assert "트레이딩 도구" in ama.tool_specs_text()


def test_trading_task_routing(monkeypatch):
    from agri_ai_core.src.control import ai_monitor_agent as ama
    for t in ["장 마감 후 공시 이벤트 스캔해서 내일 매매 종목 선정",
              "자동매매 후보 종목 뽑아줘", "주식 트레이딩 종목 추천"]:
        assert ama._is_trading_task(t), t
    assert not ama._is_trading_task("전체 재배사 제어")
    assert not ama._is_coding_task("내일 매매 종목 선정")   # 매매가 코딩보다 우선
    seen = {}
    monkeypatch.setattr("agri_ai_core.src.prompt_registry.get_control_block",
                        lambda block_id, **kw: (seen.update(id=block_id), f"P[{block_id}]")[1])
    ama.build_system_prompt(task="내일 매매할 종목 선정해줘")
    assert seen["id"] == "CTRL_AGENT_TRADE"


def test_trade_cap_and_steps():
    from agri_ai_core.src.control import ai_monitor_agent as ama
    assert ama._MAX_TRADE_TOOL_CALLS > ama._MAX_READ_TOOL_CALLS      # 다건 저장 허용
    assert ama.AGENT_TRADE_MAX_STEPS > ama.AGENT_MAX_STEPS


def test_prompt_in_db():
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        r = d.fetch_one("SELECT body_text FROM control_prompt_m WHERE block_id='CTRL_AGENT_TRADE'", ())
    body = dict(r)["body_text"] if r else ""
    assert "매매 종목 선정 절차" in body and "save_trade_candidate" in body
