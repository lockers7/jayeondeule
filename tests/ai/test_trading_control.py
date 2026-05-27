# ══════════════════════════════════════════════════════════════════════════════
# test_trading_control — Phase 2 다양한 관리자 컨트롤(AI 제어 우선) 최소단위 테스트
#
#   test_strategy_preset      : 전략 프리셋 저장·목록·활성화·활성조회
#   test_candidate_status     : 수동 승인/거부(proposed→approved)
#   test_exclusions           : 제외 종목 저장·조회 왕복
#   test_build_control_context: 전략+제외+리스크 통합 AI 주입 컨텍스트
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import trading_store as ts
from agri_ai_core.src.postgresql.connection import db_session


def test_strategy_preset():
    ts.save_strategy("이벤트소수정예", "공시 이벤트 기반, 하루 3종목 이내, 확신도 0.7 이상만")
    ts.save_strategy("실적서프라이즈", "어닝서프라이즈 갭상승 눌림목")
    names = [s["name"] for s in ts.list_strategies()]
    assert "이벤트소수정예" in names and "실적서프라이즈" in names
    ts.activate_strategy("이벤트소수정예")
    act = ts.get_active_strategy()
    assert act.get("name") == "이벤트소수정예" and "공시" in act.get("prompt_text", "")


def test_candidate_status():
    ts.ensure_tables()
    with db_session() as d:
        d.execute_query("INSERT INTO trading_candidate (scan_date, stock_code, stock_name, status) "
                        "VALUES (CURRENT_DATE, 'UTC001', '컨트롤테스트', 'proposed') "
                        "ON CONFLICT (scan_date, stock_code) DO UPDATE SET status='proposed'", ())
    r = ts.set_candidate_status(None, "UTC001", "approved")
    assert r["status"] == "approved"
    approved = ts.list_candidates(status="approved")
    assert any(c["stock_code"] == "UTC001" for c in approved)
    with db_session() as d:
        d.execute_query("DELETE FROM trading_candidate WHERE stock_code='UTC001'", ())


def test_exclusions():
    ts.set_exclusions("삼성전자, 바이오섹터, 000660")
    ex = ts.get_exclusions()
    assert "삼성전자" in ex and "바이오섹터" in ex and "000660" in ex
    ts.set_exclusions([])
    assert ts.get_exclusions() == []


def test_build_control_context():
    ts.save_strategy("UTctx전략", "테스트전략지시_이벤트중심")
    ts.activate_strategy("UTctx전략")
    ts.set_exclusions("제외종목X")
    ts.set_user_data({"capital": "10000000", "max_per_stock": "1000000"})
    ctx = ts.build_control_context()
    assert "관리자 컨트롤" in ctx
    assert "UTctx전략" in ctx and "테스트전략지시_이벤트중심" in ctx
    assert "제외종목X" in ctx
    assert "capital=10000000" in ctx
    ts.set_exclusions([])
