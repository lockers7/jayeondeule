# ══════════════════════════════════════════════════════════════════════════════
# test_kis_order_guard — 한국투자증권 KIS MCP 주문 실행 차단(시세·재무 조회 전용) 검증
#
# 농장주 지시: KIS 연동은 시세·재무 조회만. AI/자율Agent 가 주문(매매)을 낼 수 없게
# 게이트웨이에서 order_* 계열 원천 차단. inquire_*(조회)·*list* 는 허용.
# ══════════════════════════════════════════════════════════════════════════════
import importlib
from agri_ai_core.src.ai import tools_mcp_gateway as gw


def test_order_tools_blocked():
    for t in ("order_cash", "order_credit", "order_rvsecncl", "order_resv",
              "order_resv_ccnl", "order_resv_rvsecncl", "daytime_order", "daytime_order_rvsecncl"):
        assert gw._deny_reason("kis-trading", t), f"{t} 는 차단돼야 함"


def test_read_tools_allowed():
    for t in ("inquire_price", "inquire_asking_price", "inquire_balance",
              "inquire_psbl_order", "order_resv_list", "dailyprice", "inquire_financial_ratio"):
        assert gw._deny_reason("kis-trading", t) is None, f"{t} 는 허용돼야 함(조회)"


def test_other_servers_unaffected():
    assert gw._deny_reason("naver-search", "search_local") is None
    assert gw._deny_reason("korea-weather", "get_nowcast_observation") is None


def test_allow_order_env_opens(monkeypatch):
    # KIS_ALLOW_ORDER=1 이면 개방(농장주가 명시 허용 시에만)
    monkeypatch.setenv("KIS_ALLOW_ORDER", "1")
    assert gw._deny_reason("kis-trading", "order_cash") is None
