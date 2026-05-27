# ══════════════════════════════════════════════════════════════════════════════
# test_trading_trends — Phase 3 최신 매매 방법론 RAG 판단 강화(AI 제어) 단위테스트
#
#   test_seed_trends          : 방법론 10종 시드 저장·목록
#   test_recall_methodology   : 이벤트/공시 질의로 방법론 회상
#   test_build_trend_context  : 최신 방법론 주입 + 전통 TA 배제 지침
# ══════════════════════════════════════════════════════════════════════════════
from agri_ai_core.src.ai import trading_store as ts
from agri_ai_core.src.ai.trading_trend_seed import seed_trading_trends, TREND_DOCS


def test_seed_trends():
    r = seed_trading_trends(force=True)
    assert r["success"] and r["seeded"] == len(TREND_DOCS)
    lst = ts.list_trading_knowledge(category="방법론", limit=100)
    texts = " ".join(x.get("text") or "" for x in lst)
    assert "카탈리스트" in texts and "실적서프라이즈" in texts and "배제" in texts


def test_recall_methodology():
    seed_trading_trends()
    rec = ts.recall_trading_knowledge("공시 이벤트 카탈리스트 기반 매매 방법")
    assert isinstance(rec, list) and len(rec) >= 1


def test_build_trend_context():
    seed_trading_trends()
    ctx = ts.build_trend_context()
    assert "전통 TA" in ctx and "배제" in ctx
    assert "차트패턴" in ctx or "이동평균" in ctx
    assert ctx.count("- ") >= 1     # 방법론 불릿 주입
