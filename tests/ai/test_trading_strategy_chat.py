# ══════════════════════════════════════════════════════════════════════════════
# test_trading_strategy_chat — 자연어(말로 한) 매매전략 → 활성 전략 → LLM 주입 검증
#   농장주가 채팅으로 철학을 말하면 set_trading_strategy 로 저장·활성화되고,
#   build_control_context 를 통해 매 자동매매 실행에 주입되는지 확인.
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import trading_store as ts


def test_set_strategy_from_natural_language():
    txt = "앞으로 자사주 매입·실적 서프라이즈 호재 종목 위주로, 하루 3종목 이내로 신중하게 매매하라"
    r = ts.set_trading_strategy(txt, name="철학_소수정예")
    assert r["success"] and r["active"]
    act = ts.get_active_strategy()
    assert act.get("name") == "철학_소수정예" and "자사주" in act.get("prompt_text", "")


def test_strategy_injected_into_control_context():
    ts.set_trading_strategy("리스크 관리를 최우선으로, 확신 없으면 매매하지 말라", name="철학_리스크우선")
    ctx = ts.build_control_context()
    assert "철학_리스크우선" in ctx and "리스크 관리" in ctx


def test_short_strategy_rejected():
    r = ts.set_trading_strategy("응")
    assert not r["success"]


def test_registered_in_db_tool_source():
    # USE_DB_TOOLS=1 1순위 소스(tool_definition_m)에 등록됐는지
    from agri_ai_core.src.postgresql.connection import db_session
    with db_session() as d:
        row = d.fetch_one("SELECT active_yn FROM tool_definition_m WHERE tool_id='set_trading_strategy'", ())
    assert row is not None and dict(row)["active_yn"] == "Y"
